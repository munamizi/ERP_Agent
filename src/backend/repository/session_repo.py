"""
MongoDB会话管理：
    保存展示记录，配置 MongoDB 时使用 chat_sessions 集合。
"""

import asyncio
from copy import deepcopy
from datetime import datetime, timezone

from pymongo import ASCENDING, DESCENDING
from pymongo.collection import Collection


class SessionRepository:
    """通过原生 MongoDB 文档管理会话，未提供集合时使用内存。"""

    def __init__(self, collection: Collection | None = None):
        """保存集合或内存记录，并为 MongoDB 创建查询索引。"""
        self.collection = collection
        self._sessions = {}
        if collection is not None:
            collection.create_index([("user_id", ASCENDING), ("updated_at", DESCENDING)])
            collection.create_index([("user_id", ASCENDING), ("thread_id", ASCENDING)], unique=True)

    async def save(
        self,
        user_id: str,
        thread_id: str,
        title: str,
        status: str,
        messages: list[dict] | None = None,
        interrupts: list[dict] | None = None,
    ) -> None:
        """
        更新会话，保留首次标题，并按需替换展示消息与中断。

        Args:
            user_id - 用户id
            thread_id - 会话id
            title - 标题
            status - running、 completed、 interrupted 、 error
            messages - list[消息字典]
            interrupts - 随 messages 保存的待处理中断，省略时为空列表
        """
        fields = {
            "status": status,
            "updated_at": datetime.now(timezone.utc)
        }
        initial = {
            "title": title[:40]
        }
        if messages is not None:
            fields.update(messages=messages, interrupts=interrupts or [])
        else:
            initial.update(messages=[], interrupts=[])

        identity = {
            "user_id": user_id,
            "thread_id": thread_id
        }
        if self.collection is not None:
            await asyncio.to_thread(
                self.collection.update_one,
                identity,
                {
                    "$set": fields,
                    "$setOnInsert": initial
                },
                upsert=True,
            )
        else:
            session = self._sessions.setdefault((user_id, thread_id), {**identity, **initial})
            session.update(deepcopy(fields))

    async def list_sessions(self, user_id: str, limit: int = 1000) -> list[dict]:
        """
        按更新时间倒序列出用户会话列表。

        Args:
            user_id - 会话所属用户的原始标识
            limit - 返回的最大会话数量，必须大于零
        Returns:
            包含 thread_id、title、status、updated_at 的列表，不含消息或中断。
        """
        if limit < 1:
            raise ValueError("会话列表数量必须大于零")
        if self.collection is not None:
            return await asyncio.to_thread(self._list_mongodb_sessions, user_id, limit)

        items = [
            {field: session[field] for field in ("thread_id", "title", "status", "updated_at")}
            for (owner, _), session in self._sessions.items()
            if owner == user_id
        ]
        # 内存兜底自行排序；MongoDB 查询在数据库中完成排序和截断。
        items.sort(key=lambda item: item["updated_at"], reverse=True)
        return items[:limit]

    def _list_mongodb_sessions(self, user_id: str, limit: int) -> list[dict]:
        """在线程中执行 MongoDB 投影、倒序排序和数量限制，并消费游标。"""
        cursor = self.collection.find(
            {"user_id": user_id},
            {"_id": 0, "thread_id": 1, "title": 1, "status": 1, "updated_at": 1},
        ).sort("updated_at", DESCENDING).limit(limit)
        return list(cursor)


    async def get(self, user_id: str, thread_id: str) -> dict | None:
        """
        根据 用户id 和 会话id 读取完整会话记录。

        Args:
            user_id - 会话所属用户的原始标识
            thread_id - 用户范围内的会话编号
        Returns:
            不含 MongoDB _id 的会话文档；不存在时返回 None。
        """
        if self.collection is not None:
            return await asyncio.to_thread(
                self.collection.find_one,
                {"user_id": user_id, "thread_id": thread_id},
                {"_id": 0},
            )
        return deepcopy(self._sessions.get((user_id, thread_id)))


    async def delete(self, user_id: str, thread_id: str) -> None:
        """
        删除指定用户的会话记录。

        Args:
            user_id - 会话所属用户的原始标识
            thread_id - 用户范围内的会话编号
        Returns:
            None - 删除匹配记录；会话不存在时不执行额外操作。
        """
        if self.collection is not None:
            await asyncio.to_thread(
                self.collection.delete_one, {"user_id": user_id, "thread_id": thread_id}
            )
        else:
            self._sessions.pop((user_id, thread_id), None)