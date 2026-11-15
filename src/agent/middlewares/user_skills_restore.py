from langchain.agents.middleware import AgentMiddleware

from src.agent.backends.user_backend import get_context, user_key


class UserSkillsRestoreMiddleware(AgentMiddleware):
    """ 恢复新增或变化的用户技能到沙箱容器（用户技能在用户独有store）"""

    def __init__(self, backend):
        """保存用户后端和已恢复的技能版本。"""
        self.backend = backend
        self.restored_versions = {}

    async def abefore_agent(self, state, runtime):
        """
        从用户 Store 读取变化技能，复制到工作区。

        步骤：
            1. 查询用户技能，按版本筛选变化文件。
            2. 从 Store 下载变化文件并复制到工作区。
            3. 复制成功后记录已恢复版本。

        Args:
            state - 当前 Agent 状态，本钩子不修改消息
            runtime - 提供当前用户及长期 Store 的上下文
        Returns:
            None - 将变化技能写入工作区，成功后记录版本。
        """
        context = get_context(runtime)
        namespace = ("user_skills", user_key(context.user_id))
        items = await runtime.store.asearch(namespace, limit=1000)
        changed = [item for item in items if self.restored_versions.get(item.key) != item.updated_at]
        if not changed:
            return

        persisted = self.backend.routes["/persisted-skills/"]
        files = await persisted.adownload_files([item.key for item in changed])
        copies = []
        for file in files:
            if file.error:
                raise OSError(f"恢复技能失败：{file.path}，{file.error}")
            copies.append((file.path, file.content))
        for result in await self.backend.aupload_files(copies):
            if result.error:
                raise OSError(result.error)
        for item in changed:
            self.restored_versions[item.key] = item.updated_at