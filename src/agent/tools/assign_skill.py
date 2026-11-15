"""技能分配：复制技能、持久化到 StoreBackend 并清理临时资源。"""

from pathlib import PurePosixPath
from typing import Literal

from langchain.tools import ToolRuntime
from langchain_core.tools import tool

from src.agent.backends.user_backend import get_context, get_user_backend
from src.backend.api.schema import UserContext

AGENT_SCOPES = {
    "main": "main",
    "procurement-analyst": "procurement",
    "procurement-order": "order",
}


@tool(description=(
    "将已有技能目录分配给指定 Agent 并跨会话保存。source_path 必须包含 SKILL.md 及所需辅助文件；"
    "agent_name 为 main、procurement-analyst 或 procurement-order，分别分配到独立技能域；"
    "remove_source=true 时会删除临时源目录，默认保留。"
    "返回技能名称、目标路径和复制文件数量。"
))
async def assign_skill(
    source_path: str, agent_name: Literal["main", "procurement-analyst", "procurement-order"],
    runtime: ToolRuntime[UserContext], remove_source: bool = False,
) -> dict:
    """
    将完整技能目录分配给指定 Agent 的技能域，并跨会话保存。

    步骤：
        1. 读取源目录中的 SKILL.md 和辅助资源。
        2. 先复制到目标技能目录，再保存到当前用户的 StoreBackend。
        3. 需要时删除源目录，避免重复技能。

    Args:
        source_path - 工作目录中的技能文件夹，例如 /draft-skills/my-analysis
        agent_name - main、procurement-analyst 或 procurement-order，决定目标技能域
        runtime - 框架注入的用户和会话上下文
        remove_source - 是否在分配后删除源目录，默认保留
    Returns:
        技能名称、目标路径和复制文件数量。
    """
    context = get_context(runtime)
    backend = get_user_backend(context.user_id)
    source = source_path.rstrip("/")
    name = PurePosixPath(source).name
    scope = AGENT_SCOPES[agent_name]
    target = f"/skills/{scope}/{name}"
    if target == source or target.startswith(source + "/"):
        raise ValueError("请从临时技能目录分配，目标目录不能位于源目录内")
    matched = await backend.aglob(source + "/**/*")
    if matched.error:
        raise OSError(matched.error)
    files = [item["path"] for item in matched.matches if not item.get("is_dir")]
    if source + "/SKILL.md" not in files:
        raise ValueError("技能目录需要包含 SKILL.md")

    results = await backend.adownload_files(files)
    copies = []
    for result in results:
        if result.error:
            raise OSError(f"读取技能失败：{result.path}，{result.error}")
        target_path = target + result.path[len(source):]
        copies.append((target_path, result.content))

    # 工作目录和持久化存储都写入成功后，才允许清理源目录。
    persisted = backend.routes["/persisted-skills/"]
    for destination in (backend, persisted):
        uploads = await destination.aupload_files(copies)
        for result in uploads:
            if result.error:
                raise OSError(f"保存技能失败：{result.path}，{result.error}")
    if remove_source:
        deleted = await backend.adelete(source)
        if deleted.error:
            raise OSError(deleted.error)
    return {"name": name, "agent_name": agent_name, "path": target, "files": len(copies)}
