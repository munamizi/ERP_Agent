// 应用账号只读写 ERP-Agent 数据库，管理账号由镜像入口创建。
db.getSiblingDB("erp_agent").createUser({
    user: "erp_agent",
    pwd: process.env.ERP_MONGO_PASSWORD,
    roles: [{ role: "readWrite", db: "erp_agent" }],
});
