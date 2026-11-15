"""图表工具封装：统一为 generate_visualization 入口。"""

import json
from uuid import uuid4

import plotly.graph_objects as go
from langchain.tools import ToolRuntime
from langchain_core.tools import tool

from src.agent.backends.user_backend import get_context, get_user_backend
from src.backend.api.schema import UserContext

MCP_CHART_TOOLS = {}


def _remote_chart_reference() -> str:
    """将已连接的远端图表工具参数写成参考文字，排除电子表格等非图表工具。"""
    sections = []
    for name, current_tool in sorted(MCP_CHART_TOOLS.items()):
        if not name.startswith("generate_") or not name.endswith(("_chart", "_map", "_diagram", "_graph")):
            continue
        chart_type = name.removeprefix("generate_").removesuffix("_chart")
        schema = current_tool.args_schema
        if not isinstance(schema, dict):
            schema = schema.model_json_schema()
        sections.append(f"### {chart_type}\n\n```json\n{json.dumps(schema, ensure_ascii=False, indent=2)}\n```")
    if not sections:
        return ""
    return "\n\n## 已连接的远端图表\n\n以下类型优先调用远端服务，chart_config 按对应 schema 填写，不使用上面的 Plotly 格式。\n\n" + "\n\n".join(sections)

# 每种图对应 Plotly 的一种轨迹或默认绘制方式，不另写 26 个工具。
CHART_TYPES = {
    "bar": {"type": "bar"}, "line": {"type": "scatter", "mode": "lines+markers"},
    "area": {"type": "scatter", "mode": "lines", "fill": "tozeroy"},
    "scatter": {"type": "scatter", "mode": "markers"}, "bubble": {"type": "scatter", "mode": "markers"},
    "pie": {"type": "pie"}, "donut": {"type": "pie", "hole": 0.45},
    "histogram": {"type": "histogram"}, "box": {"type": "box"}, "violin": {"type": "violin"},
    "heatmap": {"type": "heatmap"}, "radar": {"type": "scatterpolar", "fill": "toself"},
    "polar": {"type": "scatterpolar", "mode": "markers"},
    "scatter3d": {"type": "scatter3d", "mode": "markers"}, "line3d": {"type": "scatter3d", "mode": "lines"},
    "surface": {"type": "surface"}, "contour": {"type": "contour"}, "waterfall": {"type": "waterfall"},
    "funnel": {"type": "funnel"}, "treemap": {"type": "treemap"}, "sunburst": {"type": "sunburst"},
    "sankey": {"type": "sankey"}, "gauge": {"type": "indicator", "mode": "gauge+number"},
    "table": {"type": "table"}, "parallel_coordinates": {"type": "parcoords"}, "scatter_matrix": {"type": "splom"},
}


@tool(description=(
    "仅在用户要求图表或明确的输出偏好需要图表时使用；普通询价、最低价和少量报价比较直接用文字或小表格，不调用本工具。"
    "chart_type 为 bar、line、pie 等类型；使用内置 Plotly 时 chart_config 包含 data 字典或列表，"
    "可选 title、layout；已接入的远端地图、关系图等使用远端 schema。完整参数先读 /skills/procurement/chart_params.md。"
    "返回图表文件路径或外部图表工具结果。"
))
async def generate_visualization(chart_type: str, chart_config: dict, runtime: ToolRuntime[UserContext]) -> dict:
    """
    生成采购图表；完整参数参考 /skills/procurement/chart_params.md。

    内容：
        已连接对应远端图表时，按原参数调用并返回服务结果。
        其余支持的类型使用 Plotly 绘制，并保存到当前用户工作区。

    Args:
        chart_type - bar、line、pie 等图表类型，完整列表见参数参考
        chart_config - 内置 Plotly 使用 data 字典或列表、title、可选 layout；外部 MCP 使用该工具的参数
        runtime - 框架注入的用户和会话上下文
    Returns:
        图表文件路径；已接入对应外部图表工具时返回其实际结果。
    """
    context = get_context(runtime)
    backend = get_user_backend(context.user_id)
    remote_name = f"generate_{chart_type}_chart"
    if chart_type.endswith(("_map", "_diagram", "_graph")):
        remote_name = f"generate_{chart_type}"
    remote = MCP_CHART_TOOLS.get(remote_name)
    if remote is not None:
        return {"provider": "mcp", "result": await remote.ainvoke(chart_config)}
    if chart_type not in CHART_TYPES:
        raise ValueError(f"未配置图表类型 {chart_type}；先读取 /skills/procurement/chart_params.md 确认实际可用类型")
    spec = CHART_TYPES[chart_type]
    data = chart_config["data"]
    traces = data if isinstance(data, list) else [data]
    figure = go.Figure(
        data=[{**spec, **trace} for trace in traces],
        layout={"title": chart_config.get("title", chart_type), **chart_config.get("layout", {})},
    )
    path = f"/analysis/charts/{chart_type}_{uuid4().hex[:8]}.html"
    html = figure.to_html(include_plotlyjs=True, full_html=True)
    results = await backend.aupload_files([(path, html.encode())])
    if results[0].error:
        raise OSError(results[0].error)
    return {"provider": "plotly", "chart_type": chart_type, "path": path}
