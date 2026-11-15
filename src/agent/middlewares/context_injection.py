from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import SystemMessage

from src.agent.backends.user_backend import get_context, user_key


class ContextInjectionMiddleware(AgentMiddleware):
    """ 每次模型调用读取当前用户偏好注入提示词中 """

    async def awrap_model_call(self, request, handler):
        """
        从当前用户的 Store 读取偏好正文，随用户身份注入本次系统提示词。

        Args:
            request - 包含系统提示、用户上下文和 Store 的模型请求
            handler - 执行后续中间件和模型调用的异步函数
        Returns:
            使用最新偏好后得到的模型响应，不修改 Store 和历史消息。
        """
        context = get_context(request.runtime)
        namespace = ("memories", user_key(context.user_id))
        item = await request.runtime.store.aget(namespace, "/preferences.md")
        preferences = item.value["content"] if item else "尚未保存个人偏好"
        note = (
            f"\n当前用户：{context.username}；user_id={context.user_id}。\n"
            "个人偏好文件：/memories/preferences.md。\n"
            f"用户偏好（当前明确要求优先）：\n{preferences}\n"
        )
        system_prompt = request.system_message.text if request.system_message else ""
        prompt = system_prompt + note
        return await handler(request.override(system_message=SystemMessage(content=prompt)))
