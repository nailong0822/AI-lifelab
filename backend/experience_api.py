"""Journey review, consent and anonymous-case read endpoints."""
from fastapi import HTTPException, Response
from .experience_models import JourneyFinish, ExperienceEdit, ExperienceConsent
from .path_store import PathConflict


def install_experience_routes(app,health):
    def service():
        return app.state.experiences

    def read(callback,*args):
        try:
            return callback(*args)
        except KeyError:
            raise HTTPException(404,'案例或路径不存在，或分享已撤回')
        except PathConflict as error:
            raise HTTPException(409,str(error))

    @app.get('/api/paths/{path_id}/experiences')
    def list_cases(path_id: str,response: Response):
        response.headers['Cache-Control']='no-store'
        read(service().paths.get,path_id)
        return service().store.list(path_id)

    @app.post('/api/paths/{path_id}/experiences',status_code=202)
    async def finish(path_id: str,body: JourneyFinish):
        if not health()['model_configured']:
            raise HTTPException(503,'请先配置 DeepSeek Key')
        try:
            return await service().start(path_id,body)
        except KeyError:
            raise HTTPException(404,'路径不存在')
        except PathConflict as error:
            raise HTTPException(409,str(error))

    @app.get('/api/experiences/{case_id}')
    def get_case(case_id: str,response: Response):
        response.headers['Cache-Control']='no-store'
        return read(service().store.get,case_id)

    @app.put('/api/experiences/{case_id}')
    def edit_case(case_id: str,body: ExperienceEdit):
        return read(service().store.save_document,case_id,body)

    @app.post('/api/experiences/{case_id}/share')
    def share_case(case_id: str,body: ExperienceConsent):
        return read(service().store.publish,case_id,body.revision)

    @app.delete('/api/experiences/{case_id}/share')
    def withdraw_case(case_id: str):
        return read(service().store.withdraw,case_id)

    @app.post('/api/experiences/{case_id}/retry',status_code=202)
    async def retry(case_id: str):
        if not health()['model_configured']:
            raise HTTPException(503,'请先配置 DeepSeek Key')
        try:
            return await service().retry(case_id)
        except KeyError:
            raise HTTPException(404,'案例不存在')
        except PathConflict as error:
            raise HTTPException(409,str(error))

    @app.get('/api/shared-cases/{case_id}')
    def public_case(case_id: str,response: Response):
        response.headers['Cache-Control']='no-store'
        return read(service().store.public,case_id)
