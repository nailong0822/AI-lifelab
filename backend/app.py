"""FastAPI 接口、SSE 与构建后的前端静态文件。"""

import asyncio
import json
import time
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, HTTPException, Request, Query
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from .config import ROOT, Settings
from .models import ResumeInput, RunInput
from .providers import DeepSeekModel, ZhihuSearch
from .service import RetrievalService, RunConflict
from .store import Store
from .workflow import RetrievalWorkflow
from .path_models import JourneyUpdate, PathResponse, PathSelection, PlanRevision, ProgressUpdate, StageRequest
from .path_store import PathConflict, PathStore
from .paths import PathService, PathWorkflow
from .companion import CompanionService
from .companion_api import install_companion_routes
from .web_search import TavilyProvider
from .experiences import ExperienceService
from .experience_api import install_experience_routes
from .auth import AuthStore, current_user, COOKIE_NAME
from .auth_api import install_auth_routes
from .user_model import UserModelRouter


def create_app(settings: Settings | None = None, *, model=None, search=None, web_provider=None) -> FastAPI:
    configured = settings or Settings.load()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        configured.data_dir.mkdir(parents=True, exist_ok=True)
        store = Store(configured.data_dir / "lifelab.db")
        auth=AuthStore(store,platform_key=lambda: (configured if settings is not None else Settings.load()).deepseek_key)
        app.state.auth=auth
        user_model=UserModelRouter(auth,model)
        async with httpx.AsyncClient(follow_redirects=False) as client:
            async with AsyncSqliteSaver.from_conn_string(str(configured.data_dir / "checkpoints.db")) as saver:
                await saver.setup()
                workflow = RetrievalWorkflow(
                    store, user_model,
                    search or ZhihuSearch(configured.zhihu_secret, client), saver,
                )
                service = RetrievalService(configured, store, workflow)
                app.state.store = store
                app.state.service = service
                path_store = PathStore(store)
                path_service = PathService(configured, path_store, PathWorkflow(path_store, user_model, saver))
                app.state.path_store = path_store
                app.state.path_service = path_service
                companion = CompanionService(configured, path_store, path_service, user_model, saver,
                    web_provider=web_provider or (TavilyProvider(configured.tavily_key,client) if configured.tavily_key else None))
                app.state.companion = companion
                experiences=ExperienceService(configured,path_store,companion,user_model)
                app.state.experiences=experiences
                workflow.experiences=experiences.store
                await service.recover()
                await path_service.recover()
                await companion.recover()
                await experiences.recover()
                yield
                await experiences.close()
                await companion.close()
                await path_service.close()
                await service.close()

    app = FastAPI(title="人生实验室", lifespan=lifespan)
    install_auth_routes(app)

    def existing(run_id: str):
        try:
            return app.state.store.snapshot(run_id)
        except KeyError:
            raise HTTPException(404, "任务不存在")

    @app.get("/api/health")
    def health():
        current = configured if settings is not None else Settings.load()
        return {
            "status": "ok", "model": "deepseek-flash",
            "model_configured": bool(current_user.get() and app.state.auth.user(current_user.get()['id'])['model_configured']),
            "zhihu_configured": bool(current.zhihu_secret) or search is not None,
        }

    @app.post("/api/runs", status_code=202)
    async def create(body: RunInput):
        status = health()
        if not status["model_configured"] or not status["zhihu_configured"]:
            raise HTTPException(503, "请先配置个人DeepSeek API Key，并确认平台知乎搜索服务已配置")
        return app.state.service.create(body.question,owner_id=current_user.get()['id'])

    @app.get("/api/runs")
    def list_runs():
        return app.state.store.list(owner_id=current_user.get()['id'])

    @app.get('/api/archive')
    def archive(page: int = Query(default=1, ge=1, le=1000000),
                search: str = Query(default='', max_length=500),
                status: str = Query(default='all', pattern='^(all|finished|running)$')):
        return app.state.store.archive(current_user.get()['id'], page=page, search=search, status=status)

    @app.get("/api/runs/{run_id}")
    def get_run(run_id: str):
        return existing(run_id)

    @app.post("/api/runs/{run_id}/resume", status_code=202)
    async def resume(run_id: str, answer: ResumeInput):
        existing(run_id)
        if not health()['model_configured']:
            raise HTTPException(409,'请先在模型设置中填写自己的DeepSeek API Key')
        try:
            return await app.state.service.resume(run_id, answer)
        except RunConflict as error:
            raise HTTPException(409, str(error))

    @app.post("/api/runs/{run_id}/cancel")
    async def cancel(run_id: str):
        existing(run_id)
        return await app.state.service.cancel(run_id)

    @app.get("/api/runs/{run_id}/report")
    def report(run_id: str):
        run = existing(run_id)
        if not run["report"]:
            raise HTTPException(409, "报告仍在生成")
        return run["report"]

    @app.get("/api/runs/{run_id}/events")
    async def events(run_id: str, request: Request, after: int = 0):
        existing(run_id)
        try:
            cursor = max(0, after, int(request.headers.get("last-event-id") or 0))
        except ValueError:
            raise HTTPException(422, "事件游标格式错误")

        async def stream():
            nonlocal cursor
            heartbeat = time.monotonic()
            while not await request.is_disconnected() and app.state.auth.authenticate(request.cookies.get(COOKIE_NAME)):
                rows = app.state.store.events(run_id, cursor)
                for event in rows:
                    cursor = event["sequence"]
                    yield f"id: {cursor}\nevent: trace\ndata: {json.dumps(event, ensure_ascii=False)}\n\n"
                run = app.state.store.get(run_id)
                terminal = run["status"] in ("finished", "failed", "cancelled")
                if terminal and cursor >= run["last_event_sequence"]:
                    yield "event: settled\ndata: {}\n\n"
                    break
                if time.monotonic() - heartbeat >= 10:
                    yield ": heartbeat\n\n"
                    heartbeat = time.monotonic()
                await asyncio.sleep(0.25)

        return StreamingResponse(
            stream(), media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    def path_existing(path_id):
        try:
            return app.state.path_store.snapshot(path_id)
        except KeyError:
            raise HTTPException(404, "路径任务不存在")

    async def path_action(path_id, method, *args):
        path_existing(path_id)
        if not health()['model_configured']:
            raise HTTPException(409,'请先在模型设置中填写自己的DeepSeek API Key')
        try:
            return await method(path_id, *args)
        except PathConflict as error:
            raise HTTPException(409, str(error))

    @app.get("/api/runs/{run_id}/paths")
    def get_paths_for_run(run_id: str):
        existing(run_id)
        path = app.state.path_store.for_retrieval(run_id)
        return app.state.path_store.snapshot(path["id"]) if path else None

    @app.post("/api/runs/{run_id}/paths", status_code=202)
    async def create_paths(run_id: str):
        source = existing(run_id)
        if not health()["model_configured"]:
            raise HTTPException(409, "请先在模型设置中填写自己的DeepSeek API Key")
        try:
            return await app.state.path_service.create(source)
        except PathConflict as error:
            raise HTTPException(409, str(error))

    @app.get("/api/paths/{path_id}")
    def get_path(path_id: str):
        return path_existing(path_id)

    @app.post("/api/paths/{path_id}/respond", status_code=202)
    async def respond_path(path_id: str, body: PathResponse):
        return await path_action(path_id, app.state.path_service.respond, body)

    @app.post("/api/paths/{path_id}/select", status_code=202)
    async def select_path(path_id: str, body: PathSelection):
        return await path_action(path_id, app.state.path_service.select, body)

    @app.post("/api/paths/{path_id}/revise", status_code=202)
    async def revise_path(path_id: str, body: PlanRevision):
        return await path_action(path_id, app.state.path_service.revise, body)

    @app.post("/api/paths/{path_id}/expand", status_code=202)
    async def expand_path(path_id: str, body: StageRequest):
        return await path_action(path_id, app.state.path_service.expand, body)

    @app.post("/api/paths/{path_id}/advance", status_code=202)
    async def advance_path(path_id: str, body: StageRequest):
        return await path_action(path_id, app.state.path_service.advance, body)

    @app.post("/api/paths/{path_id}/retry", status_code=202)
    async def retry_path(path_id: str):
        return await path_action(path_id, app.state.path_service.retry)

    @app.patch("/api/paths/{path_id}/progress")
    def update_path_progress(path_id: str, body: ProgressUpdate):
        path_existing(path_id)
        try:
            app.state.path_store.update_progress(path_id, body)
        except PathConflict as error:
            raise HTTPException(409, str(error))
        return path_existing(path_id)

    @app.patch("/api/paths/{path_id}/journey")
    def update_journey(path_id: str, body: JourneyUpdate):
        path_existing(path_id)
        app.state.path_store.change(path_id, {"journey_status": "paused" if body.paused else "active"},
                                    event_type="journey.paused" if body.paused else "journey.resumed",
                                    title="这段探索已暂停" if body.paused else "继续这段探索")
        return path_existing(path_id)

    @app.get("/api/paths/{path_id}/versions/{version}")
    def get_path_version(path_id: str, version: int):
        path_existing(path_id)
        try:
            return app.state.path_store.version(path_id, version)
        except KeyError:
            raise HTTPException(404, "计划版本不存在")

    @app.get("/api/paths/{path_id}/events")
    async def path_events(path_id: str, request: Request, after: int = 0):
        path_existing(path_id)
        try:
            cursor = max(0, after, int(request.headers.get("last-event-id") or 0))
        except ValueError:
            raise HTTPException(422, "事件游标格式错误")
        async def stream():
            nonlocal cursor
            heartbeat = time.monotonic()
            while not await request.is_disconnected() and app.state.auth.authenticate(request.cookies.get(COOKIE_NAME)):
                for event in app.state.path_store.events(path_id, cursor):
                    cursor = event["sequence"]
                    yield f"id: {cursor}\nevent: trace\ndata: {json.dumps(event, ensure_ascii=False)}\n\n"
                if time.monotonic() - heartbeat > 10:
                    yield ": heartbeat\n\n"
                    heartbeat = time.monotonic()
                await asyncio.sleep(0.3)
        return StreamingResponse(stream(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    install_companion_routes(app, health)
    install_experience_routes(app,health)

    dist = ROOT / "frontend" / "dist"
    if (dist / "assets").is_dir():
        app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")
    mascot = dist / 'mascot' if (dist / 'mascot').is_dir() else ROOT / 'frontend' / 'public' / 'mascot'
    app.mount('/mascot', StaticFiles(directory=mascot, check_dir=False), name='mascot')
    station = dist / 'station' if (dist / 'station').is_dir() else ROOT / 'frontend' / 'public' / 'station'
    app.mount('/station', StaticFiles(directory=station, check_dir=False), name='station')

    @app.get("/{path:path}", include_in_schema=False)
    async def frontend(path: str):
        if path.startswith("api/"):
            raise HTTPException(404, "接口不存在")
        if not (dist / "index.html").is_file():
            raise HTTPException(404, "前端尚未构建，请启动 Vite 或先运行 npm run build")
        return FileResponse(dist / "index.html")

    return app


app = create_app()
