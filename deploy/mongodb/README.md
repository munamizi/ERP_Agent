# ERP-Agent MongoDB

部署在 Linux 虚拟机 `192.168.100.135`，独立于 OpenSandbox 沙箱容器。

- 镜像：`mongo:9.0.4`，版本依据 MongoDB 官方发布说明选择，包含 Ubuntu 26.04 支持。
- 连接地址：`192.168.100.135:27017`。
- 项目数据库和账号：`erp_agent`，账号仅有该数据库的读写权限。
- 管理账号：`mongo_admin`，与应用账号使用不同的随机密码。
- 资源上限：1 CPU、1 GiB 内存，WiredTiger 缓存 0.25 GiB。
- 持久卷：`erp-agent-mongodb-data`、`erp-agent-mongodb-config`。
- 自启：Docker 服务开机启动，容器设置 `restart: always`。

已验证 Windows 端通过项目安装的 `MongoDBStore` 完成写入、读取和查询；未认证读取被拒绝；MongoDB 容器重启后记录仍存在。验证集合已清理。

自建 API 的存储职责：

- `agent_store`：仅供 Agent 的 `/memories/` 和 `/persisted-skills/` 使用。
- `chat_sessions`：原生 BSON 会话文档，保存用户、标题、状态、更新时间、展示消息和中断。按 `(user_id, updated_at)` 查询列表，按唯一的 `(user_id, thread_id)` 加载或删除会话。
- `checkpoints`、`checkpoint_writes`：Agent 执行检查点，仍由 `MongoDBSaver` 管理。

继续使用现有 `MONGODB_URI` 与 `MONGODB_DATABASE` 即可，启动时自动建立会话索引。未配置 URI 时，三类存储各自使用内存；已配置但连接失败时不会静默切回内存。旧 `store` 集合不再被自建 API 读写，旧数据需要单独复制到新集合，迁移不在请求处理过程中执行。

虚拟机部署目录为 `/opt/erp-agent-mongodb`。管理凭据保存在该目录的 `.env`，应用连接配置保存在 `connection.env`；目录和凭据文件仅 root 可访问。本机连接配置另存于 `.runtime/mongodb-connection.env`，现已写入项目 `src/.env`。重启自建 FastAPI 后，Store 和检查点会一起切换到 MongoDB；已有内存记录不会自动迁移。

在虚拟机检查或重建服务配置：

```bash
sudo docker compose --project-directory /opt/erp-agent-mongodb ps
sudo docker compose --project-directory /opt/erp-agent-mongodb logs --tail 50
sudo docker compose --project-directory /opt/erp-agent-mongodb up -d
```

`init-user.js` 仅在空数据卷首次初始化时执行。重建容器时保留数据卷；不要使用 `down -v`，否则会删除数据库数据卷。

官方版本说明：https://www.mongodb.com/docs/manual/release-notes/9.0/
