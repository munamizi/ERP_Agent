"""连接 MCP 服务并读取工具，为采购写入附加幂等键。"""

from langchain_mcp_adapters.client import MultiServerMCPClient

from src.agent.config import AgentSettings


async def _inject_request_key(request, handler):
    """使用 LangGraph 工具调用编号作为写入键，避免同次调用重试重复下单。"""
    if request.name in ("order_create", "order_update") and request.runtime is not None:
        request = request.override(args={**request.args, "request_key": request.runtime.tool_call_id})
    return await handler(request)


async def load_mcp_tools(config: AgentSettings) -> list:
    """
    从 ERP 和可选 MCP 服务读取工具。

    Args:
        config - ERP MCP 地址和额外服务的连接配置
    Returns:
        可直接交给 DeepAgents 的工具列表。
    """
    connections = {
        "erp": {
            "url": config.mcp_url,
            "transport": "streamable_http"
        },
        **(config.extra_mcp_servers or {})
    }
    client = MultiServerMCPClient(connections, tool_interceptors=[_inject_request_key])
    return await client.get_tools()
