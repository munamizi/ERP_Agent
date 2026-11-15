# Agent 本机测试页面

本目录存放独立测试页面，使用原生 HTML、CSS、JavaScript，无需安装 npm 依赖或构建。由现有 FastAPI 服务提供静态文件，同源调用 `/api`，不依赖 `langgraph dev` 和 Studio。

## 启动

在 IDE 中选择项目的 `.venv` 解释器，直接运行 `../backend`，即可启动页面和 Agent API，地址为 <http://127.0.0.1:8003/>。这只启动 FastAPI，ERP、供应商网站、MCP 和 OpenSandbox 需要另外保持运行。

在项目根目录运行（ERP、供应商网站、MCP 尚未启动时）：

```powershell
.venv/Scripts/python.exe run_demo.py --with-agent
```

如果上述依赖已经运行，只启动 Agent API：

```powershell
.venv/Scripts/python.exe -m uvicorn src.backend.api.web_main:app --host 127.0.0.1 --port 8003
```

打开 <http://127.0.0.1:8003/> 即可使用，默认用户 ID 为 `local-user`、显示名称为“本机用户”。需要切换用户时打开“用户设置”。模型服务密钥只留在后端。

模型、OpenSandbox、ERP 和 MCP 继续使用项目原有环境配置。`/health` 只检查 API 可达性，不验证全部依赖。供应商网站需要能从沙箱访问，按既有 `SUPPLIER_SITE_HOST`、`SUPPLIER_SANDBOX_BASE_URL` 配置监听地址与访问地址。

## 功能与文件

- `index.html`：会话列表、聊天、人工介入卡片、用户设置。
- `styles.css`：页面样式及窄屏适配。
- `app.js`：用户与会话切换、请求、历史恢复、审批交互、诊断记录。
- `stream.js`：读取 POST SSE，处理 UTF-8 网络分片与结束事件。

支持新建会话、删除会话、流式回复、查看历史、刷新恢复中断、补充采购信息，以及按后端允许的类型审批。历史会话右侧的“删除”按钮会先请求确认；删除当前会话后回到空白会话，已导出的文件保留。执行中的请求会锁定删除按钮，服务端拒绝删除时显示原因并保留原会话。执行记录显示工具参数、结果和子代理消息；导出工具返回文件后可展开对应记录并点击下载。助手回复中的 Markdown 表格在流式回复完成或打开历史会话时渲染，其余正文仍按纯文本展示。

## 对接约定

本机测试 API 无需 Agent Token，直接访问以下接口；用户 ID 用于选择对应的会话和工作区。

| 方法与路径 | 用途 |
| --- | --- |
| `POST /api/chat/stream` | 发送 `{message, thread_id, user_id, username}` |
| `POST /api/chat/resume` | 发送 `{thread_id, user_id, username, reply}` |
| `GET /api/history?user_id=…` | 获取会话索引，响应为 `{items: [...]}` |
| `GET /api/history/{thread_id}?user_id=…` | 获取 `{thread_id, messages, interrupts}` 展示快照 |
| `DELETE /api/history/{thread_id}?user_id=…` | 删除会话，由历史列表右侧“删除”按钮调用 |
| `GET /api/files/{filename}?user_id=…&thread_id=…` | 下载已导出的文件 |

两个对话接口均通过 `fetch` 读取 SSE，事件为 `session`、`token`、`tool`、`interrupt`、`done`、`error`。`source=main` 的文本进入聊天区，子代理文本放入执行记录；`done.answer` 作为本轮最终答复。正常结束、服务错误和意外断流都会结束页面等待状态。

人工介入始终恢复原会话。页面使用中断 ID 构建 `reply`，例如：

```json
{
  "thread_id": "原会话编号",
  "user_id": "local-user",
  "username": "本机用户",
  "reply": {
    "中断ID": {"decisions": [{"type": "approve"}]}
  }
}
```

`kind=order_info` 的中断使用同一结构，将对应中断 ID 的值替换为用户补充的文本。一个审批中断有多项 `action_requests` 时，`decisions` 的数量、顺序与其一致；有多个中断时，全部选择后一次提交。仅展示 `review_configs.allowed_decisions` 允许的审批方式，不发送裸字符串 `approve`。

## 当前存储边界

API 与 `langgraph dev` 使用各自的会话存储，Studio 中的旧会话不会自动显示。使用 `InMemoryStore` 时，重启 API 会清空会话和偏好；浏览器仍保存用户设置不代表后端数据仍在。

历史接口读取保存的展示快照，执行中可能没有最新记录；刷新页面后若显示“执行中”，可以稍后刷新会话。页面不会自动重放采购请求或自动批准。补充信息和审批会在提交时显示为本地消息；当前后端未将它们单独保存为主会话用户消息，刷新后这些本地消息可能不显示，中断是否继续以服务端状态为准。

“断开响应”只断开当前浏览器请求，不保证撤销已开始的 ERP 操作。发生错误后先确认执行结果，再决定下一步。
