#!/usr/bin/env python3
"""扫描源资料与生成文档中的违规词命中，输出命中清单 JSON。

用法：
    python tools/dify/kb_real/scan_compliance.py            # 扫描 txt/ 源资料
    python tools/dify/kb_real/scan_compliance.py --dir docs/dify/knowledge_real  # 扫描生成文档
    python tools/dify/kb_real/scan_compliance.py --quiet    # 只输出 JSON 文件位置
"""

from __future__ import annotations

import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
WORDS = os.path.join(ROOT, "tools", "dify", "compliance_words.json")
OUT = os.path.join(HERE, "compliance_scan.json")


def load_words() -> dict:
    with open(WORDS, "r", encoding="utf-8") as f:
        return json.load(f)


def scan_text(text: str, level_words: dict[str, list[str]]) -> list[dict]:
    hits = []
    for category, words in level_words.items():
        for w in words:
            start = 0
            while True:
                idx = text.find(w, start)
                if idx < 0:
                    break
                line_no = text.count("\n", 0, idx) + 1
                line_start = text.rfind("\n", 0, idx) + 1
                line_end = text.find("\n", idx)
                if line_end < 0:
                    line_end = len(text)
                hits.append(
                    {
                        "word": w,
                        "category": category,
                        "line": line_no,
                        "context": text[line_start:line_end].strip(),
                    }
                )
                start = idx + len(w)
    return hits


def scan_dir(path: str, words: dict, skip: set[str]) -> dict:
    files = []
    for dirpath, _dirnames, filenames in os.walk(path):
        for name in sorted(filenames):
            if not name.lower().endswith((".txt", ".md")):
                continue
            full = os.path.join(dirpath, name)
            if os.path.basename(full) in skip:
                continue
            with open(full, "r", encoding="utf-8", errors="replace") as f:
                text = f.read()
            rel = os.path.relpath(full, ROOT).replace("\\", "/")
            lvl1 = scan_text(text, words["level1"])
            lvl2 = scan_text(text, words["level2"])
            lvl3 = scan_text(text, words["level3"])
            files.append(
                {
                    "file": rel,
                    "chars": len(text),
                    "level1": lvl1,
                    "level2": lvl2,
                    "level3": lvl3,
                    "counts": {"level1": len(lvl1), "level2": len(lvl2), "level3": len(lvl3)},
                }
            )
    return {"root": os.path.relpath(path, ROOT).replace("\\", "/"), "files": files}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default=os.path.join(ROOT, "txt"))
    ap.add_argument("--skip", nargs="*", default=["28 - 违规词分级与完整清单.txt", "29 - 高频违规词合规替换话术库.txt"])
    ap.add_argument("--out", default=OUT)
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    words = load_words()
    result = scan_dir(args.dir, words, set(args.skip))
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    total = {"level1": 0, "level2": 0, "level3": 0}
    print(f"{'文件':60s} L1  L2  L3")
    for row in result["files"]:
        c = row["counts"]
        for k in total:
            total[k] += c[k]
        flag = " <<<" if c["level1"] else ""
        print(f"{os.path.basename(row['file']):60s} {c['level1']:3d} {c['level2']:3d} {c['level3']:3d}{flag}")
    print(f"\n合计 L1={total['level1']} L2={total['level2']} L3={total['level3']}")
    print(f"明细已写入 {os.path.relpath(args.out, ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
