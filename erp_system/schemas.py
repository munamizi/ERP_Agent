"""ERP HTTP 请求、核心响应和分页契约。"""

from datetime import date
from decimal import Decimal
from typing import Annotated, Generic, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field, StrictInt, StringConstraints, model_validator

Quantity = Annotated[StrictInt, Field(gt=0, le=1_000_000)]
Money = Annotated[Decimal, Field(gt=0, max_digits=12, decimal_places=2, allow_inf_nan=False)]
NonnegativeMoney = Annotated[Decimal, Field(ge=0, max_digits=12, decimal_places=2, allow_inf_nan=False)]
CustomerName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]


class Input(BaseModel):
    """拒绝未声明字段的请求基类。"""

    model_config = ConfigDict(extra="forbid")


class ErrorInfo(BaseModel):
    """可供调用方判断失败原因的错误信息。"""

    code: str
    message: str
    details: list[dict] | None = None


class ErrorResponse(BaseModel):
    """统一错误响应契约。"""

    error: ErrorInfo


class PageFilter(Input):
    """分页与通用关键词条件。"""

    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=50, ge=1, le=100)
    keyword: str | None = Field(default=None, max_length=100)
    name: str | None = Field(default=None, max_length=100)


class PartFilter(PageFilter):
    """零件名称、分类和供应商筛选条件。"""

    category: str | None = None
    supplier_id: int | None = Field(default=None, gt=0)


class SupplierFilter(PageFilter):
    """供应商关键词与准入条件。"""

    qualified: bool | None = None


class OrderFilter(PageFilter):
    """采购单明细筛选条件，日期按创建日期比较。"""

    supplier_id: int | None = Field(default=None, gt=0)
    part_id: int | None = Field(default=None, gt=0)
    sales_order_id: int | None = Field(default=None, gt=0)
    status: Literal["draft", "confirmed", "partially_received", "received", "cancelled"] | None = None
    start_date: date | None = None
    end_date: date | None = None


class WarningFilter(PageFilter):
    """库存预警类别筛选条件。"""

    type: Literal["shortage", "safety_stock", "late_inbound"] | None = None


class MovementFilter(PageFilter):
    """按物料筛选库存数量和价值流水。"""

    part_id: int | None = Field(default=None, gt=0)


class PurchaseLine(Input):
    """采购物料行；单价以人民币元传入。"""

    part_id: Quantity
    quantity: Quantity
    unit_price: Money


class PurchaseCreate(Input):
    """采购草稿请求。"""

    supplier_id: Quantity
    sales_order_id: Quantity | None = None
    expected_date: date
    freight: NonnegativeMoney = Decimal("0.00")
    notes: str = Field(default="", max_length=1000)
    currency: Literal["CNY"] = "CNY"
    lines: list[PurchaseLine] = Field(min_length=1, max_length=100)


class PurchaseUpdate(Input):
    """采购草稿修改或状态推进请求。"""

    expected_date: date | None = None
    freight: NonnegativeMoney | None = None
    notes: str | None = Field(default=None, max_length=1000)
    status: Literal["confirmed", "cancelled"] | None = None
    lines: list[PurchaseLine] | None = Field(default=None, min_length=1, max_length=100)


class ReceiptItem(Input):
    """实际收到的采购明细行和数量。"""

    line_id: Quantity
    quantity: Quantity


class ReceiptCreate(Input):
    """分批收货请求。"""

    received_on: date | None = None
    items: list[ReceiptItem] = Field(min_length=1, max_length=100)


class SalesCreate(Input):
    """销售草稿请求；客户编号或名称二选一，省略单价时使用默认售价。"""

    customer_id: Quantity | None = None
    customer_name: CustomerName | None = None
    product_id: Quantity
    quantity: Quantity
    unit_price: Money | None = None
    due_date: date

    @model_validator(mode="after")
    def _validate_customer(self) -> "SalesCreate":
        """要求客户编号和名称恰好提供一个，避免创建时客户归属不明确。"""
        if (self.customer_id is None) == (self.customer_name is None):
            raise ValueError("customer_id 和 customer_name 必须且只能提供一个")
        return self


class ProductionCreate(Input):
    """关联销售需求创建整批工单。"""

    sales_order_id: Quantity


class QuantityAction(Input):
    """完工或发货的本次实际数量。"""

    quantity: Quantity


class CashCreate(Input):
    """客户收款或供应商付款请求。"""

    kind: Literal["customer_receipt", "supplier_payment"]
    order_id: Quantity
    amount: Money


class SupplierOut(BaseModel):
    """ERP 供应商主数据。"""

    id: int
    code: str
    name: str
    city: str
    qualified: bool
    rating: str
    lead_days: int
    payment_terms: str
    contact: str
    phone: str
    description: str
    parts: list[dict]


class SupplierOfferOut(BaseModel):
    """ERP 供货关系与外部报价地址，合同价与最近成交价分别保存。"""

    supplier_id: int
    part_id: int
    supplier_name: str
    qualified: bool
    contract_price: str
    minimum_qty: int
    lead_days: int
    latest_purchase_price: str | None
    latest_purchase_at: str | None
    price_url: str


class PartOut(BaseModel):
    """零件规格、库存及供应商供货信息。"""

    id: int
    code: str
    name: str
    model: str
    category: str
    specs: str
    unit: str
    aliases: list[str]
    safety_stock: int
    on_hand: int
    reserved: int
    available: int
    inbound: int
    value: str
    average_cost: str
    suppliers: list[SupplierOfferOut]


class PurchaseLineOut(BaseModel):
    """含物料规格和累计收货量的采购明细行。"""

    id: int
    order_id: int
    part_id: int
    part_code: str
    name: str
    model: str
    unit: str
    quantity: int
    unit_price: str
    received_qty: int


class PurchaseOut(BaseModel):
    """采购单的完整业务响应。"""

    id: int
    number: str
    supplier_id: int
    supplier_name: str
    sales_order_id: int | None
    status: str
    expected_date: str
    freight: str
    freight_received: str
    notes: str
    created_at: str
    updated_at: str
    currency: str
    tax_included: bool
    total: str
    paid: str
    payable: str
    lines: list[PurchaseLineOut]
    receipts: list[dict]


T = TypeVar("T")


class Page(BaseModel, Generic[T]):
    """稳定的分页响应。"""

    items: list[T]
    total: int
    page: int
    page_size: int
