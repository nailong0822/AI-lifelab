"""随航伙伴 HTTP 与可重放 SSE。"""
import asyncio
import json
import time
from fastapi import HTTPException, Request
from fastapi.responses import StreamingResponse
from .companion_models import CompanionMessage, ActionDecision, MemoryUpdate
from .path_store import PathConflict
from .auth import COOKIE_NAME, current_user

def install_companion_routes(app, health):
    def service():
        return app.state.companion

    def read(callback, *args, **kwargs):
        try:
            return callback(*args, **kwargs)
        except KeyError:
            raise HTTPException(404, '会话、任务或记忆不存在')
        except PathConflict as error:
            raise HTTPException(409, str(error))

    async def act(callback, *args):
        try:
            return await callback(*args)
        except KeyError:
            raise HTTPException(404, '会话、任务或操作不存在')
        except PathConflict as error:
            raise HTTPException(409, str(error))

    @app.post('/api/companion/personal')
    def personal_companion_session():
        session = service().store.global_session(current_user.get()['id'])
        return service().store.snapshot(session['id'])

    @app.post('/api/paths/{path_id}/companion/sessions')
    def create_companion_session(path_id: str):
        session = read(service().store.session, path_id)
        return service().store.snapshot(session['id'])

    @app.get('/api/companion/sessions/{session_id}/messages')
    def companion_messages(session_id: str, before: int | None = None):
        return read(service().store.snapshot, session_id, before=before)

    @app.post('/api/companion/sessions/{session_id}/messages', status_code=202)
    async def companion_send(session_id: str, body: CompanionMessage):
        if not health()['model_configured']:
            raise HTTPException(409, '请先在模型设置中填写自己的DeepSeek API Key')
        return await act(service().send, session_id, body)

    @app.post('/api/companion/turns/{turn_id}/retry', status_code=202)
    async def companion_retry(turn_id: str):
        if not health()['model_configured']:
            raise HTTPException(409, '请先在模型设置中填写自己的DeepSeek API Key')
        return await act(service().retry, turn_id)

    @app.post('/api/companion/actions/{action_id}/respond', status_code=202)
    async def companion_decide(action_id: str, body: ActionDecision):
        return await act(service().decide, action_id, body.approve)

    @app.post('/api/companion/actions/{action_id}/undo')
    async def companion_undo(action_id: str):
        return await act(service().undo, action_id)

    @app.get('/api/paths/{path_id}/companion/memories')
    def companion_memories(path_id: str):
        read(service().paths.get, path_id)
        return service().store.memories(path_id)

    @app.patch('/api/companion/memories/{memory_id}')
    def companion_edit_memory(memory_id: str, body: MemoryUpdate):
        read(service().store.edit_memory, memory_id, body.value)
        return {'ok': True}

    @app.delete('/api/companion/memories/{memory_id}')
    def companion_delete_memory(memory_id: str):
        read(service().store.edit_memory, memory_id)
        return {'ok': True}

    @app.get('/api/companion/sessions/{session_id}/events')
    async def companion_events(session_id: str, request: Request, after: int = 0):
        read(service().store.get, 'sessions', session_id)
        try:
            cursor = min(2**63-1, max(0, after, int(request.headers.get('last-event-id') or 0)))
        except ValueError:
            raise HTTPException(422, '事件游标格式错误')
        async def stream():
            nonlocal cursor
            heartbeat = time.monotonic()
            while not await request.is_disconnected() and app.state.auth.authenticate(request.cookies.get(COOKIE_NAME)):
                for event in service().store.events(session_id, cursor):
                    cursor = event['sequence']
                    yield f'id: {cursor}\nevent: trace\ndata: {json.dumps(event, ensure_ascii=False)}\n\n'
                if time.monotonic() - heartbeat >= 10:
                    yield ': heartbeat\n\n'
                    heartbeat = time.monotonic()
                await asyncio.sleep(.3)
        return StreamingResponse(stream(), media_type='text/event-stream', headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'})
