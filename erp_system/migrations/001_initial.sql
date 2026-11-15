CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE suppliers (
 id INTEGER PRIMARY KEY, code TEXT UNIQUE NOT NULL, name TEXT NOT NULL, city TEXT NOT NULL,
 qualified INTEGER NOT NULL CHECK(qualified IN (0,1)), rating TEXT NOT NULL,
 lead_days INTEGER NOT NULL, payment_terms TEXT NOT NULL, contact TEXT NOT NULL, phone TEXT NOT NULL,
 description TEXT NOT NULL
);
CREATE TABLE parts (
 id INTEGER PRIMARY KEY, code TEXT UNIQUE NOT NULL, name TEXT NOT NULL, model TEXT NOT NULL,
 category TEXT NOT NULL, specs TEXT NOT NULL, unit TEXT NOT NULL, aliases TEXT NOT NULL,
 safety_stock INTEGER NOT NULL CHECK(safety_stock>=0)
);
CREATE TABLE supplier_parts (
 supplier_id INTEGER REFERENCES suppliers(id), part_id INTEGER REFERENCES parts(id),
 contract_price_fen INTEGER NOT NULL CHECK(contract_price_fen>0), minimum_qty INTEGER NOT NULL CHECK(minimum_qty>0),
 lead_days INTEGER NOT NULL, PRIMARY KEY(supplier_id,part_id)
);
CREATE TABLE products (
 id INTEGER PRIMARY KEY, code TEXT UNIQUE NOT NULL, name TEXT NOT NULL, sale_price_fen INTEGER NOT NULL,
 labor_fen INTEGER NOT NULL, overhead_fen INTEGER NOT NULL
);
CREATE TABLE bom (
 product_id INTEGER REFERENCES products(id), part_id INTEGER REFERENCES parts(id),
 quantity INTEGER NOT NULL CHECK(quantity>0), PRIMARY KEY(product_id,part_id)
);
CREATE TABLE customers (id INTEGER PRIMARY KEY, name TEXT NOT NULL, contact TEXT NOT NULL);
CREATE TABLE inventory (
 part_id INTEGER PRIMARY KEY REFERENCES parts(id), on_hand INTEGER NOT NULL CHECK(on_hand>=0),
 reserved INTEGER NOT NULL DEFAULT 0 CHECK(reserved>=0 AND reserved<=on_hand),
 value_fen INTEGER NOT NULL CHECK(value_fen>=0)
);
CREATE TABLE sales_orders (
 id INTEGER PRIMARY KEY AUTOINCREMENT, number TEXT UNIQUE, customer_id INTEGER NOT NULL REFERENCES customers(id),
 product_id INTEGER NOT NULL REFERENCES products(id), quantity INTEGER NOT NULL CHECK(quantity>0),
 unit_price_fen INTEGER NOT NULL CHECK(unit_price_fen>0), due_date TEXT NOT NULL,
 status TEXT NOT NULL, bom_snapshot TEXT NOT NULL, labor_fen INTEGER NOT NULL, overhead_fen INTEGER NOT NULL,
 created_at TEXT NOT NULL, shipped_qty INTEGER NOT NULL DEFAULT 0 CHECK(shipped_qty>=0 AND shipped_qty<=quantity)
);
CREATE TABLE reservations (
 sales_order_id INTEGER REFERENCES sales_orders(id), part_id INTEGER REFERENCES parts(id),
 quantity INTEGER NOT NULL CHECK(quantity>=0), PRIMARY KEY(sales_order_id,part_id)
);
CREATE TABLE purchase_orders (
 id INTEGER PRIMARY KEY AUTOINCREMENT, number TEXT UNIQUE, supplier_id INTEGER NOT NULL REFERENCES suppliers(id),
 sales_order_id INTEGER REFERENCES sales_orders(id), status TEXT NOT NULL,
 expected_date TEXT NOT NULL, freight_fen INTEGER NOT NULL CHECK(freight_fen>=0),
 freight_received_fen INTEGER NOT NULL DEFAULT 0, notes TEXT NOT NULL,
 created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE purchase_lines (
 id INTEGER PRIMARY KEY AUTOINCREMENT, order_id INTEGER NOT NULL REFERENCES purchase_orders(id),
 part_id INTEGER NOT NULL REFERENCES parts(id), quantity INTEGER NOT NULL CHECK(quantity>0),
 unit_price_fen INTEGER NOT NULL CHECK(unit_price_fen>0),
 received_qty INTEGER NOT NULL DEFAULT 0 CHECK(received_qty>=0 AND received_qty<=quantity),
 UNIQUE(order_id,part_id)
);
CREATE TABLE goods_receipts (
 id INTEGER PRIMARY KEY AUTOINCREMENT, number TEXT UNIQUE, order_id INTEGER NOT NULL REFERENCES purchase_orders(id),
 received_on TEXT NOT NULL, amount_fen INTEGER NOT NULL CHECK(amount_fen>0)
);
CREATE TABLE receipt_lines (
 id INTEGER PRIMARY KEY AUTOINCREMENT, receipt_id INTEGER REFERENCES goods_receipts(id),
 purchase_line_id INTEGER REFERENCES purchase_lines(id), quantity INTEGER NOT NULL CHECK(quantity>0),
 cost_fen INTEGER NOT NULL CHECK(cost_fen>=0)
);
CREATE TABLE inventory_movements (
 id INTEGER PRIMARY KEY AUTOINCREMENT, part_id INTEGER REFERENCES parts(id), quantity_delta INTEGER NOT NULL,
 value_delta_fen INTEGER NOT NULL, on_hand_after INTEGER NOT NULL, value_after_fen INTEGER NOT NULL,
 kind TEXT NOT NULL, reference_id INTEGER NOT NULL, occurred_at TEXT NOT NULL
);
CREATE TABLE production_orders (
 id INTEGER PRIMARY KEY AUTOINCREMENT, number TEXT UNIQUE, sales_order_id INTEGER UNIQUE NOT NULL REFERENCES sales_orders(id),
 quantity INTEGER NOT NULL CHECK(quantity>0), status TEXT NOT NULL,
 completed_qty INTEGER NOT NULL DEFAULT 0 CHECK(completed_qty>=0 AND completed_qty<=quantity),
 material_cost_fen INTEGER NOT NULL DEFAULT 0, allocated_material_fen INTEGER NOT NULL DEFAULT 0,
 created_at TEXT NOT NULL
);
CREATE TABLE production_completions (
 id INTEGER PRIMARY KEY AUTOINCREMENT, production_id INTEGER REFERENCES production_orders(id),
 quantity INTEGER NOT NULL CHECK(quantity>0), material_fen INTEGER NOT NULL,
 labor_fen INTEGER NOT NULL, overhead_fen INTEGER NOT NULL, total_fen INTEGER NOT NULL,
 occurred_at TEXT NOT NULL
);
CREATE TABLE finished_inventory (
 product_id INTEGER PRIMARY KEY REFERENCES products(id), quantity INTEGER NOT NULL CHECK(quantity>=0),
 value_fen INTEGER NOT NULL CHECK(value_fen>=0)
);
CREATE TABLE shipments (
 id INTEGER PRIMARY KEY AUTOINCREMENT, number TEXT UNIQUE, sales_order_id INTEGER REFERENCES sales_orders(id),
 quantity INTEGER NOT NULL CHECK(quantity>0), revenue_fen INTEGER NOT NULL, cost_fen INTEGER NOT NULL,
 occurred_at TEXT NOT NULL
);
CREATE TABLE journals (
 id INTEGER PRIMARY KEY AUTOINCREMENT, number TEXT UNIQUE, source_kind TEXT NOT NULL,
 source_id INTEGER NOT NULL, description TEXT NOT NULL, occurred_at TEXT NOT NULL,
 UNIQUE(source_kind,source_id)
);
CREATE TABLE journal_lines (
 id INTEGER PRIMARY KEY AUTOINCREMENT, journal_id INTEGER REFERENCES journals(id),
 account TEXT NOT NULL, debit_fen INTEGER NOT NULL CHECK(debit_fen>=0),
 credit_fen INTEGER NOT NULL CHECK(credit_fen>=0), CHECK(debit_fen=0 OR credit_fen=0)
);
CREATE TABLE cash_transactions (
 id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT NOT NULL, order_id INTEGER NOT NULL,
 amount_fen INTEGER NOT NULL CHECK(amount_fen>0), occurred_at TEXT NOT NULL
);
CREATE TABLE idempotency (
 scope TEXT NOT NULL, key TEXT NOT NULL, payload_hash TEXT NOT NULL, response TEXT NOT NULL,
 PRIMARY KEY(scope,key)
);
CREATE TABLE audit_logs (
 id INTEGER PRIMARY KEY AUTOINCREMENT, actor TEXT NOT NULL, action TEXT NOT NULL,
 payload TEXT NOT NULL, occurred_at TEXT NOT NULL
);
CREATE INDEX ix_purchase_lines_part ON purchase_lines(part_id);
CREATE INDEX ix_purchase_orders_status ON purchase_orders(status);
CREATE INDEX ix_movements_part ON inventory_movements(part_id,id);
CREATE INDEX ix_sales_status ON sales_orders(status);
