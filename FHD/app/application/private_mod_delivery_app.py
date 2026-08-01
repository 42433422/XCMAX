"""私有交付用例边界，供 FastAPI 路由调用。"""

from app.services.private_mod_delivery import *  # noqa: F403


async def custom_delivery_remote_json(*args, **kwargs):
    from app.services import private_mod_delivery as service

    return await service.custom_delivery_remote_json(*args, **kwargs)
