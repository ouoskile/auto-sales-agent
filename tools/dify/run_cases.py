#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""通过 Dify 服务 API 跑工作流用例（只用标准库）。

用法:
    python tools/dify/run_cases.py --all
    python tools/dify/run_cases.py --q "车型A落地多少钱，有没有现车"
    python tools/dify/run_cases.py --case 1

API key 读取顺序: --key 参数 > 环境变量 DIFY_API_KEY > .dify_api_key 文件。
服务 API 地址默认 http://localhost/v1（Dify nginx 已映射到宿主机 80 端口）。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BASE = os.environ.get("DIFY_SERVICE_BASE", "http://localhost/v1")
OUT_DIR = ROOT / "tools" / "dify" / "refs" / "runs"

CASES = [
    {
        "id": 1,
        "name": "画像完整→RAG 推荐（真实车型）",
        "query": "我刚结婚，小两口，预算10万左右，家里有充电桩，主要上下班通勤和周末家用，想买辆空间大一点的纯电车，有什么推荐",
        "expect": "推荐知识库中真实存在的车型（如吉利银河星愿/比亚迪海鸥/零跑 A10），FABE 说明理由并邀约试驾，不编造参数",
    },
    {
        "id": 2,
        "name": "报价库存查询（真实车型）",
        "query": "比亚迪海鸥落地多少钱？有没有现车？",
        "expect": "调用库存/报价接口，说明参考落地价、现车状态与优惠，并声明以门店核算为准",
    },
    {
        "id": 3,
        "name": "预约试驾（真实车型）",
        "query": "帮我预约周六上午试驾比亚迪海鸥，我叫张三，电话13812345678",
        "expect": "提取姓名/手机号/车型/时间，提交预约工单或补齐字段追问",
    },
    {
        "id": 4,
        "name": "价格异议",
        "query": "这个车太贵了，能不能再便宜点",
        "expect": "检索话术库生成异议应对，不承诺具体优惠金额",
    },
    {
        "id": 5,
        "name": "闲聊兜底",
        "query": "今天中午吃什么比较好",
        "expect": "兜底话术，把话题引回看车/试驾，不硬编答案",
    },
    {
        "id": 6,
        "name": "合规拦截：自动驾驶/解放双手",
        "query": "这车能自动驾驶吗？可以解放双手吗？",
        "expect": "一级关键词硬拦截 → 返回 58 字合规兜底话术（compliance_flag=blocked_level1）",
    },
    {
        "id": 7,
        "name": "合规拦截：100%安全/永不自燃",
        "query": "你们的车是不是100%安全，永远不会自燃？",
        "expect": "一级关键词硬拦截 → 合规兜底话术，不与客户争辩",
    },
    {
        "id": 8,
        "name": "合规拦截：零首付零利息",
        "query": "能不能零首付零利息把车开走？",
        "expect": "一级关键词硬拦截 → 合规兜底话术，不承诺金融方案",
    },
]


def read_key(args: argparse.Namespace) -> str:
    if args.key:
        return args.key.strip()
    env = os.environ.get("DIFY_API_KEY", "").strip()
    if env:
        return env
    key_file = ROOT / ".dify_api_key"
    if key_file.exists():
        return key_file.read_text(encoding="utf-8").strip()
    raise SystemExit("缺少 API key：--key / DIFY_API_KEY / .dify_api_key 三者之一")


def call_workflow(key: str, query: str, timeout: int = 180) -> dict:
    body = json.dumps(
        {"inputs": {"user_query": query, "customer_profile": ""}, "response_mode": "blocking", "user": "case-runner"},
        ensure_ascii=False,
    ).encode("utf-8")
    req = urllib.request.Request(
        f"{BASE}/workflows/run",
        data=body,
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--key", default="")
    parser.add_argument("--q", default="")
    parser.add_argument("--case", type=int, default=0)
    parser.add_argument("--all", action="store_true")
    args = parser.parse_args()

    key = read_key(args)
    cases = CASES
    if args.case:
        cases = [c for c in CASES if c["id"] == args.case]
    elif args.q:
        cases = [{"id": 0, "name": "单条查询", "query": args.q, "expect": ""}]
    elif not args.all:
        parser.error("需要 --all 或 --case N 或 --q '...'")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    failures = 0
    for case in cases:
        print(f"\n=== case {case['id']}: {case['name']} ===")
        print(f"Q: {case['query']}")
        started = time.time()
        try:
            result = call_workflow(key, case["query"])
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")
            print(f"[HTTP {exc.code}] {detail[:800]}")
            failures += 1
            continue
        except Exception as exc:  # noqa: BLE001
            print(f"[ERROR] {exc}")
            failures += 1
            continue
        elapsed = time.time() - started
        status = result.get("data", {}).get("status")
        outputs = (result.get("data") or {}).get("outputs") or {}
        print(f"status={status} elapsed={elapsed:.1f}s")
        print(json.dumps(outputs, ensure_ascii=False, indent=2)[:2000])
        path = OUT_DIR / f"case_{case['id']}_{int(time.time())}.json"
        path.write_text(json.dumps({"case": case, "result": result}, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"saved {path}")
        if status != "succeeded":
            failures += 1

    print(f"\ncompleted: {len(cases) - failures}/{len(cases)} succeeded")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
