"""可选的智谱 Web 搜索工具。"""

import httpx
from langchain_core.tools import tool

from src.agent.config import settings


@tool(description=(
    "查询供应商背景或其他外部资料。query 为搜索问题或关键词；返回搜索结果，未配置搜索服务密钥时返回未启用提示。"
    "供应商报价应以沙箱抓取脚本读取的原网页为准。"
))
async def web_search(query: str) -> dict:
    """
    使用智谱搜索查询供应商背景及外部资料，报价仍应读取供应商原网页。

    Args:
        query - 搜索问题或关键词
    Returns:
        搜索服务返回的结果；未配置密钥时说明该功能未启用。
    """
    if not settings.zhipu_api_key:
        return {"enabled": False, "message": "未配置 ZHIPU_API_KEY；模拟供应商报价网址可从 Agent 自有技能映射中查找。"}
    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.post(
            "https://open.bigmodel.cn/api/paas/v4/web_search",
            headers={"Authorization": f"Bearer {settings.zhipu_api_key}"},
            json={"search_engine": "search_std", "search_query": query, "count": 5},
        )
    response.raise_for_status()
    return response.json()
