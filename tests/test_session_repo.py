"""验证会话 Repository、存储分离和历史 API 契约。"""

import asyncio
import importlib
import sys
from datetime import datetime, timezone
from types import ModuleType
from unittest.mock import MagicMock

import httpx
import pytest
from fastapi import FastAPI
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from src.agent.config import AgentSettings
from src.backend.api.routers import history
from src.backend.repository.session_repo import SessionRepository


@pytest.fixture
def loader(monkeypatch):
    """
    创建内存加载器，隔离模块导入时的 MCP 和沙箱初始化。

    Args:
        monkeypatch - pytest 的临时替换工具
    Returns:
        不连接外部服务的 AgentLoader。
    """
    main = ModuleType("src.agent.main_agent")
    main.main_tools, main.model, main.tools = [], None, []
    monkeypatch.setitem(sys.modules, "src.agent.main_agent", main)
    module = importlib.import_module("src.backend.service.agent_loader")
    return module.AgentLoader(AgentSettings())


def test_memory_session_lifecycle():
    """
    验证首次标题、状态更新、展示数据保留、用户隔离和删除。

    Args:
        无。
    Returns:
        None - 断言完整会话生命周期符合存储契约。
    """
    async def _check():
        """执行无外部服务的异步存储验证。"""
        repo = SessionRepository()
        messages = [{"role": "human", "content": "查库存"}]
        pending = [{"id": "approval", "value": {"order_id": 1}}]
        await repo.save("alice", "one", "首" * 50, "running")
        assert (await repo.get("alice", "one"))["messages"] == []
        await repo.save("alice", "one", "替换标题", "interrupted", messages, pending)
        messages[0]["content"] = "调用方修改"
        await repo.save("alice", "two", "第二个会话", "completed", [])
        await repo.save("bob", "one", "其他用户", "completed", [])
        await repo.save("alice", "one", "仍不替换", "error")

        session = await repo.get("alice", "one")
        assert session["title"] == "首" * 40
        assert session["messages"][0]["content"] == "查库存"
        assert session["interrupts"] == pending
        assert session["status"] == "error"
        assert isinstance(session["updated_at"], datetime)
        assert session["updated_at"].tzinfo is not None
        session["messages"].clear()
        assert (await repo.get("alice", "one"))["messages"]

        items = await repo.list_sessions("alice")
        assert [item["thread_id"] for item in items] == ["one", "two"]
        assert len(await repo.list_sessions("alice", limit=1)) == 1
        assert set(items[0]) == {"thread_id", "title", "status", "updated_at"}
        await repo.save("alice", "one", "恢复", "completed", [])
        assert (await repo.get("alice", "one"))["interrupts"] == []
        await repo.delete("alice", "one")
        await repo.delete("alice", "one")
        assert await repo.get("alice", "one") is None
        assert (await repo.get("bob", "one"))["title"] == "其他用户"

    asyncio.run(_check())


def test_mongodb_query_and_atomic_update():
    """
    验证 MongoDB 查询在游标上完成投影、排序和限制，并原子保存首次标题。

    Args:
        无。
    Returns:
        None - 断言索引、查询及更新参数符合预期。
    """
    collection = MagicMock()
    cursor = collection.find.return_value
    cursor.sort.return_value = cursor
    cursor.limit.return_value = cursor
    expected = [{"thread_id": "one", "title": "库存", "status": "running",
                 "updated_at": datetime.now(timezone.utc)}]
    cursor.__iter__.return_value = iter(expected)
    repo = SessionRepository(collection)

    async def _check():
        """检查 MongoDB 调用契约，不模拟数据库内部实现。"""
        assert await repo.list_sessions("alice", 3) == expected
        await repo.save("alice", "one", "库存", "running")
        update = collection.update_one.call_args.args[1]
        assert update["$setOnInsert"] == {"title": "库存", "messages": [], "interrupts": []}
        assert "title" not in update["$set"]
        assert isinstance(update["$set"]["updated_at"], datetime)
        assert collection.update_one.call_args.kwargs == {"upsert": True}
        await repo.save("alice", "one", "忽略", "completed", [])
        update = collection.update_one.call_args.args[1]
        assert update["$set"]["messages"] == []
        assert update["$set"]["interrupts"] == []
        assert update["$setOnInsert"] == {"title": "忽略"}
        await repo.get("alice", "one")
        await repo.delete("alice", "one")

    asyncio.run(_check())
    collection.create_index.assert_any_call([("user_id", 1), ("updated_at", -1)])
    collection.create_index.assert_any_call([("user_id", 1), ("thread_id", 1)], unique=True)
    collection.find.assert_called_once_with(
        {"user_id": "alice"},
        {"_id": 0, "thread_id": 1, "title": 1, "status": 1, "updated_at": 1},
    )
    cursor.sort.assert_called_once_with("updated_at", -1)
    cursor.limit.assert_called_once_with(3)
    collection.find_one.assert_called_once_with({"user_id": "alice", "thread_id": "one"}, {"_id": 0})
    collection.delete_one.assert_called_once_with({"user_id": "alice", "thread_id": "one"})


def test_mongodb_failures_are_not_memory_fallback():
    """
    验证已配置 MongoDB 的写入失败会暴露，而不会静默写入内存。

    Args:
        无。
    Returns:
        None - 断言 MongoDB 异常继续传递。
    """
    collection = MagicMock()
    collection.update_one.side_effect = RuntimeError("database unavailable")
    repo = SessionRepository(collection)
    with pytest.raises(RuntimeError, match="database unavailable"):
        asyncio.run(repo.save("alice", "one", "库存", "running"))
    assert repo._sessions == {}


def test_loader_mongodb_collections(loader, monkeypatch):
    """
    验证加载器将 Agent Store 和会话记录绑定到不同集合。

    Args:
        loader - 隔离外部服务的加载器，确保模块已安全导入
        monkeypatch - pytest 的临时替换工具
    Returns:
        None - 断言集合配置与职责分离要求一致。
    """
    module = sys.modules[type(loader).__module__]
    client = MagicMock()
    database = client.__getitem__.return_value
    store = MagicMock()
    saver = MagicMock()
    monkeypatch.setattr(module, "MongoClient", MagicMock(return_value=client))
    monkeypatch.setattr(module, "MongoDBStore", store)
    monkeypatch.setattr(module, "MongoDBSaver", saver)
    configured = module.AgentLoader(AgentSettings(mongodb_uri="mongodb://example", mongodb_database="example"))
    module.MongoClient.assert_called_once_with("mongodb://example", serverSelectionTimeoutMS=5000, tz_aware=True)
    client.__getitem__.assert_called_once_with("example")
    database.__getitem__.assert_any_call("agent_store")
    database.__getitem__.assert_any_call("chat_sessions")
    store.assert_called_once_with(collection=database["agent_store"])
    saver.assert_called_once_with(client, db_name="example")
    assert configured.session_repo.collection is database["chat_sessions"]


def test_history_api_storage_isolation(loader):
    """
    验证三个历史接口的响应、用户隔离、执行锁和 Agent Store 独立性。

    Args:
        loader - 使用内存检查点、Agent Store 和独立会话 Repository 的加载器
    Returns:
        None - 断言历史读写删除不影响 Agent 记忆或其他用户会话。
    """
    async def _check():
        """运行 API 验证并检查消息转换和删除边界。"""
        app = FastAPI()
        app.state.loader = loader
        app.include_router(history.router)
        await loader.store.aput(("memories", "alice"), "/preferences.md", {"content": "优先现货"})
        messages = [
            HumanMessage(content="查库存", id="user-1"),
            AIMessage(content="", id="ai-1", tool_calls=[{"id": "call-1", "name": "inventory", "args": {}}]),
            ToolMessage(content="10", id="tool-1", tool_call_id="call-1"),
        ]
        pending = [{"id": "approval", "value": {"order_id": 1}}]
        await loader.save_session("alice", "one", "查库存", "interrupted", messages, pending)
        await loader.save_session("bob", "one", "其他用户", "completed", [])
        assert await loader.store.asearch(("sessions",)) == []
        assert await loader.store.asearch(("conversations",)) == []

        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/api/history", params={"user_id": "alice"})
            assert response.status_code == 200
            item = response.json()["items"][0]
            assert set(item) == {"thread_id", "title", "status", "updated_at"}
            assert isinstance(item["updated_at"], str)
            response = await client.get("/api/history/one", params={"user_id": "alice"})
            assert response.status_code == 200
            display = response.json()
            assert set(display) == {"thread_id", "messages", "interrupts"}
            assert display["interrupts"] == pending
            assert [message["role"] for message in display["messages"]] == ["human", "ai", "tool"]
            assert display["messages"][1]["tool_calls"][0]["id"] == "call-1"
            assert display["messages"][2]["tool_call_id"] == "call-1"
            assert (await client.get("/api/history/one", params={"user_id": "unknown"})).status_code == 404

            lock = loader.thread_lock("alice", "one")
            async with lock:
                assert (await client.delete("/api/history/one", params={"user_id": "alice"})).status_code == 409
            assert await loader.session_repo.get("alice", "one") is not None
            response = await client.delete("/api/history/one", params={"user_id": "alice"})
            assert response.status_code == 200
            assert response.json() == {"deleted": "one"}
            assert (await client.get("/api/history/one", params={"user_id": "alice"})).status_code == 404
            assert (await client.get("/api/history/one", params={"user_id": "bob"})).status_code == 200
        assert (await loader.store.aget(("memories", "alice"), "/preferences.md")).value == {"content": "优先现货"}

    asyncio.run(_check())
