"""
采购业务域工具：
    supplier_query - GET /suppliers/search
    order_search_details - GET /orders/search/details
    order_get - GET /orders/{id}
    order_create - POST /orders/create
    order_update - PUT /orders/update/{order_id}
"""

from mcp.server.fastmcp import FastMCP
from src.agent.tools.mcp.server.tools._erp import _request


def register_procurement_tools(mcp: FastMCP) -> None:
    """
    注册采购管理业务域的供应商查询和采购单操作工具。

    Args:
        mcp - MCP服务实例
    Returns:
        None - 在指定服务注册供应商查询及采购单查询、创建和修改工具。
    """


    @mcp.tool(description="按供应商名称或供货物料关键词查询供应商。qualified=true 只查通过 ERP 准入的供应商；返回供货信息及分页。")
    async def supplier_query(keyword: str = "", qualified: bool | None = None, page: int = 1, page_size: int = 50) -> dict:
        """
        查询供应商及其供货物料，可筛选是否已通过准入。

        Args:
            keyword - 供应商名称或供货物料关键词
            qualified - 是否合格，省略时查询全部供应商
            page - 页码
            page_size - 每页条数，最多 100
        Returns:
            含供应商、供货物料和分页信息的 ERP 查询结果。
        """
        return await _request(
            "GET",
            "/suppliers/search",
            params=locals()
        )


    @mcp.tool(description=(
        "创建采购草稿，不自动确认或收货。supplier_id、expected_date(YYYY-MM-DD)、lines 必填；"
        "每行含 part_id、quantity、unit_price，金额用元字符串。可关联 sales_order_id，一单只属于一个供应商。"
        "freight 为整单运费；request_key 由 Agent 客户端注入。返回实际单号、状态、金额和明细，失败返回 ERP error。"
    ))
    async def order_create(
        supplier_id: int,
        expected_date: str,
        lines: list[dict],
        sales_order_id: int | None = None,
        freight: str = "0.00",
        notes: str = "",
        request_key: str = "",
    ) -> dict:
        """
        创建采购草稿；本工具不会自动确认采购或登记收货。

        Args:
            supplier_id - ERP 中已准入的供应商编号
            expected_date - 预计到货日期，YYYY-MM-DD
            lines - 明细列表，每行含 part_id、quantity、unit_price；金额为元字符串
            sales_order_id - 关联的已确认销售单，省略时为备库存采购
            freight - 整单运费，元字符串
            notes - 采购备注
            request_key - 同次操作的幂等键，Agent 调用时由 MCP 客户端注入
        Returns:
            采购单编号、状态、总额和明细；业务失败时返回 ERP 错误。
        """
        body = {"supplier_id": supplier_id, "expected_date": expected_date, "lines": lines, "freight": freight, "notes": notes}
        if sales_order_id is not None:
            body["sales_order_id"] = sales_order_id
        return await _request(
            "POST",
            "/orders/create",
            body=body,
            request_key=request_key
        )


    @mcp.tool(description=(
        "按 order_id 修改采购草稿，或将 status 设为 confirmed/cancelled 以确认/取消。"
        "只传实际变更字段；lines 是替换后的完整明细，仅草稿可改。不能通过修改状态登记收货。"
        "request_key 由 Agent 客户端注入；返回更新后的单据或 ERP error。"
    ))
    async def order_update(
        order_id: int,
        status: str | None = None, 
        expected_date: str | None = None,
        lines: list[dict] | None = None,
        freight: str | None = None,
        notes: str | None = None,
        request_key: str = "",
    ) -> dict:
        """
        修改采购草稿，或按明确指令确认、取消采购单。

        Args:
            order_id - 采购单内部编号
            status - confirmed 或 cancelled，省略时只修改草稿字段
            expected_date - 新的预计到货日期
            lines - 新的完整明细列表，仅草稿可修改
            freight - 新的整单运费，元字符串
            notes - 新备注
            request_key - 同次操作的幂等键
        Returns:
            更新后的采购单，或 ERP 返回的业务错误。
        """
        body = {"status": status, "expected_date": expected_date, "lines": lines, "freight": freight, "notes": notes}
        return await _request(
            "PUT",
            f"/orders/update/{order_id}",
            body={k: v for k, v in body.items() if v is not None},
            request_key=request_key
        )


    @mcp.tool(description=(
        "分页搜索采购单及采购明细，可按关键词、供应商、物料、销售单、状态、创建日期筛选。"
        "结果按采购单分组，明细在 lines 中；用于采购历史分析或定位待操作单据。草稿、取消单不能当成交历史。"
    ))
    async def order_search_details(
        keyword: str = "",
        supplier_id: int | None = None,
        part_id: int | None = None,
        sales_order_id: int | None = None,
        status: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        page: int = 1,
        page_size: int = 50,
    ) -> dict:
        """
        搜索采购历史和当前单据，读取实际成交价与收货状态。

        Args:
            keyword - 供应商、物料或采购单关键词
            supplier_id - 供应商编号
            part_id - 物料编号
            sales_order_id - 关联销售单编号
            status - 采购单状态
            start_date - 创建日期起点，YYYY-MM-DD
            end_date - 创建日期终点，YYYY-MM-DD
            page - 页码
            page_size - 每页条数，最多 100
        Returns:
            包含供应商、物料、价格和收货明细的分页结果。
        """
        return await _request(
            "GET",
            "/orders/search/details",
            params=locals()
        )


    @mcp.tool(description="按采购单内部 order_id 读取完整明细与状态，用于查看目标单据及核对创建、修改结果；失败返回 ERP error。")
    async def order_get(order_id: int) -> dict:
        """
        读取一张采购单，核对下单或修改后的实际状态。

        Args:
            order_id - 采购单内部编号
        Returns:
            采购单完整明细和当前状态。
        """
        return await _request(
            "GET",
            f"/orders/{order_id}"
        )