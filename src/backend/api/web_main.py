"""
网页 Agent API 入口，挂载对话、历史和静态页面。
    _frontend - 提供本机 Agent 测试页面。
    _health - 检查 API 是否可达并返回基础配置。
    _sandbox_health - 检查配置的 OpenSandbox 管理服务。
    _download - 下载当前用户和会话已导出的文件。
"""

import sys
from asyncio import timeout
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from opensandbox.config import ConnectionConfig
from opensandbox.exceptions import SandboxException
from opensandbox.manager import SandboxManager
from opensandbox.models.sandboxes import SandboxFilter

# 直接运行此文件时，让 Python 能找到项目根目录下的 src 包。
if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from src.agent.backends.user_backend import user_key
from src.backend.service.agent_loader import AgentLoader
from src.backend.api.routers import chat, history


# 添加APP生命周期
@asynccontextmanager
async def _lifespan(app):
    """退出服务器时关闭沙箱和数据库连接。"""
    yield
    app.state.loader.close()
app = FastAPI(
    title="ERP Procurement Agent",
    lifespan=_lifespan
)

# 创建Agent管理器
app.state.loader = AgentLoader()

# 挂载
frontend_root = Path(__file__).resolve().parents[2] / "frontend"
app.mount("/frontend", StaticFiles(directory=frontend_root), name="frontend")

#跨域
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:8001", "http://127.0.0.1:8001", "http://localhost:8003", "http://127.0.0.1:8003"],
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["Content-Type"]
)

# 注册分组路由chat和history
app.include_router(chat.router)
app.include_router(history.router)


@app.get("/", include_in_schema=False)
async def _frontend():
    """提供与 API 同源的本机 Agent 测试页面。"""
    return FileResponse(frontend_root / "index.html", headers={"Cache-Control": "no-cache"})


@app.get("/health")
async def _health(request: Request):
    """提供无需加载模型的健康检查。"""
    loader = request.app.state.loader
    return {
        "status": "ok",
        "model": loader.config.model,
        "backend": "opensandbox",
        "storage": "mongodb" if loader.client is not None else "memory"
    }


@app.get("/health/sandbox")
async def _sandbox_health(request: Request) -> dict[str, str]:
    """在三秒内用只读查询检查配置的 OpenSandbox 管理服务。"""
    config = request.app.state.loader.config
    connection = ConnectionConfig(domain=config.sandbox_domain, api_key=config.sandbox_api_key or None)
    try:
        async with timeout(3):
            async with await SandboxManager.create(connection_config=connection) as manager:
                await manager.list_sandbox_infos(SandboxFilter(page_size=1))
    except (SandboxException, TimeoutError):
        return {"status": "unavailable"}
    return {"status": "ok"}


@app.get("/api/files/{filename}", tags=["文件"])
async def _download(filename: str, user_id: str, thread_id: str, request: Request):
    """下载当前用户和会话已经导出的报告、图表或数据。"""
    directory = request.app.state.loader.config.download_root / user_key(user_id) / user_key(thread_id)
    path = (directory / filename).resolve()
    if path.parent != directory.resolve() or not path.is_file():
        raise HTTPException(404, "文件不存在")
    return FileResponse(path, filename=filename)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8003)

