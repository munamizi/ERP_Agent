"""ERP HTTP 服务及基础操作页面入口。"""

import hmac
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, Header, Query, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from fastapi.staticfiles import StaticFiles
from sqlalchemy.exc import IntegrityError
from starlette.exceptions import HTTPException

from erp_system.config import Settings
from erp_system.database import Database
from erp_system.schemas import CashCreate, ErrorResponse, MovementFilter, OrderFilter, Page, PageFilter, PartFilter, PartOut, ProductionCreate, PurchaseCreate, PurchaseOut, PurchaseUpdate, QuantityAction, ReceiptCreate, SalesCreate, SupplierFilter, SupplierOut, WarningFilter
from erp_system.service import BusinessError, ERPService

OPENAPI_TAGS = [
    {
        "name": "销售订单与BOM",
        "description": "客户、产品配方（BOM）、销售订单和物料需求计划（MRP）。MCP 工具：`sales_order_query`、`sales_order_details`。",
    },
    {
        "name": "物料库存",
        "description": "物料规格、供货关系、原材料与成品库存、库存流水和预警。MCP 工具：`part_query`、`part_search`、`part_by_supplier`、`inventory_warning`。",
    },
    {
        "name": "采购管理",
        "description": "供应商、采购草稿、确认、取消和收货。`/orders` 均为采购单。MCP 工具：`supplier_query`、`order_search_details`、`order_get`、`order_create`、`order_update`；采购收货尚未封装为 MCP 工具。",
    },
    {
        "name": "生产与交付",
        "description": "生产工单、领料开工、完工入库和销售发货。当前没有对应的 MCP 工具。",
    },
    {
        "name": "基础财务",
        "description": "应收应付、成本毛利、会计凭证及收付款。当前没有对应的 MCP 工具。",
    },
    {
        "name": "系统辅助",
        "description": "健康检查、当前权限和审计日志；不属于上述五个业务域，当前没有对应的 MCP 工具。",
    },
]


def create_app(settings: Settings | None = None) -> FastAPI:
    """
    创建 ERP 服务，注册业务接口、权限校验和静态操作页面。

    内容：
        生命周期内迁移并初始化演示数据库。
        注册销售、库存、采购、生产和财务业务接口。
        按五个业务域组织接口文档，标注已接入的 MCP 工具名称。
        将请求验证与业务异常转换为统一错误响应。

    Args:
        settings - 服务配置，省略时读取环境变量及本地演示默认值
    Returns:
        可由 Uvicorn 启动或由测试客户端调用的 FastAPI 应用。
    """
    settings = settings or Settings()
    if len({settings.read_token, settings.buyer_token, settings.admin_token}) != 3 or not all((settings.read_token, settings.buyer_token, settings.admin_token)):
        raise ValueError("三个业务令牌必须非空且互不相同")
    service = ERPService(Database(settings.database_path))

    @asynccontextmanager
    async def _lifespan(app: FastAPI):
        """启动时准备业务数据，退出时释放连接池。"""
        service.initialize()
        try:
            yield
        finally:
            service.db.close()

    app = FastAPI(
        title="凌云电脑制造 ERP",
        version="1.0.0",
        lifespan=_lifespan,
        openapi_tags=OPENAPI_TAGS,
        responses={status: {"model": ErrorResponse} for status in (401, 403, 404, 409, 422)},
        description=(
            "接口按销售订单与BOM、物料库存、采购管理、生产与交付、基础财务分组，系统辅助接口放在最后。\n\n"
            "已封装的接口在标题中标注 `MCP: 工具名`，可直接搜索工具名对照；未标注的接口尚未开放为 MCP 工具。"
            "`/orders` 表示采购单，`/sales-orders` 表示销售单。\n\n"
            "使用 Authorize 填写 Bearer 令牌：read 可查询，buyer 可操作采购单，admin 可执行销售、收货、生产和财务写入。"
            "所有业务写入必须提交 `Idempotency-Key`；同次操作重试复用该键。金额为人民币元字符串、不含税。"
        ),
    )
    app.state.service = service
    app.add_middleware(CORSMiddleware, allow_origins=list(settings.cors_origins), allow_methods=["GET", "POST", "PUT"], allow_headers=["Authorization", "Content-Type", "Idempotency-Key"])
    bearer = HTTPBearer(auto_error=False)

    def _actor(credentials: HTTPAuthorizationCredentials | None = Depends(bearer)) -> str:
        """根据演示令牌返回角色，不存在或不匹配时拒绝访问。"""
        if credentials:
            for role, token in (("read", settings.read_token), ("buyer", settings.buyer_token), ("admin", settings.admin_token)):
                if hmac.compare_digest(credentials.credentials, token):
                    return role
        raise BusinessError("UNAUTHORIZED", "请提供有效的 Bearer API 令牌", 401)

    def _buyer(actor: str = Depends(_actor)) -> str:
        """只允许采购角色和管理员修改采购单。"""
        if actor not in ("buyer", "admin"):
            raise BusinessError("FORBIDDEN", "当前角色没有采购写入权限", 403)
        return actor

    def _admin(actor: str = Depends(_actor)) -> str:
        """只允许管理员执行收货、生产、销售及财务写入。"""
        if actor != "admin":
            raise BusinessError("FORBIDDEN", "当前操作需要管理员权限", 403)
        return actor

    def _key(key: Annotated[str, Header(alias="Idempotency-Key", min_length=1, max_length=128)]) -> str:
        """读取必填的幂等请求键，并拒绝全空白内容。"""
        if not key.strip():
            raise BusinessError("INVALID_REQUEST_KEY", "幂等请求键不能为空白", 422)
        return key

    @app.exception_handler(BusinessError)
    async def _business_error(request: Request, error: BusinessError):
        """返回可由页面和 Agent 识别的业务错误。"""
        return JSONResponse(status_code=error.status, content={"error": {"code": error.code, "message": error.message}}, headers={"WWW-Authenticate": "Bearer"} if error.status == 401 else None)

    @app.exception_handler(RequestValidationError)
    async def _validation_error(request: Request, error: RequestValidationError):
        """将输入验证失败转换为统一的错误结构。"""
        return JSONResponse(status_code=422, content={"error": {"code": "VALIDATION_ERROR", "message": "请求字段格式不正确", "details": jsonable_encoder(error.errors())}})

    @app.exception_handler(IntegrityError)
    async def _integrity_error(request: Request, error: IntegrityError):
        """将事务内数据库约束冲突转换为业务冲突响应。"""
        return JSONResponse(status_code=409, content={"error": {"code": "DATA_CONFLICT", "message": "操作违反业务数据约束，全部变化已回滚"}})

    @app.exception_handler(HTTPException)
    async def _http_error(request: Request, error: HTTPException):
        """将路由缺失等 HTTP 异常统一为错误契约。"""
        return JSONResponse(status_code=error.status_code, content={"error": {"code": "HTTP_ERROR", "message": str(error.detail)}}, headers=error.headers)

    @app.get("/health", tags=["系统辅助"], summary="检查服务与数据库状态")
    def _health():
        """返回服务状态及数据库迁移状态。"""
        with service.db.read() as conn:
            conn.exec_driver_sql("SELECT 1 FROM schema_migrations LIMIT 1")
        return {"status": "ok", "service": "erp", "version": "1.0.0"}

    @app.get("/session", tags=["系统辅助"], summary="查询当前令牌权限")
    def _session(actor: str = Depends(_actor)):
        """返回令牌角色，便于操作页面显示当前权限。"""
        return {"role": actor}

    @app.get("/suppliers/search", response_model=Page[SupplierOut], tags=["采购管理"], summary="查询供应商 · MCP: supplier_query")
    def _suppliers(filters: Annotated[SupplierFilter, Query()], actor: str = Depends(_actor)):
        """按供应商或供货零件关键词查询供应商。"""
        return service.query("suppliers", filters.model_dump(exclude_none=True))

    @app.get("/parts", response_model=Page[PartOut], tags=["物料库存"], summary="查询、搜索及按供应商筛选物料 · MCP: part_query、part_search、part_by_supplier")
    def _parts(filters: Annotated[PartFilter, Query()], actor: str = Depends(_actor)):
        """查询零件、库存和供应商供货价。"""
        return service.query("parts", filters.model_dump(exclude_none=True))

    @app.get("/orders/search/details", response_model=Page[PurchaseOut], tags=["采购管理"], summary="搜索采购单及明细 · MCP: order_search_details")
    def _orders(filters: Annotated[OrderFilter, Query()], actor: str = Depends(_actor)):
        """查询包含物料、供应商与收货信息的采购单明细。"""
        if filters.start_date and filters.end_date and filters.start_date > filters.end_date:
            raise BusinessError("INVALID_DATE_RANGE", "起始日期不能晚于结束日期", 422)
        return service.query("purchases", filters.model_dump(mode="json", exclude_none=True))

    @app.get("/orders/{id}", response_model=PurchaseOut, tags=["采购管理"], summary="读取采购单详情 · MCP: order_get")
    def _order_detail(id: int, actor: str = Depends(_actor)):
        """读取一张采购单的完整明细。"""
        return service.query("purchase", {"id": id})

    @app.post("/orders/create", response_model=PurchaseOut, status_code=201, tags=["采购管理"], summary="创建采购草稿 · MCP: order_create")
    def _order_create(body: PurchaseCreate, actor: str = Depends(_buyer), key: str = Depends(_key)):
        """创建采购草稿，并返回业务单号和明细行编号。"""
        return service.mutate("purchase_create", body.model_dump(mode="json", exclude_none=True), actor, key)

    @app.put("/orders/update/{order_id}", response_model=PurchaseOut, tags=["采购管理"], summary="修改、确认或取消采购单 · MCP: order_update")
    def _order_update(order_id: int, body: PurchaseUpdate, actor: str = Depends(_buyer), key: str = Depends(_key)):
        """修改采购草稿，或确认、取消未收货采购单。"""
        return service.mutate("purchase_update", {"id": order_id, **body.model_dump(mode="json", exclude_none=True, exclude_unset=True)}, actor, key)

    @app.post("/orders/{id}/receipts", tags=["采购管理"], summary="登记采购收货与入库")
    def _receipt(id: int, body: ReceiptCreate, actor: str = Depends(_admin), key: str = Depends(_key)):
        """收货并同步库存、物料预留及采购应付。"""
        return service.mutate("receive", {"id": id, **body.model_dump(mode="json", exclude_none=True)}, actor, key)

    @app.get("/inventory/warning", response_model=Page[dict], tags=["物料库存"], summary="查询库存与缺料预警 · MCP: inventory_warning")
    def _warnings(filters: Annotated[WarningFilter, Query()], actor: str = Depends(_actor)):
        """查询缺料、安全库存和采购交期风险。"""
        return service.query("warnings", filters.model_dump(exclude_none=True))

    @app.get("/inventory/movements", tags=["物料库存"], summary="查询原材料库存流水")
    def _movements(filters: Annotated[MovementFilter, Query()], actor: str = Depends(_actor)):
        """查询原材料数量和价值变化流水。"""
        return service.query("movements", filters.model_dump(exclude_none=True))

    @app.get("/inventory/finished", tags=["物料库存"], summary="查询成品库存")
    def _finished(actor: str = Depends(_actor)):
        """读取成品库存数量和价值。"""
        return service.query("finished")

    @app.get("/customers", tags=["销售订单与BOM"], summary="查询客户资料")
    def _customers(actor: str = Depends(_actor)):
        """列出客户主数据。"""
        return service.query("customers")

    @app.get("/products", tags=["销售订单与BOM"], summary="查询产品与 BOM 配方")
    def _products(actor: str = Depends(_actor)):
        """读取产品、售价、单位工费和 BOM。"""
        return service.query("products")

    @app.get("/sales-orders", tags=["销售订单与BOM"], summary="查询销售订单 · MCP: sales_order_query")
    def _sales(filters: Annotated[PageFilter, Query()], actor: str = Depends(_actor)):
        """分页查询销售订单及已确认收入和成本。"""
        return service.query("sales", filters.model_dump(exclude_none=True))

    @app.get("/sales-orders/{id}", tags=["销售订单与BOM"], summary="读取销售单与物料需求 · MCP: sales_order_details")
    def _sale(id: int, actor: str = Depends(_actor)):
        """读取销售订单和当前物料计划。"""
        return service.query("sale", {"id": id})

    @app.post("/sales-orders", status_code=201, tags=["销售订单与BOM"], summary="创建销售草稿")
    def _sales_create(body: SalesCreate, actor: str = Depends(_admin), key: str = Depends(_key)):
        """按已有客户编号或自定义客户名称创建销售草稿，保存配方与费用快照。"""
        return service.mutate("sales_create", body.model_dump(mode="json", exclude_none=True), actor, key)

    @app.post("/sales-orders/{id}/confirm", tags=["销售订单与BOM"], summary="确认销售单并预留物料")
    def _sales_confirm(id: int, actor: str = Depends(_admin), key: str = Depends(_key)):
        """确认销售单并占用可用物料。"""
        return service.mutate("sales_confirm", {"id": id}, actor, key)

    @app.post("/sales-orders/{id}/cancel", tags=["销售订单与BOM"], summary="取消销售单并释放预留")
    def _sales_cancel(id: int, actor: str = Depends(_admin), key: str = Depends(_key)):
        """取消可取消的销售单并释放占用。"""
        return service.mutate("sales_cancel", {"id": id}, actor, key)

    @app.get("/sales-orders/{id}/mrp", tags=["销售订单与BOM"], summary="查询销售单物料计划与采购建议")
    def _plan(id: int, actor: str = Depends(_actor)):
        """读取未开工销售单的齐套情况及采购建议。"""
        return service.query("plan", {"id": id})

    @app.post("/sales-orders/{id}/mrp", tags=["销售订单与BOM"], summary="重新计算销售单物料预留")
    def _replan(id: int, actor: str = Depends(_admin), key: str = Depends(_key)):
        """重新计算物料占用，保持重复计算幂等。"""
        return service.mutate("mrp", {"id": id}, actor, key)

    @app.post("/sales-orders/{id}/shipments", tags=["生产与交付"], summary="登记销售发货与交付")
    def _shipment(id: int, body: QuantityAction, actor: str = Depends(_admin), key: str = Depends(_key)):
        """发货并生成应收、收入与销售成本。"""
        return service.mutate("ship", {"id": id, **body.model_dump()}, actor, key)

    @app.get("/production-orders", tags=["生产与交付"], summary="查询生产工单")
    def _productions(filters: Annotated[PageFilter, Query()], actor: str = Depends(_actor)):
        """分页查询生产工单与完工成本。"""
        return service.query("productions", filters.model_dump(exclude_none=True))

    @app.post("/production-orders", status_code=201, tags=["生产与交付"], summary="创建生产工单")
    def _production_create(body: ProductionCreate, actor: str = Depends(_admin), key: str = Depends(_key)):
        """为销售订单创建生产工单。"""
        return service.mutate("production_create", body.model_dump(), actor, key)

    @app.post("/production-orders/{id}/start", tags=["生产与交付"], summary="生产领料开工")
    def _production_start(id: int, actor: str = Depends(_admin), key: str = Depends(_key)):
        """在物料齐套后领料开工。"""
        return service.mutate("production_start", {"id": id}, actor, key)

    @app.post("/production-orders/{id}/completions", tags=["生产与交付"], summary="登记生产完工与成品入库")
    def _complete(id: int, body: QuantityAction, actor: str = Depends(_admin), key: str = Depends(_key)):
        """登记本批完工数量并增加成品库存。"""
        return service.mutate("production_complete", {"id": id, **body.model_dump()}, actor, key)

    @app.get("/finance/summary", tags=["基础财务"], summary="查询应收应付与成本毛利")
    def _finance(actor: str = Depends(_actor)):
        """查询科目余额、累计毛利及应收应付。"""
        return service.query("finance")

    @app.get("/finance/journals", tags=["基础财务"], summary="查询会计凭证")
    def _journals(filters: Annotated[PageFilter, Query()], actor: str = Depends(_actor)):
        """查询自动生成的借贷凭证。"""
        return service.query("journals", filters.model_dump(exclude_none=True))

    @app.post("/finance/cash-transactions", tags=["基础财务"], summary="登记销售收款或采购付款")
    def _cash(body: CashCreate, actor: str = Depends(_admin), key: str = Depends(_key)):
        """办理销售收款或采购付款。"""
        return service.mutate("cash", body.model_dump(mode="json"), actor, key)

    @app.get("/audit-logs", tags=["系统辅助"], summary="查询业务操作审计日志")
    def _audit(filters: Annotated[PageFilter, Query()], actor: str = Depends(_admin)):
        """查询业务写入审计日志。"""
        return service.query("audit", filters.model_dump(exclude_none=True))

    static = Path(__file__).parent / "static"
    app.mount("/static", StaticFiles(directory=static), name="static")

    @app.get("/", include_in_schema=False)
    def _index():
        """显示与业务接口连接的 ERP 基础操作页。"""
        return FileResponse(static / "index.html")

    return app


app = create_app()
