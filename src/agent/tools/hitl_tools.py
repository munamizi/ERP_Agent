"""人工补充数据工具：request_order_info 中断入口。"""

from langchain_core.tools import tool
from langgraph.types import interrupt


@tool(description=(
    "创建或修改采购单缺少用户决定的信息时，暂停并询问。question 用简短中文说明必要背景与全部待答项，"
    "不复述完整方案、已确认字段或采购历史；有歧义时只澄清冲突部分。missing_fields 仅列未解决字段名。"
    "用户补充后返回其回复，供原任务合并信息继续执行；本工具不代替采购写入审批。"
))
def request_order_info(question: str, missing_fields: list[str]) -> dict:
    """
    暂停当前任务，请用户补充采购单所需的信息。

    Args:
        question - 简短说明必要背景和全部待答项，不重复已确认信息
        missing_fields - 需要用户决定的未解决字段，例如 expected_date、freight
    Returns:
        用户恢复会话时提供的内容；恢复前通过 LangGraph 中断暂停。
    """
    reply = interrupt({"kind": "order_info", "question": question, "missing_fields": missing_fields})
    return reply if isinstance(reply, dict) else {"reply": reply}
