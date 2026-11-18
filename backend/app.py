"""FastAPI 接口、SSE 与构建后的前端静态文件。"""

import asyncio
import json
import time
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, HTTPException, Request
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


def create_app(settings: Settings | None = None, *, model=None, search=None) -> FastAPI:
    configured = settings or Settings.load()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        configured.data_dir.mkdir(parents=True, exist_ok=True)
        store = Store(configured.data_dir / "lifelab.db")
        async with httpx.AsyncClient(follow_redirects=False) as client:
            async with AsyncSqliteSaver.from_conn_string(str(configured.data_dir / "checkpoints.db")) as saver:
                await saver.setup()
                workflow = RetrievalWorkflow(
                    store, model or DeepSeekModel(),
                    search or ZhihuSearch(configured.zhihu_secret, client), saver,
                )
                service = RetrievalService(configured, store, workflow)
                app.state.store = store
                app.state.service = service
                path_store = PathStore(store)
                path_service = PathService(configured, path_store, PathWorkflow(path_store, model or DeepSeekModel(), saver))
                app.state.path_store = path_store
                app.state.path_service = path_service
                await service.recover()
                await path_service.recover()
                yield
                await path_service.close()
                await service.close()

    app = FastAPI(title="人生实验室", lifespan=lifespan)

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
            "model_configured": bool(current.deepseek_key) or model is not None,
            "zhihu_configured": bool(current.zhihu_secret) or search is not None,
        }

    @app.post("/api/runs", status_code=202)
    async def create(body: RunInput):
        status = health()
        if not status["model_configured"] or not status["zhihu_configured"]:
            raise HTTPException(503, "请先在服务端 .env 中填写 DeepSeek Key 与知乎 Access Secret")
        return app.state.service.create(body.question)

    @app.get("/api/runs")
    def list_runs():
        return app.state.store.list()

    @app.get("/api/runs/{run_id}")
    def get_run(run_id: str):
        return existing(run_id)

    @app.post("/api/runs/{run_id}/resume", status_code=202)
    async def resume(run_id: str, answer: ResumeInput):
        existing(run_id)
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
            while not await request.is_disconnected():
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
            raise HTTPException(503, "请先在服务端配置 DeepSeek Key")
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
            while not await request.is_disconnected():
                for event in app.state.path_store.events(path_id, cursor):
                    cursor = event["sequence"]
                    yield f"id: {cursor}\nevent: trace\ndata: {json.dumps(event, ensure_ascii=False)}\n\n"
                if time.monotonic() - heartbeat > 10:
                    yield ": heartbeat\n\n"
                    heartbeat = time.monotonic()
                await asyncio.sleep(0.3)
        return StreamingResponse(stream(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    dist = ROOT / "frontend" / "dist"
    if (dist / "assets").is_dir():
        app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    async def frontend(path: str):
        if path.startswith("api/"):
            raise HTTPException(404, "接口不存在")
        if not (dist / "index.html").is_file():
            raise HTTPException(404, "前端尚未构建，请启动 Vite 或先运行 npm run build")
        return FileResponse(dist / "index.html")

    return app


app = create_app()
