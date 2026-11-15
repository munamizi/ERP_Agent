"""启动 ERP 和供应商网站，可同时启动 MCP 和 Agent API。"""

import argparse
import os
import subprocess
import sys
import time

from erp_system.config import ROOT, _load_env
from dotenv import load_dotenv


def main() -> None:
    """
    用当前解释器启动 ERP、供应商及可选 Agent 服务，并管理子进程退出。

    步骤：
        1. 读取监听地址参数和本地环境配置。
        2. 启动 ERP 和报价网站，按参数启动 MCP 和对话 API。
        3. 监测子进程状态，退出时终止并等待各服务结束。

    Args:
        无。
    Returns:
        None - 启动所选服务；退出时终止并等待子进程结束。
    """
    parser = argparse.ArgumentParser(description="启动电脑 ERP 与模拟供应商网站")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--supplier-host", help="报价站监听地址，默认读取 SUPPLIER_SITE_HOST 或沿用 --host")
    parser.add_argument("--with-agent", action="store_true", help="同时启动采购 MCP 和 Agent 对话 API")
    args = parser.parse_args()
    _load_env()
    load_dotenv(ROOT / "src/.env", encoding="utf-8-sig")
    supplier_host = args.supplier_host or os.getenv("SUPPLIER_SITE_HOST", args.host)
    children = []
    try:
        commands = [
            [sys.executable, "-m", "uvicorn", "erp_system.app:app", "--host", args.host, "--port", "8001"],
            [sys.executable, "-m", "http.server", "8080", "--bind", supplier_host, "--directory", str(ROOT / "supplier_site" / "public")],
        ]
        if args.with_agent:
            commands.extend([
                [sys.executable, "-m", "src.agent.tools.mcp.server.server_main"],
                [sys.executable, "-m", "uvicorn", "src.backend.api.web_main:app", "--host", args.host, "--port", "8003"],
            ])
        for command in commands:
            children.append(subprocess.Popen(command, cwd=ROOT, env=os.environ.copy(), creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0))
        print(f"ERP：http://{args.host}:8001   供应商：http://{supplier_host}:8080", flush=True)
        print("ERP 接口文档：http://localhost:8001/docs   Ctrl+C 关闭全部服务", flush=True)
        if args.with_agent:
            print(f"MCP：http://{args.host}:8000/mcp   Agent 页面：http://{args.host}:8003/   Agent API：http://{args.host}:8003/docs", flush=True)
        while all(child.poll() is None for child in children):
            time.sleep(0.5)
        if any(child.returncode not in (None, 0) for child in children):
            raise SystemExit("服务启动失败，请查看上方日志和端口占用情况")
    except KeyboardInterrupt:
        pass
    finally:
        for child in children:
            if child.poll() is None:
                child.terminate()
        for child in children:
            try:
                child.wait(timeout=10)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait()


if __name__ == "__main__":
    main()