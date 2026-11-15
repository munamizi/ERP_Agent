"""下载用户指定的技能 ZIP，检查目录和元信息后解压到草稿目录。"""

import argparse
import io
import json
import re
import zipfile
from pathlib import Path, PurePosixPath
from urllib.request import urlopen

import yaml


def download_skill(url: str, name: str, root: Path = Path("/draft-skills")) -> dict:
    """
    下载并解压技能包，不执行包内脚本或覆盖已有草稿。

    步骤：
        1. 下载 ZIP，定位唯一的 SKILL.md 和技能根目录。
        2. 检查元信息及文件路径，拒绝越界或混入其他目录的文件。
        3. 将技能文件写入新的草稿目录，返回分配前的检查信息。

    Args:
        url - 用户指定的 HTTP 或 HTTPS 技能 ZIP 地址
        name - 草稿技能目录名，只含小写字母、数字和连字符
        root - 草稿根目录，默认 /draft-skills
    Returns:
        技能目录、元信息名称及解压文件列表，不代表已测试或已分配。
    """
    if not url.startswith(("http://", "https://")) or not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", name):
        raise ValueError("请提供 HTTP(S) ZIP 地址和合法的小写技能目录名")
    with urlopen(url, timeout=30) as response:
        archive_bytes = response.read()
    target = (root / name).resolve()
    if target.exists():
        raise FileExistsError(f"草稿目录已存在，请先检查：{target}")

    with zipfile.ZipFile(io.BytesIO(archive_bytes)) as archive:
        entries = [item for item in archive.infolist() if not item.is_dir()]
        skill_files = [item for item in entries if PurePosixPath(item.filename).name == "SKILL.md"]
        if len(skill_files) != 1:
            raise ValueError("ZIP 必须包含唯一的 SKILL.md")
        skill_file = skill_files[0]
        text = archive.read(skill_file).decode("utf-8-sig")
        parts = text.split("---", 2)
        if len(parts) != 3 or parts[0].strip():
            raise ValueError("SKILL.md 缺少 YAML 元信息")
        metadata = yaml.safe_load(parts[1])
        if not isinstance(metadata, dict) or not metadata.get("name") or not metadata.get("description"):
            raise ValueError("SKILL.md 必须包含 name 和 description")

        prefix = PurePosixPath(skill_file.filename).parent
        files = []
        for entry in entries:
            relative = PurePosixPath(entry.filename).relative_to(prefix)
            destination = (target / str(relative)).resolve()
            if "\\" in entry.filename or not destination.is_relative_to(target):
                raise ValueError(f"ZIP 文件路径越界：{entry.filename}")
            files.append((entry, destination))
        for entry, destination in files:
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(archive.read(entry))

    return {"skill_name": name, "metadata_name": metadata["name"], "path": str(target),
            "files": [str(destination.relative_to(target)) for _, destination in files]}


def main() -> None:
    """
    读取下载地址和技能目录名，打印技能草稿的解压结果。

    Args:
        无。
    Returns:
        None - 创建技能草稿目录并打印 JSON，失败时抛出异常。
    """
    parser = argparse.ArgumentParser(description="下载技能 ZIP 到草稿目录")
    parser.add_argument("--url", required=True)
    parser.add_argument("--name", required=True)
    args = parser.parse_args()
    print(json.dumps(download_skill(args.url, args.name), ensure_ascii=False))


if __name__ == "__main__":
    main()
