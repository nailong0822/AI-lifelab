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
                await service.recover()
                yield
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
