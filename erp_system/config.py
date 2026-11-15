"""ERP 的本地路径、演示权限和服务配置。"""

import os
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _load_env() -> None:
    """读取本地 .env 的简单键值配置，已设置的环境变量优先。"""
    path = ROOT / ".env"
    if path.exists():
        for line in path.read_text(encoding="utf-8-sig").splitlines():
            if line.strip() and not line.lstrip().startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_env()


@dataclass(frozen=True)
class Settings:
    """ERP 配置；令牌默认值仅用于本地演示。"""

    database_path: Path = field(default_factory=lambda: ROOT / os.getenv("ERP_DATABASE_PATH", "erp_system/data/erp.sqlite"))
    read_token: str = field(default_factory=lambda: os.getenv("ERP_READ_TOKEN", "demo-read-token"))
    buyer_token: str = field(default_factory=lambda: os.getenv("ERP_BUYER_TOKEN", "demo-buyer-token"))
    admin_token: str = field(default_factory=lambda: os.getenv("ERP_ADMIN_TOKEN", "demo-admin-token"))
    cors_origins: tuple[str, ...] = field(default_factory=lambda: tuple(os.getenv("ERP_CORS_ORIGINS", "http://localhost:8001,http://127.0.0.1:8001").split(",")))
