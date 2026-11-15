---
name: supplier-price-urls
description: 按电脑物料编码、型号和供应商编号找到模拟报价网页。
---

# 找供应商报价网址

本目录 data/url_mapping.yaml 是 Agent 自行维护的模拟报价网址映射，共 48 条网址；不要求 ERP 返回 price_url 或为 Agent 增加接口。

文件采用 JSON 语法，也兼容 YAML 1.2。mappings 每项包含 part_id、part_code、model、supplier_id、supplier_name、url。

先按物料编号或 part_code 定位，再核对型号与供应商编号。名称只辅助搜索，不把不同规格当同一物料。

通过 execute 在沙箱用 Python 读取 JSON 映射，按 part_code 和 supplier_id 筛选 url，再按照 /skills/procurement/web-scraper/SKILL.md 运行抓取脚本。也可使用通过搜索等方式核实的 url。映射只提供网址，不说明报价有效或供应商已通过准入。

映射中的模拟网址是 http://localhost:8080，远端沙箱的 localhost 不能代表 Windows。按 /AGENTS.md 中的 SUPPLIER_SANDBOX_BASE_URL 使用抓取脚本的 --base-url。只对模拟报价站做地址替换，不替换普通外部网页；原网址作为来源保留。映射缺失时说明缺口，不按模拟站路径猜造真实网址。
