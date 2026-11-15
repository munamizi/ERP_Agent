"""
库存业务域工具：
    part_query - GET /parts
    part_search、
    part_by_supplier、
    inventory_warning - GET /inventory/warning
"""

from mcp.server.fastmcp import FastMCP
from src.agent.tools.mcp.server.tools._erp import _request


def register_inventory_tools(mcp: FastMCP) -> None:
    """
    注册物料库存业务域的物料查询与库存预警工具。
    """

    @mcp.tool(description="分页查询物料规格、库存、合同价、最近成交价及 suppliers 供货关系。可按关键词、分类、供应商筛选；网页报价通过 Agent 的网址映射查找。")
    async def part_query(keyword: str = "", category: str | None = None, supplier_id: int | None = None, page: int = 1, page_size: int = 50) -> dict:
        """
        查询物料规格、库存、合同价、最近成交价和供货关系。

        Args:
            keyword - 名称、型号、编码或规格关键词
            category - 物料分类
            supplier_id - 按供应商筛选
            page - 页码
            page_size - 每页条数，最多 100
        Returns:
            物料及供货关系的分页查询结果。
        """
        return await _request("GET", "/parts", params=locals())


    @mcp.tool(description="按必填 keyword 搜索物料名称、型号、编码、规格和别名，返回分页物料及供货信息。")
    async def part_search(keyword: str, page: int = 1, page_size: int = 50) -> dict:
        """
        按名称、型号、编码、规格和别名搜索物料。

        Args:
            keyword - 搜索关键词
            page - 页码
            page_size - 每页条数，最多 100
        Returns:
            匹配物料的规格、库存及供应商信息。
        """
        return await _request("GET", "/parts", params=locals())


    @mcp.tool(description="查询指定 supplier_id 能供应的物料及供货价格，支持关键词和分页。")
    async def part_by_supplier(supplier_id: int, keyword: str = "", page: int = 1, page_size: int = 50) -> dict:
        """
        查询指定供应商能够供应的物料。

        Args:
            supplier_id - 供应商编号
            keyword - 物料关键词
            page - 页码
            page_size - 每页条数，最多 100
        Returns:
            该供应商的物料和供货价格分页结果。
        """
        return await _request("GET", "/parts", params=locals())


    @mcp.tool(description="查询销售缺料、安全库存和采购晚到预警。type 可选 shortage、safety_stock、late_inbound；支持分页。")
    async def inventory_warning(type: str | None = None, page: int = 1, page_size: int = 50) -> dict:
        """
        查询销售缺料、安全库存不足或采购晚到预警。

        Args:
            type - shortage、safety_stock、late_inbound；省略时查询全部
            page - 页码
            page_size - 每页条数，最多 100
        Returns:
            含关联单据和物料编号的预警列表。
        """
        return await _request("GET", "/inventory/warning", params=locals())
