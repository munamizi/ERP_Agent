"""在沙箱中读取供应商报价或普通网页，保存为 JSON 或 Markdown。"""

import argparse
import json
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit
from urllib.request import Request, urlopen

from bs4 import BeautifulSoup
from markdownify import markdownify


def _field(page, name: str) -> str:
    """读取模拟报价页中一个已标识的字段，缺失时直接报错。"""
    return page.select_one(f'[data-field="{name}"]').get_text(strip=True)


def fetch_page(url: str, mode: str = "markdown", expected_model: str = "", base_url: str = "") -> dict:
    """
    抓取网页正文，或提取模拟供应商站的结构化报价。

    Args:
        url - Agent 报价映射或搜索核实的原网页地址
        mode - quote 提取报价，markdown 提取普通网页正文
        expected_model - 预期型号，仅报价模式核对
        base_url - 沙箱可访问的报价站地址，填写时替换原 URL 的协议和主机
    Returns:
        含真实来源和抓取时间的报价对象，或 Markdown 正文对象。
    """
    source_url = url
    if base_url:
        source = urlsplit(url)
        base = urlsplit(base_url)
        url = urlunsplit((base.scheme, base.netloc, source.path, source.query, ""))
    request = Request(url, headers={"User-Agent": "ERP-Agent/1.0"})
    with urlopen(request, timeout=20) as response:
        page = BeautifulSoup(response.read(), "html.parser")

    if mode == "markdown":
        for element in page.select("script,style,nav"):
            element.decompose()
        return {"source_url": source_url, "fetched_url": url,
                "markdown": markdownify(str(page.select_one("article") or page.body or page)),
                "fetched_at": datetime.now().isoformat(timespec="seconds")}

    article = page.select_one("article[data-part-code]")
    if article is None:
        raise ValueError("页面不是模拟供应商结构化报价，请改用 markdown 模式阅读")
    model = _field(article, "model")
    return {
        "supplier_id": int(article["data-supplier-id"]),
        "supplier_name": page.select_one("header h1").get_text(strip=True),
        "part_code": article["data-part-code"], "model": model,
        "model_matches": not expected_model or model == expected_model,
        "unit_price": _field(article, "unit-price"), "currency": _field(article, "currency"),
        "tax": _field(article, "tax"), "minimum_quantity": int(_field(article, "minimum-quantity")),
        "stock": int(_field(article, "stock")), "lead_days": int(_field(article, "lead-days")),
        "freight": _field(article, "freight"),
        "price_tiers": [{"quantity": int(_field(row, "tier-quantity")), "unit_price": _field(row, "tier-price")}
                        for row in article.select('[data-field="price-tiers"] tbody tr')],
        "updated_at": _field(article, "updated-at"), "valid_until": _field(article, "valid-until"),
        "source_url": source_url, "fetched_url": url, "fetched_at": datetime.now().isoformat(timespec="seconds"),
    }


def main() -> None:
    """
    读取命令行抓取参数，将网页结果保存到指定文件并打印文件路径。

    Args:
        无。
    Returns:
        None - 写入报价 JSON 或 Markdown 文件，失败时抛出异常。
    """
    parser = argparse.ArgumentParser(description="抓取供应商报价或普通网页")
    parser.add_argument("--url", required=True)
    parser.add_argument("--format", choices=["quote", "markdown"], default="markdown")
    parser.add_argument("--expected-model", default="")
    parser.add_argument("--base-url", default="")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    result = fetch_page(args.url, args.format, args.expected_model, args.base_url)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    content = result["markdown"] if args.format == "markdown" else json.dumps(result, ensure_ascii=False, indent=2)
    if args.format == "markdown":
        content = f"来源：{result['source_url']}\n抓取地址：{result['fetched_url']}\n抓取时间：{result['fetched_at']}\n\n{content}"
    output.write_text(content, encoding="utf-8")
    print(json.dumps({"path": str(output), "source_url": result["source_url"], "fetched_at": result["fetched_at"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
