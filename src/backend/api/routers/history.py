"""
会话管理 APIs：
    sessions - 获取用户会话列表
    session_messages - 读取会话消息
    delete_session - 删除某一会话
"""

from fastapi import APIRouter, HTTPException, Request

router = APIRouter(prefix="/api/history", tags=["历史会话"])


@router.get("")
async def sessions(request: Request, user_id: str = "local-user"):
    """
    获取当前用户的会话列表。

    Args:
        request - HTTP 请求
        user_id - 用户id
    Returns:
        会话列表（含 thread_id、title、status、updated_at）
    """
    items = await request.app.state.loader.session_repo.list_sessions(user_id)
    return {
        "items": items
    }


@router.get("/{thread_id}")
async def session_messages(thread_id: str, request: Request, user_id: str = "local-user"):
    """
    读取会话消息。

    Args:
        thread_id - 会话id
        request - HTTP 请求
        user_id - 用户id
    Returns:
        已保存的主会话消息、工具调用信息和待处理中断。
    """
    loader = request.app.state.loader
    item = await loader.session_repo.get(user_id, thread_id)
    if item is None:
        raise HTTPException(404, "会话不存在")
    # 使用展示副本，历史查询无需重新加载模型、MCP 或沙箱。
    return {
        "thread_id": thread_id,
        "messages": item["messages"],
        "interrupts": item["interrupts"]
    }


@router.delete("/{thread_id}")
async def delete_session(thread_id: str, request: Request, user_id: str = "local-user"):
    """
    删除会话，保留已生成的本地报告文件。

    Args:
        thread_id - 会话id
        request - HTTP 请求
        user_id - 用户id
    Returns:
        deleted 会话编号；执行中的会话返回 409。
    """
    loader = request.app.state.loader
    lock = loader.thread_lock(user_id, thread_id)
    if lock.locked():
        raise HTTPException(409, "请等待该会话执行结束后再删除")
    async with lock:
        await loader.checkpointer.adelete_thread(loader.thread_config(user_id, thread_id)["configurable"]["thread_id"])
        await loader.session_repo.delete(user_id, thread_id)
    return {
        "deleted": thread_id
    }
