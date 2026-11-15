"""一些规定的接口参数契约"""

import json
from dataclasses import dataclass
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    """用户消息请求体 """
    user_id: str = "local-user"
    username: str = "本机用户"
    thread_id: str = Field(default_factory=lambda: str(uuid4()))
    message: str = Field(min_length=1)


@dataclass
class UserContext:
    """用户信息"""
    user_id: str = "local-user"
    username: str = "本机用户"
    thread_id: str = ""


class ResumeRequest(BaseModel):
    """恢复等待补充信息或审批的会话，reply 是文本、字段或审批字典。"""
    user_id: str = "local-user"
    username: str = "本机用户"
    thread_id: str
    reply: Any


class SSEEvent(BaseModel):
    """
    SSEEvent.encode组装SSE响应数据流
        事件类型：
            session - 对话建立
                token - 模型token输出
                tool - 工具
                interrupt - 中断
            done - 对话完成
            error - 对话错误
    """
    event: Literal["session", "token", "tool", "interrupt", "done", "error"]
    data: dict

    def encode(self) -> str:
        return f"event: {self.event}\ndata: {json.dumps(self.data, ensure_ascii=False, default=str)}\n\n"