# 图表参数

只有本次明确要求图表或已确认的输出偏好需要图表时，才读取本参考并调用图表工具。普通询价、最低价和少量报价比较直接回复文字或小表格，不自动生成图表。

入口为 generate_visualization(chart_type, chart_config)。默认用 Plotly 输出内嵌脚本的 HTML。

chart_config 包含 title、data 和可选 layout。data 为下表中的轨迹对象，多条曲线时传对象列表；layout 使用 Plotly 布局参数。

| chart_type | data 主要字段 |
|---|---|
| bar | x: 类别，y: 金额 |
| line | x: 日期，y: 价格 |
| area | x、y |
| scatter | x、y: 数值列表 |
| bubble | x、y、marker: {size: 数值列表} |
| pie | labels: 类别，values: 金额 |
| donut | labels、values |
| histogram | x: 原始数值列表 |
| box | y: 原始数值，name: 组名 |
| violin | y、name |
| heatmap | x、y: 标签，z: 数值矩阵 |
| radar | theta: 维度，r: 分数 |
| polar | theta: 角度，r: 半径 |
| scatter3d | x、y、z: 数值列表 |
| line3d | x、y、z |
| surface | z: 矩阵，可选 x、y |
| contour | z: 矩阵，可选 x、y |
| waterfall | x: 项目，y: 增减，measure: relative/total 列表 |
| funnel | y: 阶段，x: 数量 |
| treemap | labels、parents、values |
| sunburst | labels、parents、values |
| sankey | node: {label: 节点列表}，link: {source: 索引, target: 索引, value: 数值列表} |
| gauge | value: 当前值，gauge: {axis: {range: [0,100]}} |
| table | header: {values: 列名}，cells: {values: 按列组织的数据} |
| parallel_coordinates | dimensions: [{label: 维度, values: 数值列表}] |
| scatter_matrix | dimensions: [{label: 维度, values: 数值列表}] |

柱状图的 chart_config 示例（示例数字，实际调用要使用本次数据）：

```json
{"title":"CPU 报价","data":{"x":["供应商甲","供应商乙"],"y":[1490,1520]},"layout":{"yaxis":{"title":"元/颗"}}}
```

返回 path 为会话文件路径，交给主 Agent 用 download_sandbox_file 导出。

EXTRA_MCP_SERVERS 可接教程的外部图表服务。generate_<类型>_chart 合并为对应类型；generate_district_map、generate_flow_diagram、generate_network_graph 等保留 map/diagram/graph 后缀。实际连接的远端 schema 由技能同步自动追加到本文件末尾。

同名图表已接远端时优先用远端参数，不把 Plotly 的 x/y 轨迹格式传给远端。远端返回 result 按服务原结果交付，不能当成本地 path 导出。电子表格工具不属于本图表入口。
