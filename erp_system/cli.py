"""ERP 初始化与带备份的演示数据重置命令。"""

import argparse
import sqlite3
from datetime import date, datetime, timedelta, timezone

from erp_system.config import Settings
from erp_system.database import Database
from erp_system.service import ERPService


def main() -> None:
    """
    初始化演示数据库，或显式备份并重置业务数据。

    Args:
        无。
    Returns:
        None - 执行命令并输出数据库或备份文件位置。
    """
    parser = argparse.ArgumentParser(description="初始化或重置 ERP 演示数据")
    parser.add_argument("action", choices=["init", "reset"])
    parser.add_argument("--yes", action="store_true", help="明确允许重置现有业务数据")
    parser.add_argument("--date", type=date.fromisoformat)
    args = parser.parse_args()
    if args.action == "reset" and not args.yes:
        parser.error("重置会替换业务数据，请在确认后添加 --yes；重置前会自动备份")
    db = Database(Settings().database_path)
    service = ERPService(db)
    try:
        service.initialize()
        if args.action == "reset":
            backups = db.path.parent / "backups"
            backups.mkdir(parents=True, exist_ok=True)
            target = backups / f"erp-{datetime.now():%Y%m%d-%H%M%S-%f}.sqlite"
            with sqlite3.connect(db.path) as source, sqlite3.connect(target) as destination:
                source.backup(destination)
            service.reset(args.date or datetime.now(timezone(timedelta(hours=8))).date())
            print(f"已备份至 {target}")
        print(f"ERP 数据库：{db.path}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
