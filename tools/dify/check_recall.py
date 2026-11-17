#!/usr/bin/env python3
"""Dify 知识库召回批量测试（宿主机侧）。

读 cases JSON（[{id, query, expect: [关键词...]}, ...]），对每条调
POST /console/api/datasets/{dataset_id}/hit-testing，输出 Top N 命中分段与分数字，
并按 expect 关键词做粗略命中判定，最后打印汇总。

用法：
    python tools/dify/check_recall.py                       # 用默认 cases 文件
    python tools/dify/check_recall.py --cases tools/dify/recall_cases.json --top 3
    python tools/dify/check_recall.py --threshold 0.5 --out tools/dify/refs/recall_real.json
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
DIFY = os.path.join(HERE, "dify.py")
JOBS = os.path.join(HERE, "jobs")
DATASET_ID = "403fbc9d-3c82-4077-8033-6761821f68f3"
DEFAULT_CASES = os.path.join(HERE, "recall_cases.json")


def run_job(payload: dict) -> dict:
    os.makedirs(JOBS, exist_ok=True)
    tmp = os.path.join(JOBS, f"_recall_{int(time.time() * 1000)}_{os.getpid()}.json")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    try:
        proc = subprocess.run(
            [sys.executable, DIFY, "job", tmp],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        out = (proc.stdout or "").strip()
        match = re.search(r"(\{.*\}|\[.*\])", out, re.S)
        if not match:
            raise RuntimeError(f"job 无 JSON 输出: rc={proc.returncode}\nstdout={out}\nstderr={proc.stderr}")
        return json.loads(match.group(1))
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass


def hit_testing(query: str, top_k: int, threshold: float) -> dict:
    return run_job(
        {
            "method": "POST",
            "path": f"/console/api/datasets/{DATASET_ID}/hit-testing",
            "json": {
                "query": query,
                "retrieval_model": {
                    "search_method": "semantic_search",
                    "reranking_enable": False,
                    "top_k": top_k,
                    "score_threshold_enabled": threshold > 0,
                    "score_threshold": threshold if threshold > 0 else None,
                },
            },
        }
    )


def summarize(res: dict, expect: list[str], top_k: int) -> dict:
    records = res.get("records") or []
    rows = []
    for i, rec in enumerate(records[:top_k]):
        seg = rec.get("segment") or {}
        doc = seg.get("document") or {}
        content = (seg.get("content") or "").strip().replace("\n", " ")
        rows.append(
            {
                "rank": i + 1,
                "doc": doc.get("name"),
                "score": round(float(rec.get("score") or 0), 4),
                "snippet": content[:160],
            }
        )
    blob = " ".join((r["snippet"] or "") for r in rows)
    hit_terms = [t for t in expect if t and t in blob]
    if not rows:
        verdict = "empty"
    elif expect and len(hit_terms) == len(expect):
        verdict = "hit"
    elif hit_terms:
        verdict = "partial"
    else:
        verdict = "miss"
    return {"records": rows, "hit_terms": hit_terms, "verdict": verdict}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cases", default=DEFAULT_CASES)
    ap.add_argument("--top", type=int, default=3)
    ap.add_argument("--threshold", type=float, default=0.5)
    ap.add_argument("--out", default=os.path.join(HERE, "refs", "recall_result.json"))
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    with open(args.cases, "r", encoding="utf-8") as f:
        cases = json.load(f)

    results = []
    counts = {"hit": 0, "partial": 0, "miss": 0, "empty": 0}
    for case in cases:
        res = hit_testing(case["query"], args.top, args.threshold)
        summary = summarize(res, case.get("expect") or [], args.top)
        counts[summary["verdict"]] += 1
        row = {"id": case.get("id"), "query": case["query"], **summary}
        results.append(row)
        if not args.quiet:
            print(f"[{row['id']}] {row['query']}")
            for r in summary["records"]:
                print(f"   #{r['rank']} {r['score']:.4f} {r['doc']} | {r['snippet'][:90]}")
            print(f"   -> {summary['verdict']}  hit_terms={summary['hit_terms']}")

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump({"dataset_id": DATASET_ID, "top_k": args.top, "threshold": args.threshold,
                   "counts": counts, "results": results}, f, ensure_ascii=False, indent=2)
    print(f"\n汇总: {counts}  总用例 {len(cases)}  -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
