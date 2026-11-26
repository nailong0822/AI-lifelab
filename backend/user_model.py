"""Resolve model credentials from the persisted job owner on every call."""
from fastapi import HTTPException
from .auth import model_owner
from .providers import DeepSeekModel, ProviderError


class UserModelRouter:
    def __init__(self,auth,override=None):
        self.auth=auth
        self.override=override

    def resolve(self):
        owner=model_owner.get()
        if not owner:
            raise ProviderError('本次任务缺少所属用户，已停止模型调用')
        try:
            key=self.auth.api_key(owner)
        except HTTPException as error:
            raise ProviderError(str(error.detail)) from error
        return self.override if self.override is not None else DeepSeekModel(api_key=key)

    async def generate(self,*args,**kwargs):
        return await self.resolve().generate(*args,**kwargs)

    async def choose_tool(self,*args,**kwargs):
        return await self.resolve().choose_tool(*args,**kwargs)
