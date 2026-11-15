"""ERP 业务事务：销售、物料计划、采购、生产、交付与基础财务。"""

import hashlib
import json
import os
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

from sqlalchemy import Connection

from erp_system.catalog import CUSTOMERS, HISTORY_QUANTITIES, PARTS, SUPPLIERS
from erp_system.database import Database
from erp_system.money import allocate, to_fen, yuan

ACCOUNTS = {"RAW": "原材料", "WIP": "在制品", "FG": "产成品", "AP": "采购应付", "AR": "销售应收", "BANK": "银行存款", "REVENUE": "销售收入", "COGS": "销售成本", "PRODUCTION_PAYABLE": "生产费用应付", "OPENING_EQUITY": "期初权益"}


class BusinessError(Exception):
    """可直接转换为 HTTP 错误的业务异常。"""

    def __init__(self, code: str, message: str, status: int = 409):
        """保存业务错误码、提示和 HTTP 状态。"""
        self.code, self.message, self.status = code, message, status
        super().__init__(message)


def _rows(conn: Connection, sql: str, params: tuple = ()) -> list[dict]:
    """执行参数化查询并返回字典行列表。"""
    return [dict(row) for row in conn.exec_driver_sql(sql, params).mappings()]


def _one(conn: Connection, sql: str, params: tuple = ()) -> dict:
    """查询一条记录，不存在时返回业务对象缺失错误。"""
    rows = _rows(conn, sql, params)
    if not rows:
        raise BusinessError("NOT_FOUND", "业务对象不存在", 404)
    return rows[0]


def _insert(conn: Connection, table: str, values: dict) -> int:
    """为内部指定的表插入一行，字段值始终使用参数绑定。"""
    columns = ",".join(values)
    marks = ",".join("?" for _ in values)
    return conn.exec_driver_sql(f"INSERT INTO {table} ({columns}) VALUES ({marks})", tuple(values.values())).lastrowid


class ERPService:
    """集中处理业务校验，使页面和未来 MCP 工具调用相同的业务规则。"""

    def __init__(self, database: Database):
        """关联数据库并预留演示播种使用的业务时钟。"""
        self.db = database
        self._at: str | None = None

    def _now(self) -> str:
        """返回 UTC 时间，播种历史记录时使用指定的历史时间。"""
        return self._at or datetime.now(timezone.utc).isoformat(timespec="seconds")

    def initialize(self) -> None:
        """
        准备数据库，并升级旧版演示订单的客户归属。

        步骤：
            1. 执行尚未应用的数据库结构迁移。
            2. 首次启动时创建完整演示数据。
            3. 旧版数据只调整预置历史订单的客户，保留其他业务记录。

        Args:
            无。
        Returns:
            None - 创建或升级演示数据，不重置已有订单、库存及账务。
        """
        self.db.migrate()
        with self.db.write() as conn:
            version = _rows(conn, "SELECT value FROM metadata WHERE key='seed_version'")
            if not version:
                self._seed(conn, datetime.now(timezone(timedelta(hours=8))).date())
            elif version[0]["value"] == "1":
                self._upgrade_history_customers(conn)

    def _upgrade_history_customers(self, conn: Connection) -> None:
        """按预置单号、日期和数量识别旧历史单，只更换客户引用并记录数据版本。"""
        base_date = date.fromisoformat(_one(conn, "SELECT value FROM metadata WHERE key='base_date'")["value"])
        for batch, quantity in enumerate(HISTORY_QUANTITIES):
            created_at = f"{(base_date - timedelta(days=84 - batch * 14)).isoformat()}T08:00:00+00:00"
            orders = _rows(conn, "SELECT s.id FROM sales_orders s JOIN customers c ON c.id=s.customer_id WHERE s.number=? AND s.quantity=? AND s.created_at=? AND s.status='shipped' AND s.product_id=1 AND c.name=?", (f"SO-{batch + 1:06}", quantity, created_at, CUSTOMERS[1]["name"]))
            if not orders:
                continue
            customer_id = self._customer_by_name(conn, CUSTOMERS[batch + 1]["name"], CUSTOMERS[batch + 1]["contact"])
            conn.exec_driver_sql("UPDATE sales_orders SET customer_id=? WHERE id=?", (customer_id, orders[0]["id"]))
        conn.exec_driver_sql("UPDATE metadata SET value='2' WHERE key='seed_version'")

    def _customer_by_name(self, conn: Connection, name: str, contact: str = "") -> int:
        """复用同名客户；不存在时在当前销售事务中创建客户记录。"""
        existing = _rows(conn, "SELECT id FROM customers WHERE name=? ORDER BY id LIMIT 1", (name,))
        return existing[0]["id"] if existing else _insert(conn, "customers", {"name": name, "contact": contact})

    def mutate(self, action: str, payload: dict, actor: str, key: str) -> dict:
        """
        在单个事务中执行业务写入并保存幂等结果和审计记录。

        步骤：
            1. 根据操作、身份和请求键校验已有请求的内容。
            2. 执行业务动作，连同库存和凭证一起提交。
            3. 记录审计信息和请求结果，重复请求返回已保存结果。

        Args:
            action - 内部已注册的业务动作名称
            payload - 已经过请求模型校验的业务字段
            actor - 当前调用令牌对应的角色
            key - 调用方提供的幂等请求键
        Returns:
            业务动作结果；同键不同内容抛出幂等冲突错误。
        """
        text = json.dumps(payload, sort_keys=True, ensure_ascii=False)
        digest = hashlib.sha256(text.encode()).hexdigest()
        scope = f"{actor}:{action}"
        with self.db.write() as conn:
            existing = _rows(conn, "SELECT * FROM idempotency WHERE scope=? AND key=?", (scope, key))
            if existing:
                if existing[0]["payload_hash"] != digest:
                    raise BusinessError("IDEMPOTENCY_CONFLICT", "同一个请求键已用于不同的请求内容")
                return json.loads(existing[0]["response"])
            handlers = {
                "sales_create": self._sales_create, "sales_confirm": self._sales_confirm,
                "sales_cancel": self._sales_cancel, "mrp": self._mrp,
                "purchase_create": self._purchase_create, "purchase_update": self._purchase_update,
                "receive": self._receive, "production_create": self._production_create,
                "production_start": self._production_start, "production_complete": self._production_complete,
                "ship": self._ship, "cash": self._cash,
            }
            result = handlers[action](conn, payload)
            _insert(conn, "audit_logs", {"actor": actor, "action": action, "payload": text, "occurred_at": self._now()})
            _insert(conn, "idempotency", {"scope": scope, "key": key, "payload_hash": digest, "response": json.dumps(result, ensure_ascii=False)})
            return result

    def _number(self, conn: Connection, table: str, row_id: int, prefix: str) -> None:
        """为新单据设置稳定的业务单号。"""
        conn.exec_driver_sql(f"UPDATE {table} SET number=? WHERE id=?", (f"{prefix}-{row_id:06}", row_id))

    def _post(self, conn: Connection, kind: str, reference: int, description: str, lines: list[tuple]) -> None:
        """校验凭证借贷平衡并按来源单据保存凭证。"""
        if sum(d for _, d, _ in lines) != sum(c for _, _, c in lines) or any(d < 0 or c < 0 for _, d, c in lines):
            raise BusinessError("UNBALANCED_JOURNAL", "财务凭证借贷不平衡")
        row_id = _insert(conn, "journals", {"source_kind": kind, "source_id": reference, "description": description, "occurred_at": self._now()})
        self._number(conn, "journals", row_id, "JV")
        for account, debit, credit in lines:
            if debit or credit:
                _insert(conn, "journal_lines", {"journal_id": row_id, "account": account, "debit_fen": debit, "credit_fen": credit})

    def _move(self, conn: Connection, part_id: int, quantity: int, cost: int, kind: str, reference: int) -> None:
        """增加或扣减原材料数量与价值，并保存变化后的库存流水。"""
        conn.exec_driver_sql("UPDATE inventory SET on_hand=on_hand+?,value_fen=value_fen+? WHERE part_id=?", (quantity, cost, part_id))
        stock = _one(conn, "SELECT * FROM inventory WHERE part_id=?", (part_id,))
        _insert(conn, "inventory_movements", {"part_id": part_id, "quantity_delta": quantity, "value_delta_fen": cost, "on_hand_after": stock["on_hand"], "value_after_fen": stock["value_fen"], "kind": kind, "reference_id": reference, "occurred_at": self._now()})

    def _sales_create(self, conn: Connection, data: dict) -> dict:
        """按客户编号或名称创建销售草稿，并保存配方及单位生产费用快照。"""
        product = _one(conn, "SELECT * FROM products WHERE id=?", (data["product_id"],))
        customer_id = _one(conn, "SELECT id FROM customers WHERE id=?", (data["customer_id"],))["id"] if data.get("customer_id") else self._customer_by_name(conn, data["customer_name"])
        bom = _rows(conn, "SELECT part_id,quantity FROM bom WHERE product_id=?", (product["id"],))
        price = to_fen(data["unit_price"]) if data.get("unit_price") else product["sale_price_fen"]
        row_id = _insert(conn, "sales_orders", {"customer_id": customer_id, "product_id": product["id"], "quantity": data["quantity"], "unit_price_fen": price, "due_date": data["due_date"], "status": "draft", "bom_snapshot": json.dumps(bom), "labor_fen": product["labor_fen"], "overhead_fen": product["overhead_fen"], "created_at": self._now()})
        self._number(conn, "sales_orders", row_id, "SO")
        return self._sales_detail(conn, row_id)

    def _sales_confirm(self, conn: Connection, data: dict) -> dict:
        """确认销售草稿并同步物料预留。"""
        sale = _one(conn, "SELECT * FROM sales_orders WHERE id=?", (data["id"],))
        if sale["status"] != "draft":
            raise BusinessError("INVALID_STATUS", "只有销售草稿可以确认")
        conn.exec_driver_sql("UPDATE sales_orders SET status='confirmed' WHERE id=?", (sale["id"],))
        self._mrp(conn, {"id": sale["id"]})
        return self._sales_detail(conn, sale["id"])

    def _sales_cancel(self, conn: Connection, data: dict) -> dict:
        """取消尚未关联有效采购或生产工单的销售单，并释放预留。"""
        sale = _one(conn, "SELECT * FROM sales_orders WHERE id=?", (data["id"],))
        if sale["status"] not in ("draft", "confirmed"):
            raise BusinessError("INVALID_STATUS", "当前销售单状态不允许取消")
        if _rows(conn, "SELECT id FROM production_orders WHERE sales_order_id=?", (sale["id"],)) or _rows(conn, "SELECT id FROM purchase_orders WHERE sales_order_id=? AND status<>'cancelled'", (sale["id"],)):
            raise BusinessError("LINKED_DOCUMENT", "请先处理关联采购单；已建生产工单的销售单不能取消")
        for row in _rows(conn, "SELECT * FROM reservations WHERE sales_order_id=?", (sale["id"],)):
            conn.exec_driver_sql("UPDATE inventory SET reserved=reserved-? WHERE part_id=?", (row["quantity"], row["part_id"]))
        conn.exec_driver_sql("DELETE FROM reservations WHERE sales_order_id=?", (sale["id"],))
        conn.exec_driver_sql("UPDATE sales_orders SET status='cancelled' WHERE id=?", (sale["id"],))
        return self._sales_detail(conn, sale["id"])

    def _mrp(self, conn: Connection, data: dict) -> dict:
        """在未开工的销售需求中增量预留可用物料，重复执行不重复占用。"""
        sale = _one(conn, "SELECT * FROM sales_orders WHERE id=?", (data["id"],))
        if sale["status"] != "confirmed":
            raise BusinessError("INVALID_STATUS", "只对已确认且尚未开工的销售单计算物料计划")
        for line in json.loads(sale["bom_snapshot"]):
            part_id, required = line["part_id"], line["quantity"] * sale["quantity"]
            stock = _one(conn, "SELECT * FROM inventory WHERE part_id=?", (part_id,))
            existing = _rows(conn, "SELECT quantity FROM reservations WHERE sales_order_id=? AND part_id=?", (sale["id"], part_id))
            owned = existing[0]["quantity"] if existing else 0
            added = min(required - owned, stock["on_hand"] - stock["reserved"])
            conn.exec_driver_sql("INSERT INTO reservations VALUES (?,?,?) ON CONFLICT(sales_order_id,part_id) DO UPDATE SET quantity=quantity+excluded.quantity", (sale["id"], part_id, added))
            conn.exec_driver_sql("UPDATE inventory SET reserved=reserved+? WHERE part_id=?", (added, part_id))
        return self._plan(conn, sale)

    def _plan(self, conn: Connection, sale: dict) -> dict:
        """读取该订单的物料齐套情况及按时到货的关联采购建议。"""
        lines = []
        for item in json.loads(sale["bom_snapshot"]):
            part = _one(conn, "SELECT p.*,i.on_hand,i.reserved FROM parts p JOIN inventory i ON i.part_id=p.id WHERE p.id=?", (item["part_id"],))
            owned = _rows(conn, "SELECT quantity FROM reservations WHERE sales_order_id=? AND part_id=?", (sale["id"], part["id"]))
            allocated = owned[0]["quantity"] if owned else 0
            required = item["quantity"] * sale["quantity"]
            # 在途仅用于采购建议；物料是否齐套仍以实际预留量判断。
            inbound = _one(conn, "SELECT COALESCE(SUM(l.quantity-l.received_qty),0) AS qty FROM purchase_lines l JOIN purchase_orders o ON o.id=l.order_id WHERE l.part_id=? AND o.sales_order_id=? AND o.status IN ('confirmed','partially_received') AND o.expected_date<=?", (part["id"], sale["id"], sale["due_date"]))["qty"]
            missing = max(0, required - allocated)
            lines.append({"part_id": part["id"], "part_code": part["code"], "name": part["name"], "model": part["model"], "unit": part["unit"], "required": required, "on_hand": part["on_hand"], "reserved_total": part["reserved"], "reserved_for_order": allocated, "available": part["on_hand"] - part["reserved"], "shortage": missing, "on_time_inbound": inbound, "suggested_purchase_qty": max(0, missing - inbound)})
        return {"sales_order_id": sale["id"], "due_date": sale["due_date"], "ready": all(line["shortage"] == 0 for line in lines), "items": lines}

    def _validate_purchase(self, conn: Connection, supplier_id: int, lines: list[dict]) -> list[dict]:
        """校验合格供应商、供货关系、起订量及零件重复行。"""
        supplier = _one(conn, "SELECT * FROM suppliers WHERE id=?", (supplier_id,))
        if not supplier["qualified"]:
            raise BusinessError("SUPPLIER_UNQUALIFIED", "供应商尚未通过企业准入审核")
        checked, seen = [], set()
        for line in lines:
            part_id = line["part_id"]
            if part_id in seen:
                raise BusinessError("DUPLICATE_PART", "同一采购单不能重复填写相同零件", 422)
            relation = _one(conn, "SELECT * FROM supplier_parts WHERE supplier_id=? AND part_id=?", (supplier_id, part_id))
            if line["quantity"] < relation["minimum_qty"]:
                raise BusinessError("BELOW_MINIMUM_QTY", f"零件 {part_id} 起订量为 {relation['minimum_qty']}")
            checked.append({"part_id": part_id, "quantity": line["quantity"], "unit_price_fen": to_fen(line["unit_price"])})
            seen.add(part_id)
        return checked

    def _purchase_create(self, conn: Connection, data: dict) -> dict:
        """创建采购草稿，成交价独立保存，不自动改写网页报价或历史价格。"""
        lines = self._validate_purchase(conn, data["supplier_id"], data["lines"])
        if data.get("sales_order_id"):
            sale = _one(conn, "SELECT * FROM sales_orders WHERE id=?", (data["sales_order_id"],))
            if sale["status"] != "confirmed":
                raise BusinessError("INVALID_STATUS", "只能关联已确认且尚未开工的销售单")
            required_parts = {line["part_id"] for line in json.loads(sale["bom_snapshot"])}
            if any(line["part_id"] not in required_parts for line in lines):
                raise BusinessError("BOM_MISMATCH", "采购零件不属于关联销售单的 BOM")
        row_id = _insert(conn, "purchase_orders", {"supplier_id": data["supplier_id"], "sales_order_id": data.get("sales_order_id"), "status": "draft", "expected_date": data["expected_date"], "freight_fen": to_fen(data.get("freight", "0.00")), "notes": data.get("notes", ""), "created_at": self._now(), "updated_at": self._now()})
        self._number(conn, "purchase_orders", row_id, "PO")
        for line in lines:
            _insert(conn, "purchase_lines", {"order_id": row_id, **line})
        return self._purchase_detail(conn, row_id)

    def _purchase_update(self, conn: Connection, data: dict) -> dict:
        """修改采购草稿，或确认、取消未收货采购单。"""
        order = _one(conn, "SELECT * FROM purchase_orders WHERE id=?", (data["id"],))
        changes = {k: v for k, v in data.items() if k != "id"}
        if not changes:
            raise BusinessError("EMPTY_UPDATE", "请提供至少一个修改字段", 422)
        status = changes.pop("status", None)
        if order["status"] not in ("draft", "confirmed"):
            raise BusinessError("INVALID_STATUS", "已收货或已取消的采购单不能修改")
        if changes and order["status"] != "draft":
            raise BusinessError("INVALID_STATUS", "采购单确认后只能在未收货时取消")
        if "lines" in changes:
            lines = self._validate_purchase(conn, order["supplier_id"], changes.pop("lines"))
            if order["sales_order_id"]:
                sale = _one(conn, "SELECT * FROM sales_orders WHERE id=?", (order["sales_order_id"],))
                part_ids = {line["part_id"] for line in json.loads(sale["bom_snapshot"])}
                if any(line["part_id"] not in part_ids for line in lines):
                    raise BusinessError("BOM_MISMATCH", "采购零件不属于关联销售单的 BOM")
            conn.exec_driver_sql("DELETE FROM purchase_lines WHERE order_id=?", (order["id"],))
            for line in lines:
                _insert(conn, "purchase_lines", {"order_id": order["id"], **line})
        for field in ("expected_date", "notes", "freight"):
            if field in changes:
                column = "freight_fen" if field == "freight" else field
                value = to_fen(changes[field]) if field == "freight" else changes[field]
                conn.exec_driver_sql(f"UPDATE purchase_orders SET {column}=? WHERE id=?", (value, order["id"]))
        if status:
            if status == "confirmed" and order["status"] != "draft":
                raise BusinessError("INVALID_STATUS", "只有采购草稿可以确认")
            conn.exec_driver_sql("UPDATE purchase_orders SET status=? WHERE id=?", (status, order["id"]))
        conn.exec_driver_sql("UPDATE purchase_orders SET updated_at=? WHERE id=?", (self._now(), order["id"]))
        return self._purchase_detail(conn, order["id"])

    def _receive(self, conn: Connection, data: dict) -> dict:
        """分批收货、分摊运费并形成库存流水及采购应付凭证。"""
        order = _one(conn, "SELECT * FROM purchase_orders WHERE id=?", (data["id"],))
        if order["status"] not in ("confirmed", "partially_received"):
            raise BusinessError("INVALID_STATUS", "只有已确认且未全部收货的采购单可以收货")
        checked, seen = [], set()
        for item in data["items"]:
            if item["line_id"] in seen:
                raise BusinessError("DUPLICATE_LINE", "收货明细行重复", 422)
            line = _one(conn, "SELECT * FROM purchase_lines WHERE id=? AND order_id=?", (item["line_id"], order["id"]))
            if item["quantity"] > line["quantity"] - line["received_qty"]:
                raise BusinessError("OVER_RECEIPT", "收货数量超过采购单未收数量")
            checked.append((line, item["quantity"], item["quantity"] * line["unit_price_fen"]))
            seen.add(item["line_id"])
        total_order = _one(conn, "SELECT SUM(quantity*unit_price_fen) AS total FROM purchase_lines WHERE order_id=?", (order["id"],))["total"]
        received_before = _one(conn, "SELECT SUM(received_qty*unit_price_fen) AS total FROM purchase_lines WHERE order_id=?", (order["id"],))["total"]
        goods = sum(value for _, _, value in checked)
        target_freight = int((Decimal(order["freight_fen"]) * (received_before + goods) / total_order).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
        freight = target_freight - order["freight_received_fen"]
        costs = [goods_value + extra for (_, _, goods_value), extra in zip(checked, allocate(freight, [v for _, _, v in checked]))]
        receipt_id = _insert(conn, "goods_receipts", {"order_id": order["id"], "received_on": data.get("received_on", self._now()[:10]), "amount_fen": goods + freight})
        self._number(conn, "goods_receipts", receipt_id, "GR")
        for (line, quantity, _), cost in zip(checked, costs):
            conn.exec_driver_sql("UPDATE purchase_lines SET received_qty=received_qty+? WHERE id=?", (quantity, line["id"]))
            _insert(conn, "receipt_lines", {"receipt_id": receipt_id, "purchase_line_id": line["id"], "quantity": quantity, "cost_fen": cost})
            self._move(conn, line["part_id"], quantity, cost, "purchase_receipt", receipt_id)
        remaining = _one(conn, "SELECT SUM(quantity-received_qty) AS qty FROM purchase_lines WHERE order_id=?", (order["id"],))["qty"]
        conn.exec_driver_sql("UPDATE purchase_orders SET status=?,freight_received_fen=?,updated_at=? WHERE id=?", ("received" if remaining == 0 else "partially_received", target_freight, self._now(), order["id"]))
        self._post(conn, "receipt", receipt_id, "采购收货确认应付", [("RAW", goods + freight, 0), ("AP", 0, goods + freight)])
        # 收货后按销售单编号顺序补齐未开工订单的预留，避免到货仍显示缺料。
        for sale in _rows(conn, "SELECT id FROM sales_orders WHERE status='confirmed' ORDER BY id"):
            self._mrp(conn, sale)
        return {"receipt_id": receipt_id, "amount": yuan(goods + freight), "order": self._purchase_detail(conn, order["id"])}

    def _production_create(self, conn: Connection, data: dict) -> dict:
        """为销售需求建立唯一生产工单。"""
        sale = _one(conn, "SELECT * FROM sales_orders WHERE id=?", (data["sales_order_id"],))
        if sale["status"] != "confirmed" or _rows(conn, "SELECT id FROM production_orders WHERE sales_order_id=?", (sale["id"],)):
            raise BusinessError("INVALID_PRODUCTION", "销售单状态不正确或已存在生产工单")
        row_id = _insert(conn, "production_orders", {"sales_order_id": sale["id"], "quantity": sale["quantity"], "status": "draft", "created_at": self._now()})
        self._number(conn, "production_orders", row_id, "MO")
        return self._production_detail(conn, row_id)

    def _production_start(self, conn: Connection, data: dict) -> dict:
        """检查整张工单齐套后领料，并将实际材料成本转入在制品。"""
        work = _one(conn, "SELECT * FROM production_orders WHERE id=?", (data["id"],))
        sale = _one(conn, "SELECT * FROM sales_orders WHERE id=?", (work["sales_order_id"],))
        if work["status"] != "draft":
            raise BusinessError("INVALID_STATUS", "工单已经开工")
        self._mrp(conn, {"id": sale["id"]})
        if not self._plan(conn, sale)["ready"]:
            raise BusinessError("MATERIAL_SHORTAGE", "物料未齐套，不能整批开工")
        total = 0
        for line in _rows(conn, "SELECT r.*,i.on_hand,i.value_fen FROM reservations r JOIN inventory i ON i.part_id=r.part_id WHERE sales_order_id=?", (sale["id"],)):
            qty = line["quantity"]
            cost = int((Decimal(line["value_fen"]) * qty / line["on_hand"]).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
            total += cost
            conn.exec_driver_sql("UPDATE inventory SET reserved=reserved-? WHERE part_id=?", (qty, line["part_id"]))
            self._move(conn, line["part_id"], -qty, -cost, "production_issue", work["id"])
        conn.exec_driver_sql("DELETE FROM reservations WHERE sales_order_id=?", (sale["id"],))
        conn.exec_driver_sql("UPDATE production_orders SET status='in_progress',material_cost_fen=? WHERE id=?", (total, work["id"]))
        conn.exec_driver_sql("UPDATE sales_orders SET status='in_production' WHERE id=?", (sale["id"],))
        self._post(conn, "issue", work["id"], "生产领料", [("WIP", total, 0), ("RAW", 0, total)])
        return self._production_detail(conn, work["id"])

    def _production_complete(self, conn: Connection, data: dict) -> dict:
        """按实际完工数量分摊材料、人工和制造费，并增加成品库存。"""
        work = _one(conn, "SELECT * FROM production_orders WHERE id=?", (data["id"],))
        sale = _one(conn, "SELECT * FROM sales_orders WHERE id=?", (work["sales_order_id"],))
        if work["status"] not in ("in_progress", "partially_completed"):
            raise BusinessError("INVALID_STATUS", "工单尚未开工或已全部完工")
        qty = data["quantity"]
        if qty > work["quantity"] - work["completed_qty"]:
            raise BusinessError("OVER_COMPLETION", "完工数量超过工单剩余数量")
        cumulative = work["completed_qty"] + qty
        target = int((Decimal(work["material_cost_fen"]) * cumulative / work["quantity"]).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
        material = target - work["allocated_material_fen"]
        labor, overhead = qty * sale["labor_fen"], qty * sale["overhead_fen"]
        total = material + labor + overhead
        completion = _insert(conn, "production_completions", {"production_id": work["id"], "quantity": qty, "material_fen": material, "labor_fen": labor, "overhead_fen": overhead, "total_fen": total, "occurred_at": self._now()})
        conn.exec_driver_sql("UPDATE production_orders SET completed_qty=?,allocated_material_fen=?,status=? WHERE id=?", (cumulative, target, "completed" if cumulative == work["quantity"] else "partially_completed", work["id"]))
        conn.exec_driver_sql("UPDATE finished_inventory SET quantity=quantity+?,value_fen=value_fen+? WHERE product_id=?", (qty, total, sale["product_id"]))
        if cumulative == work["quantity"]:
            conn.exec_driver_sql("UPDATE sales_orders SET status='ready_to_ship' WHERE id=?", (sale["id"],))
        self._post(conn, "completion", completion, "完工入库及生产费用归集", [("WIP", labor + overhead, 0), ("PRODUCTION_PAYABLE", 0, labor + overhead), ("FG", total, 0), ("WIP", 0, total)])
        return self._production_detail(conn, work["id"])

    def _ship(self, conn: Connection, data: dict) -> dict:
        """按该订单的已完工数量发货，确认应收与实际销售成本。"""
        sale = _one(conn, "SELECT * FROM sales_orders WHERE id=?", (data["id"],))
        work = _one(conn, "SELECT * FROM production_orders WHERE sales_order_id=?", (sale["id"],))
        qty = data["quantity"]
        if qty > work["completed_qty"] - sale["shipped_qty"]:
            raise BusinessError("INSUFFICIENT_FINISHED_GOODS", "该订单的未发货完工数量不足")
        completed_cost = _one(conn, "SELECT COALESCE(SUM(total_fen),0) AS value FROM production_completions WHERE production_id=?", (work["id"],))["value"]
        shipped_cost = _one(conn, "SELECT COALESCE(SUM(cost_fen),0) AS value FROM shipments WHERE sales_order_id=?", (sale["id"],))["value"]
        target = int((Decimal(completed_cost) * (sale["shipped_qty"] + qty) / work["completed_qty"]).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
        cost = target - shipped_cost
        revenue = qty * sale["unit_price_fen"]
        shipment = _insert(conn, "shipments", {"sales_order_id": sale["id"], "quantity": qty, "revenue_fen": revenue, "cost_fen": cost, "occurred_at": self._now()})
        self._number(conn, "shipments", shipment, "SH")
        conn.exec_driver_sql("UPDATE finished_inventory SET quantity=quantity-?,value_fen=value_fen-? WHERE product_id=?", (qty, cost, sale["product_id"]))
        conn.exec_driver_sql("UPDATE sales_orders SET shipped_qty=shipped_qty+?,status=? WHERE id=?", (qty, "shipped" if sale["shipped_qty"] + qty == sale["quantity"] else sale["status"], sale["id"]))
        self._post(conn, "shipment", shipment, "发货确认收入与销售成本", [("AR", revenue, 0), ("REVENUE", 0, revenue), ("COGS", cost, 0), ("FG", 0, cost)])
        return {"shipment_id": shipment, "revenue": yuan(revenue), "cost": yuan(cost), "gross_profit": yuan(revenue - cost), "sales_order": self._sales_detail(conn, sale["id"])}

    def _cash(self, conn: Connection, data: dict) -> dict:
        """按已形成的应收应付办理分次收付款，禁止超额结算。"""
        kind, order_id, amount = data["kind"], data["order_id"], to_fen(data["amount"])
        if kind == "customer_receipt":
            _one(conn, "SELECT id FROM sales_orders WHERE id=?", (order_id,))
            accrued = _one(conn, "SELECT COALESCE(SUM(revenue_fen),0) AS value FROM shipments WHERE sales_order_id=?", (order_id,))["value"]
        else:
            _one(conn, "SELECT id FROM purchase_orders WHERE id=?", (order_id,))
            accrued = _one(conn, "SELECT COALESCE(SUM(amount_fen),0) AS value FROM goods_receipts WHERE order_id=?", (order_id,))["value"]
        paid = _one(conn, "SELECT COALESCE(SUM(amount_fen),0) AS value FROM cash_transactions WHERE kind=? AND order_id=?", (kind, order_id))["value"]
        if amount > accrued - paid:
            raise BusinessError("OVER_PAYMENT", "金额超过该单据尚未结算的应收或应付")
        cash_id = _insert(conn, "cash_transactions", {"kind": kind, "order_id": order_id, "amount_fen": amount, "occurred_at": self._now()})
        entries = [("BANK", amount, 0), ("AR", 0, amount)] if kind == "customer_receipt" else [("AP", amount, 0), ("BANK", 0, amount)]
        self._post(conn, "cash", cash_id, "客户收款" if kind == "customer_receipt" else "供应商付款", entries)
        return {"id": cash_id, "kind": kind, "amount": yuan(amount), "remaining": yuan(accrued - paid - amount)}

    def _money_fields(self, row: dict) -> dict:
        """将数据库中的金额列转换为接口的元字符串字段。"""
        return {key[:-4] if key.endswith("_fen") else key: yuan(value) if key.endswith("_fen") else value for key, value in row.items()}

    def _purchase_detail(self, conn: Connection, order_id: int) -> dict:
        """返回含供应商、零件、收货及结算信息的采购单。"""
        order = _one(conn, "SELECT o.*,s.name AS supplier_name FROM purchase_orders o JOIN suppliers s ON s.id=o.supplier_id WHERE o.id=?", (order_id,))
        lines = _rows(conn, "SELECT l.*,p.code AS part_code,p.name,p.model,p.unit FROM purchase_lines l JOIN parts p ON p.id=l.part_id WHERE order_id=? ORDER BY l.id", (order_id,))
        total = sum(line["quantity"] * line["unit_price_fen"] for line in lines) + order["freight_fen"]
        accrued = _one(conn, "SELECT COALESCE(SUM(amount_fen),0) AS value FROM goods_receipts WHERE order_id=?", (order_id,))["value"]
        paid = _one(conn, "SELECT COALESCE(SUM(amount_fen),0) AS value FROM cash_transactions WHERE kind='supplier_payment' AND order_id=?", (order_id,))["value"]
        return {**self._money_fields(order), "currency": "CNY", "tax_included": False, "total": yuan(total), "payable": yuan(accrued - paid), "paid": yuan(paid), "lines": [self._money_fields(line) for line in lines], "receipts": [self._money_fields(row) for row in _rows(conn, "SELECT * FROM goods_receipts WHERE order_id=? ORDER BY id", (order_id,))]}

    def _sales_detail(self, conn: Connection, sale_id: int) -> dict:
        """返回销售单、累计交付金额、实际成本和物料计划。"""
        sale = _one(conn, "SELECT s.*,c.name AS customer_name,p.name AS product_name FROM sales_orders s JOIN customers c ON c.id=s.customer_id JOIN products p ON p.id=s.product_id WHERE s.id=?", (sale_id,))
        shipment = _one(conn, "SELECT COALESCE(SUM(revenue_fen),0) AS revenue,COALESCE(SUM(cost_fen),0) AS cost FROM shipments WHERE sales_order_id=?", (sale_id,))
        paid = _one(conn, "SELECT COALESCE(SUM(amount_fen),0) AS value FROM cash_transactions WHERE kind='customer_receipt' AND order_id=?", (sale_id,))["value"]
        result = self._money_fields(sale)
        result["bom_snapshot"] = json.loads(sale["bom_snapshot"])
        return {**result, "total": yuan(sale["quantity"] * sale["unit_price_fen"]), "recognized_revenue": yuan(shipment["revenue"]), "recognized_cost": yuan(shipment["cost"]), "gross_profit": yuan(shipment["revenue"] - shipment["cost"]), "receivable": yuan(shipment["revenue"] - paid), "paid": yuan(paid), "mrp": self._plan(conn, sale) if sale["status"] == "confirmed" else None}

    def _production_detail(self, conn: Connection, row_id: int) -> dict:
        """返回工单及逐批完工成本。"""
        work = _one(conn, "SELECT w.*,s.number AS sales_order_number,p.name AS product_name FROM production_orders w JOIN sales_orders s ON s.id=w.sales_order_id JOIN products p ON p.id=s.product_id WHERE w.id=?", (row_id,))
        completions = _rows(conn, "SELECT * FROM production_completions WHERE production_id=? ORDER BY id", (row_id,))
        return {**self._money_fields(work), "completions": [self._money_fields(row) for row in completions], "completed_cost": yuan(sum(row["total_fen"] for row in completions))}

    def _parts(self, conn: Connection) -> list[dict]:
        """组装零件、库存、供货价和历史成交价，便于采购分析。"""
        result = []
        root_url = os.getenv("SUPPLIER_BASE_URL", "http://localhost:8080").rstrip("/")
        for part in _rows(conn, "SELECT p.*,i.on_hand,i.reserved,i.value_fen FROM parts p JOIN inventory i ON i.part_id=p.id ORDER BY p.id"):
            suppliers = []
            for offer in _rows(conn, "SELECT sp.*,s.name AS supplier_name,s.qualified FROM supplier_parts sp JOIN suppliers s ON s.id=sp.supplier_id WHERE part_id=? ORDER BY supplier_id", (part["id"],)):
                latest = _rows(conn, "SELECT l.unit_price_fen,o.created_at FROM purchase_lines l JOIN purchase_orders o ON o.id=l.order_id WHERE l.part_id=? AND o.supplier_id=? AND l.received_qty>0 ORDER BY o.created_at DESC,o.id DESC LIMIT 1", (part["id"], offer["supplier_id"]))
                slug = next(s["slug"] for s in SUPPLIERS if s["id"] == offer["supplier_id"])
                suppliers.append({**self._money_fields(offer), "qualified": bool(offer["qualified"]), "latest_purchase_price": yuan(latest[0]["unit_price_fen"]) if latest else None, "latest_purchase_at": latest[0]["created_at"] if latest else None, "price_url": f"{root_url}/{slug}/products/{part['code']}.html"})
            avg = int((Decimal(part["value_fen"]) / part["on_hand"]).quantize(Decimal("1"), rounding=ROUND_HALF_UP)) if part["on_hand"] else 0
            inbound = _one(conn, "SELECT COALESCE(SUM(l.quantity-l.received_qty),0) AS qty FROM purchase_lines l JOIN purchase_orders o ON o.id=l.order_id WHERE l.part_id=? AND o.status IN ('confirmed','partially_received')", (part["id"],))["qty"]
            result.append({**self._money_fields(part), "aliases": json.loads(part["aliases"]), "available": part["on_hand"] - part["reserved"], "inbound": inbound, "average_cost": yuan(avg), "suppliers": suppliers})
        return result

    def _warnings(self, conn: Connection) -> list[dict]:
        """分别汇总订单缺料、安全库存和关联采购延期风险。"""
        result = []
        for sale in _rows(conn, "SELECT * FROM sales_orders WHERE status='confirmed' ORDER BY id"):
            for line in self._plan(conn, sale)["items"]:
                if line["shortage"]:
                    result.append({"type": "shortage", "sales_order_id": sale["id"], "sales_order_number": sale["number"], "due_date": sale["due_date"], **line})
        for part in self._parts(conn):
            if part["available"] < part["safety_stock"]:
                result.append({"type": "safety_stock", "part_id": part["id"], "part_code": part["code"], "name": part["name"], "available": part["available"], "safety_stock": part["safety_stock"]})
        for row in _rows(conn, "SELECT o.id,o.number,o.expected_date,o.sales_order_id,s.due_date FROM purchase_orders o JOIN sales_orders s ON s.id=o.sales_order_id WHERE o.status IN ('confirmed','partially_received') AND o.expected_date>s.due_date"):
            result.append({"type": "late_inbound", **row})
        return result

    def _finance(self, conn: Connection) -> dict:
        """汇总科目余额、已确认收入成本、订单应收应付及凭证平衡。"""
        sums = _rows(conn, "SELECT account,SUM(debit_fen) AS debit,SUM(credit_fen) AS credit FROM journal_lines GROUP BY account")
        balances = {row["account"]: row["debit"] - row["credit"] for row in sums}
        accounts = [{"code": code, "name": name, "debit_balance": yuan(max(0, balances.get(code, 0))), "credit_balance": yuan(max(0, -balances.get(code, 0)))} for code, name in ACCOUNTS.items()]
        revenue, cost = -balances.get("REVENUE", 0), balances.get("COGS", 0)
        return {"currency": "CNY", "tax_included": False, "revenue": yuan(revenue), "cost": yuan(cost), "gross_profit": yuan(revenue - cost), "receivable": yuan(balances.get("AR", 0)), "payable": yuan(-balances.get("AP", 0)), "production_payable": yuan(-balances.get("PRODUCTION_PAYABLE", 0)), "bank": yuan(balances.get("BANK", 0)), "balanced": sum(balances.values()) == 0, "accounts": accounts}

    def query(self, kind: str, filters: dict | None = None) -> dict:
        """
        查询业务对象和分页列表，所有查询均不改变状态。

        内容：
            组装销售、采购、生产、库存和财务明细。
            按关键词、关联编号、状态和日期筛选分页列表。

        Args:
            kind - 已注册的查询种类
            filters - 查询条件，包含分页、关键词或对象编号等字段
        Returns:
            业务明细，或包含 items、total、page、page_size 的分页结果。
        """
        filters = {k: v for k, v in (filters or {}).items() if v is not None}
        with self.db.read() as conn:
            if kind == "sale":
                return self._sales_detail(conn, filters["id"])
            if kind == "purchase":
                return self._purchase_detail(conn, filters["id"])
            if kind == "production":
                return self._production_detail(conn, filters["id"])
            if kind == "plan":
                return self._plan(conn, _one(conn, "SELECT * FROM sales_orders WHERE id=? AND status='confirmed'", (filters["id"],)))
            if kind == "finance":
                return self._finance(conn)
            if kind == "parts":
                items = self._parts(conn)
                if "supplier_id" in filters:
                    items = [p for p in items if any(s["supplier_id"] == filters["supplier_id"] for s in p["suppliers"])]
                if "category" in filters:
                    items = [p for p in items if p["category"] == filters["category"]]
            elif kind == "suppliers":
                items = [{**row, "qualified": bool(row["qualified"])} for row in _rows(conn, "SELECT * FROM suppliers ORDER BY id")]
                for supplier in items:
                    supplier["parts"] = [{"part_id": p["id"], "part_code": p["code"], "name": p["name"], "model": p["model"], "aliases": p["aliases"]} for p in self._parts(conn) if any(s["supplier_id"] == supplier["id"] for s in p["suppliers"])]
                if "qualified" in filters:
                    items = [s for s in items if s["qualified"] == filters["qualified"]]
            elif kind == "purchases":
                items = [self._purchase_detail(conn, row["id"]) for row in _rows(conn, "SELECT id FROM purchase_orders ORDER BY id DESC")]
                if "supplier_id" in filters:
                    items = [o for o in items if o["supplier_id"] == filters["supplier_id"]]
                if "part_id" in filters:
                    items = [o for o in items if any(line["part_id"] == filters["part_id"] for line in o["lines"])]
                if "sales_order_id" in filters:
                    items = [o for o in items if o["sales_order_id"] == filters["sales_order_id"]]
                for field, compare in (("start_date", "start"), ("end_date", "end")):
                    if field in filters:
                        items = [o for o in items if (o["created_at"][:10] >= str(filters[field]) if compare == "start" else o["created_at"][:10] <= str(filters[field]))]
            elif kind == "sales":
                items = [self._sales_detail(conn, row["id"]) for row in _rows(conn, "SELECT id FROM sales_orders ORDER BY id DESC")]
            elif kind == "productions":
                items = [self._production_detail(conn, row["id"]) for row in _rows(conn, "SELECT id FROM production_orders ORDER BY id DESC")]
            elif kind == "warnings":
                items = self._warnings(conn)
                if "type" in filters:
                    items = [item for item in items if item["type"] == filters["type"]]
            elif kind == "customers":
                items = _rows(conn, "SELECT * FROM customers ORDER BY id")
            elif kind == "products":
                items = [self._money_fields(row) for row in _rows(conn, "SELECT * FROM products ORDER BY id")]
                for item in items:
                    item["bom"] = _rows(conn, "SELECT b.part_id,b.quantity,p.code AS part_code,p.name,p.model,p.unit FROM bom b JOIN parts p ON p.id=b.part_id WHERE product_id=?", (item["id"],))
            elif kind == "finished":
                items = [self._money_fields(row) for row in _rows(conn, "SELECT i.*,p.name FROM finished_inventory i JOIN products p ON p.id=i.product_id")]
            elif kind == "movements":
                items = [self._money_fields(row) for row in _rows(conn, "SELECT m.*,p.name,p.code AS part_code FROM inventory_movements m JOIN parts p ON p.id=m.part_id ORDER BY m.id DESC")]
                if "part_id" in filters:
                    items = [i for i in items if i["part_id"] == filters["part_id"]]
            elif kind == "journals":
                items = _rows(conn, "SELECT * FROM journals ORDER BY id DESC")
                for item in items:
                    item["lines"] = [self._money_fields(row) for row in _rows(conn, "SELECT * FROM journal_lines WHERE journal_id=?", (item["id"],))]
                    item["balanced"] = sum(to_fen(l["debit"]) - to_fen(l["credit"]) for l in item["lines"]) == 0
            elif kind == "audit":
                items = _rows(conn, "SELECT * FROM audit_logs ORDER BY id DESC")
                for item in items:
                    item["payload"] = json.loads(item["payload"])
            else:
                raise BusinessError("UNKNOWN_QUERY", "查询类型不存在", 404)
            if "status" in filters:
                items = [item for item in items if item.get("status") == filters["status"]]
            keyword = str(filters.get("keyword") or filters.get("name") or "").strip().casefold()
            if keyword:
                if kind == "parts":
                    items = [item for item in items if keyword in " ".join([item["name"], item["model"], item["code"], item["specs"], *item["aliases"]]).casefold()]
                else:
                    items = [item for item in items if keyword in json.dumps(list(item.values()), ensure_ascii=False).casefold()]
            page, size = filters.get("page", 1), filters.get("page_size", 50)
            return {"items": items[(page - 1) * size:page * size], "total": len(items), "page": page, "page_size": size}

    def reset(self, base_date: date) -> None:
        """
        清空业务表后重新播种演示数据，保留已应用的数据库迁移。

        Args:
            base_date - 演示当前日期，历史单据和交付日期据此生成
        Returns:
            None - 事务内替换演示业务数据；调用方须先备份并取得重置授权。
        """
        with self.db.write() as conn:
            tables = ["audit_logs", "idempotency", "cash_transactions", "journal_lines", "journals", "shipments", "production_completions", "production_orders", "inventory_movements", "receipt_lines", "goods_receipts", "purchase_lines", "purchase_orders", "reservations", "sales_orders", "finished_inventory", "inventory", "bom", "products", "customers", "supplier_parts", "parts", "suppliers", "metadata"]
            for table in tables:
                conn.exec_driver_sql(f"DELETE FROM {table}")
            conn.exec_driver_sql("DELETE FROM sqlite_sequence")
            self._seed(conn, base_date)

    def _seed(self, conn: Connection, base_date: date) -> None:
        """通过真实业务处理流程播种六批历史订单，再建立大学的缺料订单。"""
        self._at = f"{(base_date - timedelta(days=90)).isoformat()}T08:00:00+00:00"
        try:
            for supplier in SUPPLIERS:
                _insert(conn, "suppliers", {k: v for k, v in supplier.items() if k != "slug"})
            total_opening = 0
            for part in PARTS:
                _insert(conn, "parts", {k: part[k] for k in ("id", "code", "name", "model", "category", "specs", "unit")} | {"aliases": json.dumps(part["aliases"], ensure_ascii=False), "safety_stock": part["safety"]})
                value = part["stock"] * to_fen(part["price"])
                _insert(conn, "inventory", {"part_id": part["id"], "on_hand": 0, "reserved": 0, "value_fen": 0})
                self._move(conn, part["id"], part["stock"], value, "opening", 1)
                total_opening += value
                for supplier in SUPPLIERS:
                    factor = {1: Decimal("1"), 2: Decimal("0.95"), 3: Decimal("1.04"), 4: Decimal("0.85")}[supplier["id"]]
                    price = int((to_fen(part["price"]) * factor).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
                    _insert(conn, "supplier_parts", {"supplier_id": supplier["id"], "part_id": part["id"], "contract_price_fen": price, "minimum_qty": 100 if supplier["id"] == 2 and part["id"] == 1 else 1, "lead_days": supplier["lead_days"]})
            _insert(conn, "products", {"id": 1, "code": "NOTE-PRO16", "name": "凌云 Pro16 高性能笔记本", "sale_price_fen": 650000, "labor_fen": 20000, "overhead_fen": 10000})
            _insert(conn, "finished_inventory", {"product_id": 1, "quantity": 0, "value_fen": 0})
            for part in PARTS:
                _insert(conn, "bom", {"product_id": 1, "part_id": part["id"], "quantity": part["bom_qty"]})
            for customer in CUSTOMERS:
                _insert(conn, "customers", customer)
            self._post(conn, "opening", 1, "期初库存与银行资金", [("RAW", total_opening, 0), ("BANK", 100000000, 0), ("OPENING_EQUITY", 0, total_opening + 100000000)])
            for batch, quantity in enumerate(HISTORY_QUANTITIES):
                day = base_date - timedelta(days=84 - batch * 14)
                self._at = f"{day.isoformat()}T08:00:00+00:00"
                sale = self._sales_create(conn, {"customer_id": CUSTOMERS[batch + 1]["id"], "product_id": 1, "quantity": quantity, "due_date": (day + timedelta(days=14)).isoformat()})
                self._sales_confirm(conn, {"id": sale["id"]})
                grouped = {i: [] for i in (1, 2, 3)}
                for part in PARTS:
                    supplier_id = (1 if batch % 2 == 0 else 3) if part["id"] == 1 else 1 + (part["id"] + batch) % 3
                    contract = _one(conn, "SELECT * FROM supplier_parts WHERE supplier_id=? AND part_id=?", (supplier_id, part["id"]))
                    factor = Decimal("0.96") + Decimal("0.012") * batch
                    price = int((contract["contract_price_fen"] * factor).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
                    grouped[supplier_id].append({"part_id": part["id"], "quantity": part["bom_qty"] * quantity, "unit_price": yuan(price)})
                for supplier_id, lines in grouped.items():
                    expected = day + timedelta(days=SUPPLIERS[supplier_id - 1]["lead_days"])
                    order = self._purchase_create(conn, {"supplier_id": supplier_id, "sales_order_id": sale["id"], "expected_date": expected.isoformat(), "lines": lines, "notes": "历史生产批次采购"})
                    self._purchase_update(conn, {"id": order["id"], "status": "confirmed"})
                    received = expected + timedelta(days=1 if supplier_id == 3 and batch % 2 else 0)
                    self._at = f"{received.isoformat()}T08:00:00+00:00"
                    receipt = self._receive(conn, {"id": order["id"], "received_on": received.isoformat(), "items": [{"line_id": line["id"], "quantity": line["quantity"]} for line in order["lines"]]})
                    self._cash(conn, {"kind": "supplier_payment", "order_id": order["id"], "amount": receipt["amount"]})
                    self._at = f"{day.isoformat()}T08:00:00+00:00"
                self._at = f"{(day + timedelta(days=8)).isoformat()}T08:00:00+00:00"
                work = self._production_create(conn, {"sales_order_id": sale["id"]})
                self._production_start(conn, {"id": work["id"]})
                self._production_complete(conn, {"id": work["id"], "quantity": quantity})
                self._at = f"{(day + timedelta(days=10)).isoformat()}T08:00:00+00:00"
                shipment = self._ship(conn, {"id": sale["id"], "quantity": quantity})
                self._cash(conn, {"kind": "customer_receipt", "order_id": sale["id"], "amount": shipment["revenue"]})
            self._at = f"{base_date.isoformat()}T08:00:00+00:00"
            sale = self._sales_create(conn, {"customer_id": 1, "product_id": 1, "quantity": 100, "due_date": (base_date + timedelta(days=7)).isoformat()})
            self._sales_confirm(conn, {"id": sale["id"]})
            for key, value in {"seed_version": "2", "base_date": base_date.isoformat()}.items():
                _insert(conn, "metadata", {"key": key, "value": value})
        finally:
            self._at = None
