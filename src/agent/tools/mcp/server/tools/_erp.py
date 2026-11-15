""" MCP 工具共用的 ERP HTTP 请求 """

from uuid import uuid4

import httpx

from src.agent.config import settings


async def _request(
        method: str,
        path: str,
        *,
        params: dict | None = None,
        body: dict | None = None,
        request_key: str = ""
) -> dict:
    """按读写权限调用 ERP，保留业务错误结构和同次操作的请求键。"""
    token = settings.erp_read_token if method == "GET" else settings.erp_buyer_token
    headers = {"Authorization": f"Bearer {token}"}
    if method != "GET":
        headers["Idempotency-Key"] = request_key or str(uuid4())

    async with httpx.AsyncClient(base_url=settings.erp_url, timeout=15) as client:
        response = await client.request(method, path, params={k: v for k, v in (params or {}).items() if v is not None}, json=body, headers=headers)

    return response.json()
