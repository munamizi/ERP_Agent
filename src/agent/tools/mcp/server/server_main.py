"""ERP-Agent的 MCP 服务器。"""

from mcp.server.fastmcp import FastMCP

from src.agent.tools.mcp.server.tools.inventory_tools import register_inventory_tools
from src.agent.tools.mcp.server.tools.procurement_tools import register_procurement_tools
from src.agent.tools.mcp.server.tools.sales_tools import register_sales_tools


mcp = FastMCP("ERP Procurement", host="127.0.0.1", port=8000, stateless_http=True, json_response=True)

# 按 ERP 接口文档中的业务域顺序注册；生产与交付、基础财务尚未封装工具。
register_sales_tools(mcp)
register_inventory_tools(mcp)
register_procurement_tools(mcp)

if __name__ == "__main__":
    mcp.run(transport="streamable-http")
