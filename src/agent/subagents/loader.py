"""子代理 YAML 配置转化"""

from pathlib import Path

import yaml
from deepagents.middleware.summarization import create_summarization_tool_middleware
from langchain.agents.middleware import ModelCallLimitMiddleware, ToolCallLimitMiddleware


def load_subagents(tools: list, model, backend, config) -> list[dict]:
    """
    读取 YAML 子 Agent 配置，按明确工具名分配。

    步骤：
        1. 读取子 Agent 配置中的明确工具名。
        2. 将明确名称解析为实际工具，缺失时直接报错。
        3. 装配模型及调用限制，为分析子 Agent 加入摘要中间件。

    Args:
        tools - ERP、图表、搜索和订单信息工具的完整列表
        model - 主子 Agent 共用的模型
        backend - 当前用户的复合后端，同用户会话共享远端沙箱工作区
        config - 模型及工具调用次数限制
    Returns:
        已解析实际工具、模型和中间件的子 Agent 配置列表。
    """
    tool_index = {current_tool.name: current_tool for current_tool in tools}
    subagents = []
    for path in sorted((Path(__file__).parent / "configs").glob("*.yaml")):
        agent_config = yaml.safe_load(path.read_text(encoding="utf-8"))
        tool_names = agent_config.pop("tools")
        # 精确匹配：配置漏写或拼错时直接报错，不让 Agent 带着缺失能力启动。
        agent_config["tools"] = [tool_index[name] for name in tool_names]
        agent_config["model"] = model
        agent_config["middleware"] = [
            ModelCallLimitMiddleware(run_limit=config.model_call_limit, exit_behavior="end"),
            ToolCallLimitMiddleware(run_limit=config.tool_call_limit, exit_behavior="end"),
        ]
        if agent_config["name"] == "procurement-analyst":
            summarization = create_summarization_tool_middleware(model=model, backend=backend)
            agent_config["middleware"].insert(0, summarization)
        subagents.append(agent_config)
    return subagents
