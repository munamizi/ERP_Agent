"""将沙箱内的文件下载到本地。"""

import asyncio
from pathlib import PurePosixPath
from urllib.parse import urlencode

from langchain.tools import ToolRuntime
from langchain_core.tools import tool

from src.agent.backends.user_backend import get_context, get_user_backend, user_key
from src.agent.config import settings
from src.backend.api.schema import UserContext


@tool(description=(
    "仅在用户要求文件或已有明确文件交付要求时导出工作区文件；普通询价和最低价比较直接回复，不为调用本工具而先生成文件。"
    "可读取同一用户之前会话生成的文件。path 例如 /analysis/report.md。"
    "返回文件名、大小和下载链接；文件不存在时返回错误。"
))
async def download_sandbox_file(path: str, runtime: ToolRuntime[UserContext]) -> dict:
    """
    将用户工作区的文件导出到当前会话的下载目录。

    Args:
        path - 后端文件路径，例如 /analysis/report.md
        runtime - 框架注入的用户和会话上下文
    Returns:
        文件名、大小和下载 URL；文件不存在时返回错误。
    """
    context = get_context(runtime)
    backend = get_user_backend(context.user_id)
    result = (await backend.adownload_files([path]))[0]
    if result.error:
        return {"error": result.error, "path": path}
    directory = settings.download_root / user_key(context.user_id) / user_key(context.thread_id)
    await asyncio.to_thread(directory.mkdir, parents=True, exist_ok=True)
    name = PurePosixPath(path).name
    await asyncio.to_thread((directory / name).write_bytes, result.content)
    query = urlencode({"user_id": context.user_id, "thread_id": context.thread_id})
    return {
        "file_name": name,
        "size": len(result.content),
        "download_url": f"{settings.api_url}/api/files/{name}?{query}",
    }
