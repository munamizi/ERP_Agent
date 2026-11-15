"""
销售订单与BOM业务域工具：
    sales_order_query - GET /sales-orders
    sales_order_details - GET /sales-orders/{id}
"""

from mcp.server.fastmcp import FastMCP
from src.agent.tools.mcp.server.tools._erp import _request


def register_sales_tools(mcp: FastMCP) -> None:
    """
    注册销售订单与BOM业务域中已封装的销售单查询工具。

    Args:
        mcp - 接收销售业务工具的 MCP 服务实例
    Returns:
        None - 在指定服务注册销售单列表和详情查询工具。
    """

    @mcp.tool(description="按客户或销售单关键词分页查询销售订单，定位本次采购需求；不是采购单查询。")
    async def sales_order_query(keyword: str = "", page: int = 1, page_size: int = 50) -> dict:
        """
        查询用户自己的销售订单，定位本次采购要服务的业务需求。

        Args:
            keyword - 客户名称或销售单关键词
            page - 页码
            page_size - 每页条数，最多 100
        Returns:
            销售单、客户、交期和当前物料需求的分页结果。
        """
        return await _request("GET", "/sales-orders", params=locals())


    @mcp.tool(description="读取指定销售单。已确认且未开工时含 mrp：物料需求、实物缺口、按时在途和 suggested_purchase_qty 采购建议。")
    async def sales_order_details(sales_order_id: int) -> dict:
        """
        查看一张销售单及其实际缺口、按时在途和采购建议。

        Args:
            sales_order_id - 销售单内部编号
        Returns:
            销售单明细；已确认且未开工时包含 mrp 物料计划。
        """
        return await _request("GET", f"/sales-orders/{sales_order_id}")
