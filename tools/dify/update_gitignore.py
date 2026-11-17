#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把 Dify 相关本地私密产物追加进 .gitignore（保持 UTF-8，不破坏已有内容）。"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
GITIGNORE = ROOT / ".gitignore"
EXTRA = [
    "",
    "# Dify 本地私密产物（API key / 登录 token / 运行结果）",
    ".dify_api_key",
    ".dify_token",
    "tools/dify/refs/runs/",
    "tools/dify/refs/app_workflow_ref.json",
    "tools/dify/refs/app_workflow_ref.zip",
]


def main() -> None:
    text = GITIGNORE.read_text(encoding="utf-8") if GITIGNORE.exists() else ""
    missing = [line for line in EXTRA if line.strip() and line.strip() not in text]
    if missing:
        if not text.endswith("\n"):
            text += "\n"
        text += "\n".join(missing) + "\n"
        GITIGNORE.write_text(text, encoding="utf-8")
        print("added:", ", ".join(missing))
    else:
        print("nothing to add")


if __name__ == "__main__":
    main()
