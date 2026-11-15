import asyncio
from deepagents import create_deep_agent
from deepagents.middleware.summarization import create_summarization_tool_middleware
from langchain.agents.middleware import ModelCallLimitMiddleware, TodoListMiddleware, ToolCallLimitMiddleware
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.store.memory import InMemoryStore
from src.agent.backends.user_backend import close_backends, get_user_backend, user_key
from src.agent.config import settings
from src.agent.memory.prompts import SYSTEM_PROMPT, TODO_SYSTEM_PROMPT, TODO_TOOL_DESCRIPTION
from src.agent.middlewares.context_injection import ContextInjectionMiddleware
from src.agent.middlewares.skills_sync import SkillsSyncMiddleware
from src.agent.middlewares.user_skills_restore import UserSkillsRestoreMiddleware
from src.backend.api.schema import UserContext
from src.backend.repository.session_repo import SessionRepository
from src.agent.subagents.loader import load_subagents
from langgraph.checkpoint.mongodb import MongoDBSaver
from langgraph.store.mongodb import MongoDBStore
from pymongo import MongoClient
from src.agent.main_agent import main_tools, model, tools

class AgentLoader:
    """
    Agent管理器：
        1.get_agent根据用户id拿取对应Agent
        2.save_session保存会话列表信息
        3.close释放沙箱和 MongoDB连接

    """
    def __init__(self, config=settings):
        """初始化存储、用户 Agent 缓存和会话锁。"""
        self.config = config
        self.client = None

        if config.mongodb_uri:
            self.client = MongoClient(config.mongodb_uri, serverSelectionTimeoutMS=5000, tz_aware=True)
            self.checkpointer = MongoDBSaver(self.client, db_name=config.mongodb_database)
            database = self.client[config.mongodb_database]
            self.store = MongoDBStore(collection=database["agent_store"])
            self.session_repo = SessionRepository(database["chat_sessions"])
        else:
            self.checkpointer = InMemorySaver()
            self.store = InMemoryStore()
            self.session_repo = SessionRepository()

        self.user_agents = {}

        self.load_lock = asyncio.Lock()

        self.thread_locks = {}


    async def get_agent(self, context):
        """
        获取当前用户的专属Agent

        Args:
            context - 当前用户和会话信息，使用 user_id 选择
        Returns:
            当前用户可复用的 Agent；不同会话使用同一图和文件工作区。
        """
        async with self.load_lock:
            # 当前用户尚无 Agent 时创建，后续请求复用。
            if context.user_id not in self.user_agents:
                if not self.config.api_key:
                    raise ValueError("请在 src/.env 中填写 DEEPSEEK_API_KEY")
                # 文件后端、子代理、中间件
                backend = await asyncio.to_thread(get_user_backend, context.user_id, self.config)
                subagents = load_subagents(tools, model, backend, self.config)
                middleware = [
                    ContextInjectionMiddleware(),
                    SkillsSyncMiddleware(backend, self.config),
                    UserSkillsRestoreMiddleware(backend),
                    create_summarization_tool_middleware(model=model, backend=backend),
                    TodoListMiddleware(
                        system_prompt=TODO_SYSTEM_PROMPT,
                        tool_description=TODO_TOOL_DESCRIPTION,
                    ),
                    ModelCallLimitMiddleware(run_limit=self.config.model_call_limit, exit_behavior="end"),
                    ToolCallLimitMiddleware(run_limit=self.config.tool_call_limit, exit_behavior="end"),
                ]
                # 为用户创建Agent
                self.user_agents[context.user_id] = create_deep_agent(
                    model=model,
                    system_prompt=SYSTEM_PROMPT,
                    backend=backend,
                    tools=main_tools,
                    middleware=middleware,
                    subagents=subagents,
                    skills=["/skills/main/"],
                    memory=["/AGENTS.md"],
                    context_schema=UserContext,
                    name="procurement-main",
                    store=self.store,
                    checkpointer=self.checkpointer,
                )
            # 返回用户Agent
            return self.user_agents[context.user_id]


    def thread_config(self, user_id: str, thread_id: str) -> dict:
        """ 返回当前用户对应的 thread_id"""
        return {"configurable": {"thread_id": f"{user_key(user_id)}:{thread_id}"}}


    def thread_lock(self, user_id: str, thread_id: str):
        """ 获取会话锁，避免同一会话同时写入两轮对话。"""
        key = (user_id, thread_id)
        return self.thread_locks.setdefault(key, asyncio.Lock())


    async def save_session(
            self,
            user_id: str,
            thread_id: str,
            title: str,
            status: str,
            messages=None,
            interrupts=None
    ):
        """
        将会话状态和展示消息保存到独立的会话 Repository。

        Args:
            user_id - 用户id
            thread_id - 会话id
            title - 标题（首条消息截取前40字）
            status - running、completed、interrupted 或 error
            messages - 可选的主会话消息，传入时保存为展示历史
            interrupts - 随 messages 保存的待处理中断，省略时保存空列表
        Returns:
            None - 更新会话记录，保留首次标题；不写入 Agent Store。
        """
        display = None
        if messages is not None:
            display = [
                {
                    "id": m.id,
                    "role": m.type,
                    "content": m.content,
                    "tool_calls": getattr(m, "tool_calls", []),
                    "tool_call_id": getattr(m, "tool_call_id", None)
                } for m in messages
            ]
        await self.session_repo.save(user_id, thread_id, title, status, display, interrupts)


    def close(self) -> None:
        """ 释放沙箱和 MongoDB 连接。"""
        close_backends()
        self.user_agents.clear()
        if self.client:
            self.client.close()