"""SQLAlchemy 连接管理与 SQLite 事务、迁移管理。"""

from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from sqlalchemy import Connection, create_engine, event


def _configure(connection, record):
    """启用外键、WAL 和等待锁超时。"""
    cursor = connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA busy_timeout=15000")
    cursor.close()


class Database:
    """使用立即写事务串行校验库存，避免 SQLite 忽略行锁的问题。"""

    def __init__(self, path: Path):
        """构造数据库连接引擎，连接在实际访问时建立。"""
        self.path = Path(path).resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.engine = create_engine(f"sqlite:///{self.path.as_posix()}", connect_args={"check_same_thread": False, "timeout": 15})
        event.listen(self.engine, "connect", _configure)

    @contextmanager
    def read(self) -> Iterator[Connection]:
        """
        提供只读业务查询使用的连接。

        Args:
            无。
        Returns:
            逐次提供一个 SQLAlchemy 连接，退出上下文后关闭连接。
        """
        with self.engine.connect() as connection:
            yield connection

    @contextmanager
    def write(self) -> Iterator[Connection]:
        """
        提供立即写事务，业务失败时回滚全部状态变化。

        Args:
            无。
        Returns:
            逐次提供一个事务连接，正常退出提交，异常退出回滚。
        """
        with self.engine.connect() as connection:
            connection.exec_driver_sql("BEGIN IMMEDIATE")
            try:
                yield connection
                connection.commit()
            except Exception:
                connection.rollback()
                raise

    def migrate(self) -> None:
        """
        按文件名顺序执行尚未应用的 SQL 数据库迁移。

        Args:
            无。
        Returns:
            None - 创建或升级表结构，并记录已应用的迁移版本。
        """
        with self.write() as connection:
            connection.exec_driver_sql("CREATE TABLE IF NOT EXISTS schema_migrations (version TEXT PRIMARY KEY)")
            for file in sorted((Path(__file__).parent / "migrations").glob("*.sql")):
                applied = connection.exec_driver_sql("SELECT 1 FROM schema_migrations WHERE version=?", (file.name,)).first()
                if not applied:
                    for statement in file.read_text(encoding="utf-8").split(";"):
                        if statement.strip():
                            connection.exec_driver_sql(statement)
                    connection.exec_driver_sql("INSERT INTO schema_migrations VALUES (?)", (file.name,))

    def close(self) -> None:
        """
        释放数据库连接池。

        Args:
            无。
        Returns:
            None - 关闭连接池中的空闲连接。
        """
        self.engine.dispose()
