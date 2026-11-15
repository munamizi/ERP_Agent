# 供应商报价站怎么用

`public/` 就是整个网站：一个入口首页、四个供应商目录、48 个报价页和一个公共样式文件。直接维护这些 HTML 和 CSS 就行。

## 打开网站

在项目根目录执行 `uv run python run_demo.py`，ERP 和报价站会一起启动。只想打开报价站时，执行：

```powershell
uv run python -m http.server 8080 --bind 127.0.0.1 --directory supplier_site/public
```

然后访问 `http://localhost:8080`。这里用 Python 自带的文件服务器，只是为了让 Agent 能通过 HTTP 请求读取页面。

## 改一次价格，看看 Agent 能不能读到

以华芯 CPU 为例，打开 `public/huaxin/products/CPU-HX8.html`：

1. 找到 `data-field="unit-price"`，把旁边的 `1490.00` 改成你要测试的价格。
2. 如果阶梯价也变了，再修改下方表格里的 `tier-price`。库存、交期、更新时间和有效期也可以在同一页修改。
3. 保存后，让 Agent 再次请求原来的网址。文件服务器会读取保存后的内容，不用重启；浏览器查看时可强制刷新。

供应商目录 `public/huaxin/index.html` 也显示参考价，想让目录和详情一致，就一起修改。

修改时保留页面路径、物料编号、型号、供应商编号和 `data-field` 属性。它们让 Agent 知道“这是谁的哪种零件”，也方便从 HTML 中提取价格。

48 个网址统一记录在项目根目录的 `src/agent/skills/procurement/supplier-price-urls/data/url_mapping.yaml`，这里不再保存第二份映射。

网页只模拟供应商公布的报价。改了网页，ERP 中的历史成交价和现有采购单不会跟着改变；Agent 需要把选定的成交价明确传给采购接口。
