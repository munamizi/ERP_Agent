"""
langgraph studio 测试入口
    供 studio UI测试使用；
    自键后端服务忽略当前模块，Agent创建看 agent_loader.py
"""

from anyio.from_thread import start_blocking_portal
from deepagents import create_deep_agent
from deepagents.middleware.summarization import create_summarization_tool_middleware
from langchain.agents.middleware import ModelCallLimitMiddleware, ToolCallLimitMiddleware, TodoListMiddleware
from langchain_openai import ChatOpenAI

from src.agent.backends.user_backend import get_user_backend
from src.agent.config import settings
from src.agent.memory.prompts import SYSTEM_PROMPT
from src.agent.middlewares.context_injection import ContextInjectionMiddleware
from src.agent.middlewares.skills_sync import SkillsSyncMiddleware
from src.agent.middlewares.user_skills_restore import UserSkillsRestoreMiddleware
from src.backend.api.schema import UserContext
from src.agent.subagents.loader import load_subagents
from src.agent.tools.assign_skill import assign_skill
from src.agent.tools.chart_generator import MCP_CHART_TOOLS, generate_visualization
from src.agent.tools.download_sandbox_file import download_sandbox_file
from src.agent.tools.hitl_tools import request_order_info
from src.agent.tools.mcp.mcp_client import load_mcp_tools
from src.agent.tools.web_search import web_search


model = ChatOpenAI(
    model=settings.model,
    api_key=lambda: settings.api_key,
    base_url=settings.base_url,
    temperature=0,
    streaming=True,
    timeout=60,
    max_retries=1,
)

# 工具列表
with start_blocking_portal() as portal:
    mcp_tools = portal.call(load_mcp_tools, settings)
MCP_CHART_TOOLS.update({item.name: item for item in mcp_tools})
tools = [
    *mcp_tools, generate_visualization,
    request_order_info, web_search,
]
main_tools = [assign_skill, download_sandbox_file, web_search]


# 文件后端。langgraph dev使用固定用户键："local-user"拿取复合后端；如果使用自定义API，自己处理用户id
backend = get_user_backend("local-user")

# 子代理加载
subagents = load_subagents(tools, model, backend, settings)

# 中间件列表
middleware = [
    ContextInjectionMiddleware(),
    SkillsSyncMiddleware(backend, settings),
    UserSkillsRestoreMiddleware(backend),
    create_summarization_tool_middleware(model=model, backend=backend),
    TodoListMiddleware(),
    ModelCallLimitMiddleware(run_limit=settings.model_call_limit, exit_behavior="end"),
    ToolCallLimitMiddleware(run_limit=settings.tool_call_limit, exit_behavior="end"),
]

#
deep_agent = create_deep_agent(
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
)
