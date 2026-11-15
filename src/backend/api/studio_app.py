"""LangGraph Studio 服务入口：跨域配置、本地网络访问与资源清理。"""

import asyncio
from contextlib import asynccontextmanager

from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware

from src.agent.backends.user_backend import close_backends


@asynccontextmanager
async def _lifespan():
    """Studio 退出时关闭沙箱容器，用户工作目录由 Linux 存储卷保留。"""
    try:
        yield
    finally:
        await asyncio.to_thread(close_backends)


# 使用 LangGraph 的自定义 HTTP 应用入口，让 Studio 的本地网络预检由外层处理。
app = Starlette(
    lifespan=_lifespan,
    middleware=[
        Middleware(
            CORSMiddleware,
            allow_origins=["https://smith.langchain.com"],
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
            allow_private_network=True,
            expose_headers=["x-pagination-total", "x-pagination-next", "content-location"],
        ),
    ],
)
