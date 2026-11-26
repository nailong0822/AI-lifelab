"""Authentication and administrator endpoints."""
from typing import Literal
from urllib.parse import urlsplit
import httpx
from fastapi import HTTPException, Request, Response, Query
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from fastapi.exception_handlers import request_validation_exception_handler
from pydantic import Field, SecretStr, field_validator
from .auth import COOKIE_NAME, SESSION_SECONDS, current_user
from .models import Contract


class Credentials(Contract):
    username: str = Field(min_length=3,max_length=32)
    password: SecretStr = Field(min_length=8,max_length=128)


class Registration(Credentials):
    role: Literal['user','admin']='user'
    invitation: SecretStr = Field(default=SecretStr(''),max_length=100)


class ModelKey(Contract):
    api_key: SecretStr = Field(min_length=8,max_length=512)

    @field_validator('api_key')
    @classmethod
    def validate_key(cls,value):
        key=value.get_secret_value().strip()
        if len(key)<8 or any(c.isspace() for c in key):
            raise ValueError('API Key需至少8个字符，且不能含空白字符')
        return SecretStr(key)


def install_auth_routes(app):
    def auth():
        return app.state.auth

    @app.exception_handler(RequestValidationError)
    async def validation_error(request,error):
        if request.url.path.startswith('/api/auth/'):
            return JSONResponse({'detail':[{k:item[k] for k in ('loc','msg','type')} for item in error.errors()]},
                                status_code=422,headers={'Cache-Control':'no-store'})
        return await request_validation_exception_handler(request,error)

    @app.middleware('http')
    async def authenticate(request,call_next):
        path=request.url.path
        if not path.startswith('/api/'):
            return await call_next(request)
        try:
            if request.method not in ('GET','HEAD','OPTIONS'):
                origin=request.headers.get('origin')
                if origin and (urlsplit(origin).scheme,urlsplit(origin).netloc)!=(request.url.scheme,request.url.netloc):
                    raise HTTPException(403,'请求来源不匹配，请从当前站点操作')
                if request.headers.get('sec-fetch-site')=='cross-site':
                    raise HTTPException(403,'请求来源不匹配')
            principal=auth().authenticate(request.cookies.get(COOKIE_NAME))
            public=path in ('/api/auth/login','/api/auth/register','/api/auth/me')
            public=public or path.startswith('/api/shared-cases/') and request.method in ('GET','HEAD')
            if not principal and not public:
                raise HTTPException(401,'请先登录')
            if principal:
                auth().assert_access(path,principal)
            token=current_user.set(principal)
            try:
                response=await call_next(request)
                response.headers['Cache-Control']='no-store'
                return response
            finally:
                current_user.reset(token)
        except HTTPException as error:
            return JSONResponse({'detail':error.detail},status_code=error.status_code,headers={'Cache-Control':'no-store'})

    def session(user,request,response):
        auth().logout(request.cookies.get(COOKIE_NAME))
        token=auth().new_session(user['id'])
        response.set_cookie(COOKIE_NAME,token,max_age=SESSION_SECONDS,httponly=True,
                            secure=request.url.scheme=='https',samesite='lax',path='/')
        return user

    @app.get('/api/auth/me')
    def me():
        return current_user.get()

    @app.post('/api/auth/register',status_code=201)
    def register(body:Registration,request:Request,response:Response):
        user=auth().register(body.username,body.password.get_secret_value(),body.role,body.invitation.get_secret_value())
        return session(user,request,response)

    @app.post('/api/auth/login')
    def login(body:Credentials,request:Request,response:Response):
        user=auth().login(body.username,body.password.get_secret_value())
        return session(user,request,response)

    @app.post('/api/auth/logout')
    def logout(request:Request,response:Response):
        auth().logout(request.cookies.get(COOKIE_NAME))
        response.delete_cookie(COOKIE_NAME,path='/')
        return {'ok':True}

    @app.put('/api/auth/model-key')
    def save_key(body:ModelKey):
        return auth().set_key(current_user.get()['id'],body.api_key.get_secret_value())

    @app.delete('/api/auth/model-key')
    def delete_key():
        return auth().set_key(current_user.get()['id'],None)

    @app.post('/api/auth/model-key/test')
    async def test_key():
        key=auth().api_key(current_user.get()['id'])
        # The fixed provider endpoint only checks access, without generating text.
        try:
            async with httpx.AsyncClient(follow_redirects=False) as client:
                result=await client.get('https://api.deepseek.com/models',headers={'Authorization':'Bearer '+key},timeout=12)
            if result.status_code in (401,403):
                raise HTTPException(422,'API Key验证失败，请检查后重新保存')
            if not result.is_success:
                raise HTTPException(502,'DeepSeek暂时无法完成验证，请稍后重试')
        except httpx.HTTPError:
            raise HTTPException(502,'连接DeepSeek超时，请稍后重试')
        return {'ok':True,'message':'API Key验证通过'}

    @app.get('/api/admin/users')
    def users(search:str=Query(default='',max_length=32),page:int=Query(default=1,ge=1,le=100000)):
        return auth().admin_overview(search,page)

    @app.get('/api/admin/users/{user_id}/reviews')
    def reviews(user_id:str,page:int=Query(default=1,ge=1,le=100000)):
        return auth().admin_reviews(user_id,page)
