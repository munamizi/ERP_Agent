import asyncio

from langchain.agents.middleware import AgentMiddleware

from src.agent.config import PROJECT_ROOT, settings
from src.agent.tools.chart_generator import _remote_chart_reference


class SkillsSyncMiddleware(AgentMiddleware):
    """ 将本机 AGENTS.md 和技能目录同步至沙箱容器 """

    def __init__(self, backend, config=settings):
        """保存用户后端、配置和上次成功同步的文件内容。"""
        self.backend = backend
        self.config = config
        self.synced_files = {}

    def _read_files(self):
        """ 读取本地 AGENTS.md 和技能文件 """
        rules = (PROJECT_ROOT / "src/agent/memory/AGENTS.md").read_text(encoding="utf-8")
        rules += "\n当前默认后端为远端 OpenSandbox，文件操作和 execute 均在 Linux 沙箱中完成。\n"
        if self.config.sandbox_supplier_url:
            rules += f"沙箱抓取模拟报价页时 --base-url 使用 {self.config.sandbox_supplier_url}，保留映射中的原网址作为来源。\n"
        files = [("/AGENTS.md", rules.encode())]
        for path in self.config.skills_root.rglob("*"):
            if not path.is_file() or "__pycache__" in path.parts:
                continue
            target = "/skills/" + path.relative_to(self.config.skills_root).as_posix()
            content = path.read_bytes()
            if target == "/skills/procurement/chart_params.md":
                content += _remote_chart_reference().encode()
            files.append((target, content))
        return files

    async def abefore_agent(self, state, runtime):
        """
        将项目准则和变化的本地技能上传到用户工作区。

        内容：
            1. 在线程中读取 AGENTS.md 和本地技能文件。
            2. 与上次成功同步的内容比较，筛选出新增或修改的文件。
            3. 上传变化文件，成功后保存本次内容，供下次比较。

        Args:
            state - 当前 Agent 状态，本钩子不修改消息
            runtime - 当前用户的运行上下文
        Returns:
            更新工作区文件和同步记录。
        """
        files = await asyncio.to_thread(self._read_files)

        changed = []
        for path, content in files:
            if self.synced_files.get(path) != content:
                changed.append((path, content))
        if not changed:
            return

        results = await self.backend.aupload_files(changed)
        for (path, content), result in zip(changed, results):
            if result.error:
                raise OSError(result.error)
            self.synced_files[path] = content