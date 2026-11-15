"""
用户后端管理模块：
    通过 dict[用户键, 后端] 存储和拿取对应用户复合后端
"""

import hashlib

from deepagents.backends import CompositeBackend, StoreBackend
from langgraph.config import get_config
from opensandbox import SandboxSync
from opensandbox.config import ConnectionConfigSync
from opensandbox.models.sandboxes import PVC, Volume

from src.agent.backends.custom_opensandbox import OpenSandboxBackend
from src.agent.config import settings
from src.backend.api.schema import UserContext

# 用户后端字典
user_backends: dict[str, CompositeBackend] = {}


def user_key(user_id: str) -> str:
    """
    把用户标识转换为命名空间和沙箱存储卷使用的固定键。

    Args:
        user_id - 原始用户标识
    Returns:
        用户标识的 SHA256 前 24 位十六进制字符串。
    """
    return hashlib.sha256(user_id.encode()).hexdigest()[:24]


def get_user_backend(user_id: str, config=settings) -> CompositeBackend:
    """
    获取用户复合后端：
        default： OpenSandbox
        /persisted-skills/： StoreBackend
        /memories/： StoreBackend


    Args:
        user_id - 工作区所属用户；不使用会话编号划分文件目录
        config - OpenSandbox 地址、密钥和运行镜像配置
    Returns:
        默认使用 OpenSandbox，记忆和持久化技能路由到用户 Store 的 CompositeBackend。
    """
    # 如果已有，直接返回复合文件后端
    if user_id in user_backends:
        return user_backends[user_id]

    # 如果没有，则根据用户id创建opensandbox
    key = user_key(user_id)
    sandbox = SandboxSync.create(
        config.sandbox_image,
        timeout=None,
        connection_config=ConnectionConfigSync(
            domain=config.sandbox_domain,
            api_key=config.sandbox_api_key or None,
            use_server_proxy=True,
        ),
        metadata={
            "project": "erp-agent",
            "user_key": key
        },
        volumes=[
            Volume(name=name, pvc=PVC(claim_name=f"erp-agent-{key}-{name}"), mount_path=f"/{name}")
            for name in ("skills", "data", "analysis", "draft-skills")
        ],
    )
    # 创建复合文件后端
    backend = CompositeBackend(
        default=OpenSandboxBackend(sandbox),
        routes={
            "/memories/": StoreBackend(namespace=lambda _runtime: ("memories", key)),
            "/persisted-skills/": StoreBackend(namespace=lambda _runtime: ("user_skills", key)),
        },
    )
    # 存储复合文件后端
    user_backends[user_id] = backend

    return backend


def get_context(runtime) -> UserContext:
    """
    读取当前用户信息，补齐会话编号。

    Args:
        runtime - LangGraph静态上下文
    Returns:
        当前用户和会话信息，不包含后端管理器等内部资源。
    """
    context = runtime.context or UserContext()
    if not context.thread_id:
        context.thread_id = get_config()["configurable"]["thread_id"]
    return context


def close_backends() -> None:
    """
    关闭进程创建的沙箱，保留用户存储卷并清空后端引用。

    Args:
        无。
    Returns:
        None - 销毁沙箱容器和 SDK 连接，用户工作目录仍保存在 Linux 存储卷中。
    """
    backends = list(user_backends.values())
    user_backends.clear()
    for backend in backends:
        backend.default.close()
