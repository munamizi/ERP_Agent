"""
对话 APIs：
    chat_stream - 发送用户消息给Agent流式输出。
    chat_resume - 恢复等待补充信息或审批的会话。
"""

import asyncio

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from langchain_core.messages import AIMessage, ToolMessage
from langgraph.types import Command

from src.backend.api.schema import ChatRequest, UserContext, ResumeRequest, SSEEvent

router = APIRouter(prefix="/api/chat", tags=["对话"])


def _event(event, **data):
    """把事件名称和数据编码为前端接收的 SSE 文本。"""
    return SSEEvent(event=event, data=data).encode()


@router.post("/stream")
async def chat_stream(chat_request: ChatRequest, request: Request):
    """
    用户发送消息接口
        发送用户消息，流式输出主 Agent、子 Agent、工具和中断事件。

    Args:
        chat_request - 用户id、会话id、用户消息内容
        request - HTTP 请求
    Returns:
        _response(
        HTTP请求,
        用户消息请求体,
        消息列表,
        消息文本,
        )
    """
    return await _response(
        request,
        chat_request,
        {"messages": [{"role": "user", "content": chat_request.message}]},
        chat_request.message
    )


@router.post("/resume")
async def chat_resume(body: ResumeRequest, request: Request):
    """
    恢复等待补充信息或审批的会话。

    Args:
        body - 原用户与会话编号；reply 为补充文本或 decisions 审批字典
        request - 提供应用内 AgentLoader 的 HTTP 请求
    Returns:
        从原检查点继续执行的 SSE 响应，不新建对话任务。
    """
    return await _response(
        request,
        body,
        Command(resume=body.reply),
        "恢复采购任务",
        resume=True
    )


async def _response(
        request,
        body,
        messages,
        title,
        resume=False
):
    """
    在发送 SSE 前检查服务配置、会话占用和中断状态。

    """
    # 获取Agent管理器
    loader = request.app.state.loader
    # 获取用户信息
    context = UserContext(user_id=body.user_id, username=body.username, thread_id=body.thread_id)
    if loader.thread_lock(body.user_id, body.thread_id).locked():
        raise HTTPException(409, "该会话正在执行，请等待本轮结束")
    try:
        # 获得该用户Agent
        agent = await loader.get_agent(context)
    except Exception as error:
        raise HTTPException(503, str(error)) from error

    # 获取该用户Agent的state
    state = await agent.aget_state(loader.thread_config(body.user_id, body.thread_id))

    # 如果当前用户Agent状态没有问题，流式输出
    pending = bool(state.interrupts)
    if resume and not pending:
        raise HTTPException(409, "当前会话没有等待恢复的任务")
    if not resume and pending:
        raise HTTPException(409, "请先通过 resume 补充信息或处理审批")
    return StreamingResponse(
        _stream(loader, agent, context, messages, title),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
    )


async def _stream(
        loader,
        agent,
        context,
        messages,
        title
):
    """
    流式输出生成器：
        1.将 Agent 流式输出分流并转换成 SSE响应输出
        2.更新 MongoDB会话文档信息
    """
    config = loader.thread_config(context.user_id, context.thread_id)
    lock = loader.thread_lock(context.user_id, context.thread_id)
    async with (lock):
        # 发送对话建立SSE数据session
        yield _event(
            "session",
            thread_id=context.thread_id,
            user_id=context.user_id
        )
        # 更新会话状态
        await loader.save_session(context.user_id, context.thread_id, title, "running")

        # 根据Agent的输出情况，分流向前端发送不同类型的SSE响应数据：token、interrupt、tool
        interrupted, pending = False, {}
        try:
            async for chunk in agent.astream(
                input=messages,
                stream_mode=["messages", "updates"],
                config=config,
                context=context,
                subgraphs=True,
                version="v2",
            ):
                source = "/".join(chunk["ns"]) or "main"

                if chunk["type"] == "messages":
                    message, metadata = chunk["data"]
                    if metadata.get("langgraph_node") == "model" and isinstance(message, AIMessage) and message.text:
                        yield _event(
                            "token",
                            text=message.text,
                            source=source
                        )
                    continue

                if chunk["type"] != "updates":
                    continue
                for node, update in chunk["data"].items():
                    if node == "__interrupt__":
                        interrupted = True
                        for item in update:
                            if item.id in pending:
                                continue
                            pending[item.id] = {
                                "id": item.id,
                                "value": item.value
                            }
                            yield _event(
                                "interrupt",
                                id=item.id,
                                value=item.value,
                                source=source
                            )
                        continue
                    if not isinstance(update, dict):
                        continue
                    for message in update.get("messages", []):
                        if isinstance(message, AIMessage):
                            for call in message.tool_calls:
                                yield _event(
                                    "tool",
                                    status="calling",
                                    id=call["id"],
                                    name=call["name"],
                                    args=call["args"],
                                    source=source,
                                )
                        elif isinstance(message, ToolMessage):
                            yield _event(
                                "tool",
                                status=message.status,
                                id=message.tool_call_id,
                                name=message.name,
                                result=message.content,
                                source=source,
                            )

            state = await agent.aget_state(config)
            answer = next((message.text for message in reversed(state.values.get("messages", [])) \
                if isinstance(message, AIMessage) and not message.tool_calls), "") \
                if not interrupted else ""
            status = "interrupted" if interrupted else "completed"

            # 更新会话信息
            await loader.save_session(
                context.user_id,
                context.thread_id,
                title,
                status,
                state.values.get("messages", []),
                list(pending.values())
            )
            # 本次对话结束，发送对话完成SSE响应
            yield _event(
                "done",
                thread_id=context.thread_id,
                status=status,
                answer=answer
            )
        except asyncio.CancelledError:
            await loader.save_session(context.user_id, context.thread_id, title, "interrupted")
            raise
        except Exception as error:
            # 流已经开始后无法再改 HTTP 状态，错误通过 SSE 明确交给客户端。
            await loader.save_session(context.user_id, context.thread_id, title, "error")
            yield _event(
                "error",
                message=str(error)
            )