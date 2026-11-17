#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""把 tools/dify/workflow_draft.json 提交为 Dify 应用的工作流草稿。

用法：
    python tools/dify/submit_draft.py                 # 提交到默认应用
    python tools/dify/submit_draft.py --app-id <uuid> # 提交到指定应用
    python tools/dify/submit_draft.py --print-only    # 只生成 job 文件，不发请求

流程：
1. 调 `dify.py get /console/api/apps/<app_id>/workflows/draft` 取当前草稿，
   拿到服务端 hash（首次保存后就必须带上，否则 409 draft_workflow_not_sync）。
2. 把 hash 注入 workflow_draft.json 的顶层 "hash" 字段，生成 job JSON。
3. 调 `dify.py job` 把 {graph, features, hash, conversation_variables} POST 到
   /console/api/apps/<app_id>/workflows/draft。
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
DRAFT = ROOT / "tools" / "dify" / "workflow_draft.json"
JOB = ROOT / ".tmp_tests" / "job_save_draft.json"
DIFY = ROOT / "tools" / "dify" / "dify.py"
DEFAULT_APP_ID = "479d4779-9f96-4553-a8d8-e0401da50d35"


def run_dify(*args: str) -> tuple[int, str]:
    proc = subprocess.run(
        [sys.executable, str(DIFY), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return proc.returncode, (proc.stdout or "")


def fetch_draft_hash(app_id: str) -> str | None:
    """返回当前草稿的 hash；草稿不存在/无 hash 时返回 None。"""
    path = f"/console/api/apps/{app_id}/workflows/draft"
    code, out = run_dify("get", path)
    if code != 0:
        return None
    try:
        payload = json.loads(out)
    except json.JSONDecodeError:
        match = re.search(r'"hash"\s*:\s*"([0-9a-f]{32,})"', out)
        return match.group(1) if match else None
    value = payload.get("hash") if isinstance(payload, dict) else None
    return value if isinstance(value, str) and value else None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--app-id", default=DEFAULT_APP_ID)
    parser.add_argument("--print-only", action="store_true")
    parser.add_argument(
        "--no-hash",
        action="store_true",
        help="不查询服务端 hash，直接以 null 提交（仅适用于全新空应用）",
    )
    args = parser.parse_args()

    draft: dict[str, Any] = json.loads(DRAFT.read_text(encoding="utf-8"))
    if not args.no_hash:
        server_hash = fetch_draft_hash(args.app_id)
        draft["hash"] = server_hash
        print(f"server hash: {server_hash or '(none)'}")

    job = {
        "method": "POST",
        "path": f"/console/api/apps/{args.app_id}/workflows/draft",
        "json": draft,
    }
    JOB.parent.mkdir(parents=True, exist_ok=True)
    JOB.write_text(json.dumps(job, ensure_ascii=False), encoding="utf-8")
    print(f"job written: {JOB} ({JOB.stat().st_size} bytes)")
    if args.print_only:
        return 0

    proc = subprocess.run(
        [sys.executable, str(DIFY), "job", str(JOB)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if proc.stdout:
        print(proc.stdout)
    if proc.stderr:
        sys.stderr.write(proc.stderr)
    return proc.returncode


if __name__ == "__main__":
    sys.exit(main())
