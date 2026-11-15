"""Agent 全局配置"""

import json
import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[2]


@dataclass
class AgentSettings:
    """Agent配置"""

    model: str = "deepseek-flash"
    api_key: str = ""
    base_url: str = "https://api.deepseek.com"
    erp_url: str = "http://127.0.0.1:8001"
    erp_read_token: str = "demo-read-token"
    erp_buyer_token: str = "demo-buyer-token"
    mcp_url: str = "http://127.0.0.1:8000/mcp"
    extra_mcp_servers: dict | None = None
    mongodb_uri: str = ""
    mongodb_database: str = "erp_agent"
    sandbox_domain: str = "192.168.100.135:8090"
    sandbox_api_key: str = ""
    sandbox_image: str = "erp-agent-sandbox:py313"
    sandbox_supplier_url: str = ""  # 沙箱能访问的报价站地址，用于替换 localhost
    download_root: Path = PROJECT_ROOT / ".runtime/agent-downloads"
    skills_root: Path = PROJECT_ROOT / "src/agent/skills"
    api_url: str = "http://127.0.0.1:8003"
    zhipu_api_key: str = ""
    model_call_limit: int = 30
    tool_call_limit: int = 60

    @classmethod
    def from_env(cls) -> "AgentSettings":
        """
        读取 .env 和环境变量，生成模型、ERP、存储及文件配置。

        Args:
            无。
        Returns:
            可供 Agent、MCP 服务和对话 API 共用的配置对象。
        """
        load_dotenv(PROJECT_ROOT / "src/.env", encoding="utf-8-sig")
        return cls(
            model=os.getenv("AGENT_MODEL", "deepseek-flash"),
            api_key=os.getenv("DEEPSEEK_API_KEY", ""),
            base_url=os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
            erp_url=os.getenv("ERP_BASE_URL", "http://127.0.0.1:8001"),
            erp_read_token=os.getenv("ERP_READ_TOKEN", "demo-read-token"),
            erp_buyer_token=os.getenv("ERP_BUYER_TOKEN", "demo-buyer-token"),
            mcp_url=os.getenv("ERP_MCP_URL", "http://127.0.0.1:8000/mcp"),
            extra_mcp_servers=json.loads(os.getenv("EXTRA_MCP_SERVERS", "{}")),
            mongodb_uri=os.getenv("MONGODB_URI", ""),
            mongodb_database=os.getenv("MONGODB_DATABASE", "erp_agent"),
            sandbox_domain=os.getenv("OPENSANDBOX_DOMAIN", "192.168.100.135:8090"),
            sandbox_api_key=os.getenv("OPENSANDBOX_API_KEY", ""),
            sandbox_image=os.getenv("OPENSANDBOX_IMAGE", "erp-agent-sandbox:py313"),
            sandbox_supplier_url=os.getenv("SUPPLIER_SANDBOX_BASE_URL", ""),
            download_root=PROJECT_ROOT / os.getenv("AGENT_DOWNLOAD_ROOT", ".runtime/agent-downloads"),
            api_url=os.getenv("AGENT_API_URL", "http://127.0.0.1:8003"),
            zhipu_api_key=os.getenv("ZHIPU_API_KEY", ""),
            model_call_limit=int(os.getenv("AGENT_MODEL_CALL_LIMIT", "30")),
            tool_call_limit=int(os.getenv("AGENT_TOOL_CALL_LIMIT", "60")),
        )


settings = AgentSettings.from_env()
