import {api, getToken, setToken} from "./api.js";

let _view = "sales", _state = {}, _busy = false;
const _titles = {sales:"销售订单与 BOM",inventory:"物料与库存",purchase:"采购管理",production:"生产与交付",finance:"基础财务"};
const _statuses = {draft:"草稿",confirmed:"已确认",partially_received:"部分收货",received:"全部收货",cancelled:"已取消",in_progress:"生产中",in_production:"生产中",partially_completed:"部分完工",completed:"已完工",ready_to_ship:"待发货",shipped:"已发货"};

// 对接口文本编码，避免单据备注等内容被作为 HTML 执行。
function _esc(value) { return String(value ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c])); }
// 将已编码的单元格组织成基础表格。
function _table(headers, rows) { return '<div class="table-wrap"><table><thead><tr>' + headers.map(h => "<th>" + _esc(h) + "</th>").join("") + "</tr></thead><tbody>" + (rows.length ? rows.map(row => "<tr>" + row.map(c => "<td>" + c + "</td>").join("") + "</tr>").join("") : '<tr><td colspan="' + headers.length + '">暂无记录</td></tr>') + "</tbody></table></div>"; }
// 生成业务按钮，业务编号通过固定的 data 属性传递。
function _button(action, id, label) { return '<button data-action="' + action + '" data-id="' + id + '">' + label + "</button>"; }
// 生成下拉选项，展示名称与编号。
function _options(items, label = "name") { return items.map(i => '<option value="' + i.id + '">' + _esc(i[label]) + " [" + i.id + "]</option>").join(""); }
// 显示操作反馈。
function _message(text, error = false) { const node = document.querySelector("#message"); node.textContent = text; node.className = error ? "error" : "success"; }
// 判断当前角色是否具有管理员业务操作权限。
function _admin() { return _state.role === "admin"; }
// 判断当前角色是否具有采购写入权限。
function _buyer() { return _state.role === "buyer" || _admin(); }

// 重新读取各业务模块，所有写入后的页面展示均采用服务端返回数据。
async function _load() {
    const paths = ["/session","/customers","/products","/parts?page_size=100","/suppliers/search","/sales-orders?page_size=100","/orders/search/details?page_size=100","/production-orders?page_size=100","/finance/summary","/inventory/finished"];
    const data = await Promise.all(paths.map(path => api(path)));
    _state = {role:data[0].role,customers:data[1].items,products:data[2].items,parts:data[3].items,suppliers:data[4].items,sales:data[5].items,orders:data[6].items,works:data[7].items,finance:data[8],finished:data[9].items};
    document.querySelector("#role").textContent = {admin:"管理员",buyer:"采购员",read:"只读"}[_state.role];
    _render();
}

// 展示销售单和固定版本的产品 BOM。
function _sales() {
    const rows = _state.sales.map(s => [_esc(s.number),_esc(s.customer_name),s.quantity,_esc(s.total),_esc(s.due_date),_esc(_statuses[s.status]),s.shipped_qty,_esc(s.gross_profit),(s.status === "confirmed" ? _button("sale-materials",s.id,"物料需求") : "") + (_admin() && s.status === "draft" ? _button("confirm-sale",s.id,"确认") : "") + (_admin() && ["draft","confirmed"].includes(s.status) ? _button("cancel-sale",s.id,"取消") : "")]);
    return "<section><h3>销售订单</h3>" + (_admin() ? _button("new-sale",0,"新建销售订单") : "") + _table(["单号","客户","数量","合同金额","交期","状态","已发货","已确认毛利","操作"],rows) + "</section><section><h3>凌云 Pro16 配方 · 每台</h3>" + _table(["零件","型号","用量","单位"],_state.products[0].bom.map(b => [_esc(b.name),_esc(b.model),b.quantity,_esc(b.unit)])) + "<p>单位人工费 ¥" + _esc(_state.products[0].labor) + "；单位制造费用 ¥" + _esc(_state.products[0].overhead) + "。销售单创建时保存配方与费用快照。</p></section>";
}

// 展示原材料状态与可独立访问的供应商报价链接。
function _inventory() {
    return "<section><h3>原材料库存</h3>" + _table(["零件/型号","现存","占用","可用","采购在途","平均成本","安全库存","供应商报价"],_state.parts.map(p => [_esc(p.name) + "<br><small>" + _esc(p.model) + "</small>",p.on_hand,p.reserved,p.available,p.inbound,_esc(p.average_cost),p.safety_stock,p.suppliers.map(s => '<a target="_blank" rel="noopener" href="' + _esc(s.price_url) + '">' + _esc(s.supplier_name) + (s.qualified ? "" : "（待审核）") + "</a>").join("<br>")])) + "</section>";
}

// 展示采购单；仅符合业务状态和当前权限的操作提供按钮。
function _purchase() {
    return "<section><h3>采购单</h3>" + (_buyer() ? _button("new-order",0,"新建采购单") : "") + _table(["采购单","供应商","物料","数量/已收","金额","预计到货","状态","操作"],_state.orders.map(o => [_esc(o.number),_esc(o.supplier_name),o.lines.map(l => _esc(l.name)).join("<br>"),o.lines.map(l => l.quantity + " / " + l.received_qty).join("<br>"),_esc(o.total),_esc(o.expected_date),_esc(_statuses[o.status]),(_buyer() && o.status === "draft" ? _button("edit-order",o.id,"修改") + _button("confirm-order",o.id,"确认") : "") + (_buyer() && ["draft","confirmed"].includes(o.status) ? _button("cancel-order",o.id,"取消") : "") + (_admin() && ["confirmed","partially_received"].includes(o.status) ? _button("receive-order",o.id,"收货") : "")])) + "</section>";
}

// 展示生产工单、可发货订单和当前成品库存。
function _production() {
    const candidates = _state.sales.filter(s => s.status === "confirmed" && !_state.works.some(w => w.sales_order_id === s.id));
    return "<section><h3>生产工单</h3>" + (_admin() ? candidates.map(s => _button("new-work",s.id,"为 " + _esc(s.number) + " 建工单")).join("") : "") + _table(["工单","销售单","计划数量","已完工","状态","已领材料成本","完工成本","操作"],_state.works.map(w => [_esc(w.number),_esc(w.sales_order_number),w.quantity,w.completed_qty,_esc(_statuses[w.status]),_esc(w.material_cost),_esc(w.completed_cost),(_admin() && w.status === "draft" ? _button("start-work",w.id,"领料开工") : "") + (_admin() && ["in_progress","partially_completed"].includes(w.status) ? _button("complete-work",w.id,"登记完工") : "")])) + "</section><section><h3>销售发货</h3>" + _table(["销售单","已发货/订购","状态","操作"],_state.sales.filter(s => ["in_production","ready_to_ship"].includes(s.status)).map(s => [_esc(s.number),s.shipped_qty + " / " + s.quantity,_esc(_statuses[s.status]),_admin() ? _button("ship-sale",s.id,"登记发货") : ""])) + "</section><section><h3>成品库存</h3>" + _table(["产品","数量","库存价值"],_state.finished.map(i => [_esc(i.name),i.quantity,_esc(i.value)])) + "</section>";
}

// 展示收支汇总和未结清单据，收付款从对应单据发起。
function _finance() {
    const f = _state.finance;
    const sales = _state.sales.filter(s => Number(s.receivable) > 0);
    const orders = _state.orders.filter(o => Number(o.payable) > 0);
    return "<section><h3>收支概况（含历史业务）</h3><p>收入 ¥" + _esc(f.revenue) + "；销售成本 ¥" + _esc(f.cost) + "；毛利 ¥" + _esc(f.gross_profit) + "。</p></section><section><h3>待收款 · ¥" + _esc(f.receivable) + "</h3>" + _table(["销售单","客户","未收金额","操作"],sales.map(s => [_esc(s.number),_esc(s.customer_name),_esc(s.receivable),_admin() ? _button("receive-cash",s.id,"收款") : ""])) + "</section><section><h3>待付款 · ¥" + _esc(f.payable) + "</h3>" + _table(["采购单","供应商","未付金额","操作"],orders.map(o => [_esc(o.number),_esc(o.supplier_name),_esc(o.payable),_admin() ? _button("pay-cash",o.id,"付款") : ""])) + "</section>";
}

// 根据导航选择渲染页面，不在页面中计算或修改库存。
function _render() {
    document.querySelector("#view-title").textContent = _titles[_view];
    document.querySelectorAll("[data-view]").forEach(b => b.classList.toggle("active",b.dataset.view === _view));
    document.querySelector("#content").innerHTML = ({sales:_sales,inventory:_inventory,purchase:_purchase,production:_production,finance:_finance}[_view])();
}

// 打开带业务动作标识的操作表单。
function _dialog(title, action, id, fields) {
    document.querySelector("#dialog-content").innerHTML = "<h3>" + _esc(title) + '</h3><form id="action-form" data-action="' + action + '" data-id="' + id + '">' + fields + '<button type="submit">提交</button></form>';
    document.querySelector("#action-dialog").showModal();
}

// 生成可编辑的采购物料行。
function _poLine(line = {part_id:1,quantity:1,unit_price:"1500.00"}) {
    const options = _state.parts.map(p => '<option value="' + p.id + '"' + (p.id === line.part_id ? " selected" : "") + ">" + _esc(p.name) + " · " + _esc(p.model) + "</option>").join("");
    return '<div class="po-line"><label>零件<select class="part-id">' + options + '</select></label><label>数量<input class="quantity" type="number" min="1" step="1" required value="' + line.quantity + '"></label><label>成交单价（元）<input class="unit-price" type="number" min="0.01" step="0.01" required value="' + _esc(line.unit_price) + '"></label><button type="button" data-action="remove-line">移除此行</button></div>';
}

// 使用本机日期生成七天后的默认交期，不依赖预置订单。
function _defaultDate() {
    const date = new Date();
    date.setDate(date.getDate() + 7);
    return [date.getFullYear(),String(date.getMonth() + 1).padStart(2,"0"),String(date.getDate()).padStart(2,"0")].join("-");
}

// 根据动作展示对应的操作表单，或提交无需补充数据的动作。
async function _action(action, id) {
    if (action === "new-sale") return _dialog("新建销售订单",action,0,'<label>客户名称<input name="customer_name" list="customer-names" maxlength="200" required placeholder="输入客户名称，也可选择已有客户"></label><datalist id="customer-names">' + _state.customers.map(c => '<option value="' + _esc(c.name) + '"></option>').join("") + '</datalist><label>产品<select name="product_id">' + _options(_state.products) + '</select></label><label>数量<input name="quantity" type="number" min="1" step="1" required value="1"></label><label>单价（元）<input name="unit_price" type="number" min="0.01" step="0.01" required value="' + _esc(_state.products[0].sale_price) + '"></label><label>交期<input name="due_date" type="date" required value="' + _defaultDate() + '"></label>');
    if (action === "sale-materials") {
        const sale = await api("/sales-orders/" + id);
        const plan = sale.mrp;
        if (!plan) throw new Error("只有已确认且尚未开工的订单可以查看物料需求");
        document.querySelector("#dialog-content").innerHTML = "<h3>" + _esc(sale.number) + " · 物料需求</h3><p>客户：" + _esc(sale.customer_name) + "；交期：" + _esc(sale.due_date) + "；" + (plan.ready ? "物料齐套，可以开工" : "物料未齐套") + "</p>" + _table(["零件","需求","已预留","实际缺口","按时在途","建议采购"],plan.items.map(i => [_esc(i.name),i.required,i.reserved_for_order,i.shortage,i.on_time_inbound,i.suggested_purchase_qty]));
        document.querySelector("#action-dialog").showModal();
        return;
    }
    if (action === "new-order" || action === "edit-order") {
        const order = _state.orders.find(o => o.id === id);
        const dateValue = order ? order.expected_date : _defaultDate();
        let fields = order ? "<p>供应商：" + _esc(order.supplier_name) + "</p>" : '<label>供应商<select name="supplier_id">' + _options(_state.suppliers.filter(s => s.qualified)) + '</select></label><label>关联销售单<select name="sales_order_id"><option value="">备库存采购</option>' + _state.sales.filter(s => s.status === "confirmed").map(s => '<option value="' + s.id + '">' + _esc(s.number) + " · " + _esc(s.customer_name) + "</option>").join("") + "</select></label>";
        fields += '<label>预计到货<input name="expected_date" type="date" required value="' + dateValue + '"></label><label>单笔运费（元）<input name="freight" type="number" min="0" step="0.01" required value="' + (order ? order.freight : "80.00") + '"></label><label>备注<input name="notes" value="' + _esc(order ? order.notes : "") + '"></label><div id="po-lines">' + (order ? order.lines : [undefined]).map(_poLine).join("") + '</div><button type="button" data-action="add-line">增加物料行</button>';
        return _dialog(order ? "修改采购草稿" : "新建采购草稿",action,id,fields);
    }
    if (action === "receive-order") {
        const order = _state.orders.find(o => o.id === id);
        return _dialog("采购收货 " + order.number,action,id,order.lines.filter(l => l.received_qty < l.quantity).map(l => '<label>' + _esc(l.name) + "（未收 " + (l.quantity-l.received_qty) + '）<input class="receipt-qty" data-line-id="' + l.id + '" type="number" min="0" max="' + (l.quantity-l.received_qty) + '" step="1" value="' + (l.quantity-l.received_qty) + '"></label>').join(""));
    }
    if (action === "complete-work" || action === "ship-sale") return _dialog(action === "complete-work" ? "登记本次完工" : "登记本次发货",action,id,'<label>本次数量<input name="quantity" type="number" min="1" step="1" required value="1"></label>');
    if (action === "receive-cash" || action === "pay-cash") {
        const receipt = action === "receive-cash";
        const order = (receipt ? _state.sales : _state.orders).find(o => o.id === id);
        const remaining = receipt ? order.receivable : order.payable;
        return _dialog(receipt ? "客户收款" : "供应商付款",action,id,"<p>单据：" + _esc(order.number) + "；" + _esc(receipt ? order.customer_name : order.supplier_name) + "</p><p>尚未结算 ¥" + _esc(remaining) + '</p><label>本次金额（元）<input name="amount" type="number" min="0.01" max="' + _esc(remaining) + '" step="0.01" required value="' + _esc(remaining) + '"></label>');
    }
    const actions = {
        "confirm-sale": ["/sales-orders/" + id + "/confirm","POST",{}],
        "cancel-sale": ["/sales-orders/" + id + "/cancel","POST",{}],
        "confirm-order": ["/orders/update/" + id,"PUT",{status:"confirmed"}],
        "cancel-order": ["/orders/update/" + id,"PUT",{status:"cancelled"}],
        "new-work": ["/production-orders","POST",{sales_order_id:id}],
        "start-work": ["/production-orders/" + id + "/start","POST",{}]
    };
    if (actions[action]) await _write(...actions[action]);
}

// 禁止并发页面提交，完成操作后重新读取业务数据。
async function _write(path, method, body) {
    if (_busy) return;
    _busy = true;
    document.querySelectorAll("button").forEach(b => b.disabled = true);
    try {
        const result = await api(path,{method,body});
        document.querySelector("#action-dialog").close();
        await _load();
        _message("操作成功" + (result.number ? "：" + result.number : ""));
    } finally {
        _busy = false;
        document.querySelectorAll("button").forEach(b => b.disabled = false);
    }
}

// 将表单数据转换为固定的接口请求，业务合法性由后端再次校验。
async function _submit(form) {
    const values = Object.fromEntries(new FormData(form)), action = form.dataset.action, id = Number(form.dataset.id);
    if (["new-order","edit-order"].includes(action)) {
        const lines = [...form.querySelectorAll(".po-line")].map(row => ({part_id:Number(row.querySelector(".part-id").value),quantity:Number(row.querySelector(".quantity").value),unit_price:row.querySelector(".unit-price").value}));
        if (!lines.length) throw new Error("请至少填写一行采购物料");
        const body = {expected_date:values.expected_date,freight:values.freight,notes:values.notes,lines};
        if (action === "new-order") { body.supplier_id = Number(values.supplier_id); if (values.sales_order_id) body.sales_order_id = Number(values.sales_order_id); }
        return _write(action === "new-order" ? "/orders/create" : "/orders/update/" + id,action === "new-order" ? "POST" : "PUT",body);
    }
    if (action === "new-sale") return _write("/sales-orders","POST",{customer_name:values.customer_name.trim(),product_id:Number(values.product_id),quantity:Number(values.quantity),unit_price:values.unit_price,due_date:values.due_date});
    if (action === "receive-order") {
        const items = [...form.querySelectorAll(".receipt-qty")].map(input => ({line_id:Number(input.dataset.lineId),quantity:Number(input.value)})).filter(i => i.quantity > 0);
        if (!items.length) throw new Error("本次至少收货一件物料");
        return _write("/orders/" + id + "/receipts","POST",{items});
    }
    if (action === "complete-work") return _write("/production-orders/" + id + "/completions","POST",{quantity:Number(values.quantity)});
    if (action === "ship-sale") return _write("/sales-orders/" + id + "/shipments","POST",{quantity:Number(values.quantity)});
    if (action === "receive-cash" || action === "pay-cash") return _write("/finance/cash-transactions","POST",{kind:action === "receive-cash" ? "customer_receipt" : "supplier_payment",order_id:id,amount:values.amount});
}

document.querySelector("#token").value = getToken();
document.querySelector("#session-form").addEventListener("submit",async event => { event.preventDefault(); setToken(document.querySelector("#token").value); try { await _load(); _message("连接成功"); } catch(error) { _message(error.message,true); } });
document.querySelector("#refresh").addEventListener("click",async () => { try { await _load(); _message("数据已刷新"); } catch(error) { _message(error.message,true); } });
document.querySelector("#close-dialog").addEventListener("click",() => document.querySelector("#action-dialog").close());
document.addEventListener("click",async event => {
    const button = event.target.closest("button"); if (!button) return;
    if (button.dataset.view && _state.role) { _view = button.dataset.view; _render(); return; }
    if (button.dataset.action === "add-line") { document.querySelector("#po-lines").insertAdjacentHTML("beforeend",_poLine({part_id:4,quantity:1,unit_price:"620.00"})); return; }
    if (button.dataset.action === "remove-line") { button.closest(".po-line").remove(); return; }
    if (button.dataset.action) { try { await _action(button.dataset.action,Number(button.dataset.id)); } catch(error) { _message(error.message,true); } }
});
document.addEventListener("submit",async event => { if (event.target.id !== "action-form") return; event.preventDefault(); try { await _submit(event.target); } catch(error) { _message(error.message,true); } });
try { await _load(); _message("业务数据已加载"); } catch(error) { _message(error.message,true); }
