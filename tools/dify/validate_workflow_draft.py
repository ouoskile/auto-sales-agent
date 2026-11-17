#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""校验 tools/dify/workflow_draft.json 的结构自洽性（本地，零依赖）。

用法：python tools/dify/validate_workflow_draft.py
退出码 0 = 全部通过；1 = 有错误（逐条打印）。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
JSON_PATH = ROOT / "tools" / "dify" / "workflow_draft.json"

NODE_WIDTH = 242
NODE_GAP_X = 24


def node_outputs(node: dict) -> dict[str, str]:
    """返回 {输出变量名: 类型}，用于校验下游 selector。"""
    data = node.get("data", {})
    ntype = data.get("type")
    if ntype == "start":
        return {v["variable"]: v.get("type", "string") for v in data.get("variables", [])}
    if ntype == "llm":
        return {"text": "string"}
    if ntype == "code":
        return {
            name: spec.get("type", "string")
            for name, spec in (data.get("outputs") or {}).items()
        }
    if ntype == "http-request":
        return {
            "status_code": "number",
            "body": "string",
            "headers": "object",
            "files": "array[file]",
        }
    if ntype == "knowledge-retrieval":
        return {"result": "array[object]"}
    if ntype == "template-transform":
        return {"output": "string"}
    if ntype == "variable-aggregator":
        return {"output": data.get("output_type", "string")}
    if ntype == "parameter-extractor":
        return {
            p["name"]: p.get("type", "string") for p in data.get("parameters", [])
        }
    if ntype == "question-classifier":
        return {"class_name": "string"}
    return {}


def iter_selectors(obj, path="data"):
    """递归找形如 ["node_id", "var"] 的列表。"""
    if isinstance(obj, list):
        if len(obj) == 2 and all(isinstance(x, str) for x in obj):
            yield path, obj
        else:
            for i, item in enumerate(obj):
                yield from iter_selectors(item, f"{path}[{i}]")
    elif isinstance(obj, dict):
        for k, v in obj.items():
            yield from iter_selectors(v, f"{path}.{k}")


def main() -> int:
    doc = json.loads(JSON_PATH.read_text(encoding="utf-8"))
    errors: list[str] = []
    warnings: list[str] = []

    # ---------- 顶层：draft 提交体只允许 SyncDraftWorkflowPayload 的字段
    allowed_top = {
        "graph",
        "features",
        "hash",
        "force",
        "is_collaborative",
        "_is_collaborative",
        "environment_variable_patch",
        "conversation_variables",
    }
    extra_top = sorted(set(doc) - allowed_top)
    if extra_top:
        errors.append(f"顶层出现不允许的字段（extra=forbid 会 400）：{extra_top}")

    graph = doc["graph"]
    nodes = graph["nodes"]
    edges = graph["edges"]
    if len(nodes) != 35:
        errors.append(f"节点数 {len(nodes)} != 35")
    if len(edges) != 44:
        errors.append(f"边数 {len(edges)} != 44")

    ids = [n["id"] for n in nodes]
    dup = {i for i in ids if ids.count(i) > 1}
    if dup:
        errors.append(f"节点 id 重复：{sorted(dup)}")
    if len({n["position"]["x"] for n in nodes}) == 0:
        errors.append("缺少 position")
    if "viewport" not in graph:
        errors.append("graph 缺少 viewport")

    # ---------- 节点 id 必须匹配运行时占位符正则 [a-zA-Z0-9_]{1,50}
    import re

    id_re = re.compile(r"^[a-zA-Z0-9_]{1,50}$")
    for node in nodes:
        if not id_re.match(node["id"]):
            errors.append(f"节点 id 含非法字符（占位符无法引用）：{node['id']}")
        if node.get("type") != "custom":
            warnings.append(f"节点 {node['id']} 的包装 type 不是 custom：{node.get('type')}")
        data = node.get("data", {})
        if not data.get("type"):
            errors.append(f"节点 {node['id']} 缺少 data.type")
        if not data.get("title"):
            errors.append(f"节点 {node['id']} 缺少 data.title")

    type_by_id = {n["id"]: n["data"]["type"] for n in nodes}
    outputs_by_id = {n["id"]: node_outputs(n) for n in nodes}

    # ---------- 边：端点存在、sourceHandle 合法
    out_edges: dict[str, list[dict]] = {i: [] for i in ids}
    in_degree = {i: 0 for i in ids}
    for edge in edges:
        src, tgt = edge["source"], edge["target"]
        if src not in ids:
            errors.append(f"边源节点不存在：{edge['id']}")
            continue
        if tgt not in ids:
            errors.append(f"边目标节点不存在：{edge['id']}")
            continue
        out_edges[src].append(edge)
        in_degree[tgt] += 1
        handle = edge["sourceHandle"]
        stype = type_by_id[src]
        if stype == "question-classifier":
            classes = {c["id"] for c in nodes[ids.index(src)]["data"]["classes"]}
            if handle not in classes:
                errors.append(f"分类器 {src} 分支 handle 非法：{handle}")
        elif stype == "if-else":
            case_ids = {"true"} | {
                c["case_id"] for c in nodes[ids.index(src)]["data"]["cases"]
            }
            if handle not in case_ids | {"false"}:
                errors.append(f"条件分支 {src} handle 非法：{handle}")
        elif handle != "source":
            errors.append(f"普通节点 {src} 的 sourceHandle 应为 source，实际 {handle}")
        if edge.get("targetHandle") != "target":
            errors.append(f"边 {edge['id']} targetHandle 不是 target")
        if edge.get("type") != "custom":
            warnings.append(f"边 {edge['id']} type 不是 custom")

    # ---------- if-else / 分类器每个分支都必须有出边
    for node in nodes:
        nid, ntype = node["id"], node["data"]["type"]
        handles = {e["sourceHandle"] for e in out_edges[nid]}
        if ntype == "question-classifier":
            for cls in node["data"]["classes"]:
                if cls["id"] not in handles:
                    errors.append(f"分类器 {nid} 的 class {cls['id']} 没有对应分支边")
        if ntype == "if-else":
            for case in node["data"]["cases"]:
                if case["case_id"] not in handles:
                    errors.append(f"条件节点 {nid} 的 case {case['case_id']} 没有分支边")
            if "false" not in handles:
                errors.append(f"条件节点 {nid} 缺少 ELSE(false) 分支边")

    # ---------- 连通性：start 可达所有节点；非 end 节点必须有出边
    start_id = next((i for i in ids if type_by_id[i] == "start"), None)
    if not start_id:
        errors.append("缺少 start 节点")
    else:
        seen = {start_id}
        stack = [start_id]
        while stack:
            cur = stack.pop()
            for edge in out_edges[cur]:
                if edge["target"] not in seen:
                    seen.add(edge["target"])
                    stack.append(edge["target"])
        unreachable = sorted(set(ids) - seen)
        if unreachable:
            errors.append(f"从 start 不可达的节点：{unreachable}")

    for node in nodes:
        nid, ntype = node["id"], node["data"]["type"]
        if ntype != "end" and not out_edges[nid]:
            errors.append(f"非结束节点 {nid} 没有出边")
        if ntype == "end" and out_edges[nid]:
            errors.append(f"end 节点 {nid} 不应有出边")

    # ---------- 环检测（必须是有向无环图）
    color = {i: 0 for i in ids}  # 0 未访问 1 访问中 2 完成

    def dfs(cur: str) -> None:
        color[cur] = 1
        for edge in out_edges[cur]:
            nxt = edge["target"]
            if color[nxt] == 1:
                errors.append(f"检测到环：{cur} -> {nxt}")
            elif color[nxt] == 0:
                dfs(nxt)
        color[cur] = 2

    if start_id:
        dfs(start_id)

    # ---------- selector 全部指向真实节点与真实输出变量
    for node in nodes:
        nid = node["id"]
        for path, sel in iter_selectors(node.get("data", {})):
            src, var = sel
            if src not in ids:
                errors.append(f"{nid} 的 selector {path} 指向不存在的节点 {src}")
                continue
            if var not in outputs_by_id[src]:
                errors.append(
                    f"{nid} 的 selector {path} 引用了 {src} 未声明的输出变量 {var}"
                    f"（可用：{sorted(outputs_by_id[src])}）"
                )

    # ---------- 聚合器：9 路、output_type=string、末位为闲聊兜底
    agg = next((n for n in nodes if n["data"]["type"] == "variable-aggregator"), None)
    if agg:
        vars_list = agg["data"].get("variables", [])
        if len(vars_list) != 9:
            errors.append(f"聚合器路数 {len(vars_list)} != 9")
        if agg["data"].get("output_type") != "string":
            errors.append("聚合器 output_type 应为 string")
        if vars_list and vars_list[-1] != ["smalltalk_reply", "output"]:
            errors.append("聚合器末位应为 smalltalk_reply.output（真兜底）")

    # ---------- 合规链路（task-9）：8 节点，接在 merge_reply 之后、end 之前
    compliance_ids = [
        "compliance_scan",
        "compliance_if",
        "compliance_llm",
        "compliance_verify",
        "compliance_if2",
        "compliance_fallback",
        "compliance_fallback2",
        "compliance_finalize",
    ]
    for cid in compliance_ids:
        if cid not in ids:
            errors.append(f"缺少合规链路节点 {cid}")
    merge_out = {e["target"] for e in out_edges.get("merge_reply", [])}
    if merge_out != {"compliance_scan"}:
        errors.append(f"merge_reply 的出边应只有 compliance_scan，实际 {sorted(merge_out)}")
    fin_out = {e["target"] for e in out_edges.get("compliance_finalize", [])}
    if fin_out != {"sources_attach"}:
        errors.append(f"compliance_finalize 的出边应只有 sources_attach，实际 {sorted(fin_out)}")
    attach_out = {e["target"] for e in out_edges.get("sources_attach", [])}
    if attach_out != {"end"}:
        errors.append(f"sources_attach 的出边应只有 end，实际 {sorted(attach_out)}")
    if "compliance_scan" in ids:
        scan_data = nodes[ids.index("compliance_scan")]["data"]
        scan_code = scan_data.get("code", "")
        words_file = ROOT / "tools" / "dify" / "compliance_words.json"
        if not words_file.exists():
            errors.append("缺少 tools/dify/compliance_words.json")
        else:
            words = json.loads(words_file.read_text(encoding="utf-8"))
            flat = [w for group in words["level1"].values() for w in group]
            missing = [w for w in flat if f'"{w}"' not in scan_code]
            if missing:
                errors.append(
                    f"compliance_scan 代码缺少 level1 词 {len(missing)} 个（如 {missing[:5]}）"
                )
            if words["fallback"]["hit_level1"] not in json.dumps(
                nodes, ensure_ascii=False
            ):
                errors.append("一级拦截兜底话术（fallback.hit_level1）未出现在 graph 中")
            if words["fallback"]["llm_unfixable"] not in json.dumps(
                nodes, ensure_ascii=False
            ):
                errors.append("不可修正兜底话术（fallback.llm_unfixable）未出现在 graph 中")
        if "text" not in (scan_data.get("outputs") or {}):
            errors.append("compliance_scan 缺少 text 输出（下游 LLM 需要）")
    if "compliance_llm" in ids:
        llm_data = nodes[ids.index("compliance_llm")]["data"]
        system_text = "".join(
            item.get("text", "") for item in llm_data.get("prompt_template", [])
        )
        if "{{#compliance_scan.text#}}" not in system_text:
            errors.append("compliance_llm 的 System Prompt 未注入 {{#compliance_scan.text#}}")
        if "合规审核员" not in system_text:
            errors.append("compliance_llm 未使用 compliance_words.json 的合规 Prompt")
        if llm_data.get("reasoning_format") != "separated":
            errors.append("compliance_llm 应设置 reasoning_format=separated")

    # ---------- end 输出 response + compliance_flag（值来自 compliance_finalize）
    end_node = next((n for n in nodes if n["data"]["type"] == "end"), None)
    if end_node:
        outs = {
            o.get("variable"): o.get("value_selector")
            for o in end_node["data"].get("outputs", [])
        }
        if outs.get("response") != ["sources_attach", "response"]:
            errors.append(f"end.response selector 意外：{outs.get('response')}")
        if outs.get("compliance_flag") != ["sources_attach", "compliance_flag"]:
            errors.append(f"end.compliance_flag selector 意外：{outs.get('compliance_flag')}")
        if outs.get("sources") != ["sources_attach", "sources"]:
            errors.append(f"end.sources selector 意外：{outs.get('sources')}")
        if len(outs) != 3:
            warnings.append(f"end 输出变量 {len(outs)} 个（预期 response + sources + compliance_flag）")

    # ---------- 坐标：同列不重叠（按 x 分组，检查 y 方向间距 > 节点高度）
    by_x: dict[float, list[dict]] = {}
    for node in nodes:
        by_x.setdefault(node["position"]["x"], []).append(node)
    for x, group in by_x.items():
        group.sort(key=lambda n: n["position"]["y"])
        for prev, cur in zip(group, group[1:]):
            gap = cur["position"]["y"] - (prev["position"]["y"] + prev.get("height", 98))
            if gap < 20:
                warnings.append(
                    f"同列 x={x} 节点 {prev['id']} 与 {cur['id']} 纵向间距 {gap}px 偏小"
                )

    # ---------- 变量占位符：{{#node.var#}} 的 node 必须存在
    ph_re = re.compile(r"\{\{#([a-zA-Z0-9_]{1,50})\.([a-zA-Z_][a-zA-Z0-9_]{0,29})#\}\}")
    text_nodes = [n for n in nodes if n["data"]["type"] in ("llm", "http-request", "template-transform")]
    for node in text_nodes:
        blob = json.dumps(node["data"], ensure_ascii=False)
        for src, var in ph_re.findall(blob):
            if src not in ids:
                errors.append(f"{node['id']} 占位符引用了不存在的节点：{{{{#{src}.{var}#}}}}")
            elif var not in outputs_by_id[src]:
                errors.append(f"{node['id']} 占位符引用未声明输出：{{{{#{src}.{var}#}}}}")

    # ---------- HTTP 节点规则
    for node in nodes:
        data = node["data"]
        if data["type"] != "http-request":
            continue
        if data["method"] == "post" and data.get("retry_config", {}).get("retry_enabled"):
            errors.append(f"POST 节点 {node['id']} 不应开启重试（会重复建单）")
        if data["body"]["type"] == "json" and len(data["body"]["data"]) != 1:
            errors.append(f"HTTP {node['id']} json body 必须恰好 1 条 BodyData")
        if "host.docker.internal" not in data["url"]:
            warnings.append(f"HTTP {node['id']} URL 不是 host.docker.internal：{data['url']}")

    # ---------- 知识检索
    for node in nodes:
        data = node["data"]
        if data["type"] != "knowledge-retrieval":
            continue
        if data["dataset_ids"] != ["403fbc9d-3c82-4077-8033-6761821f68f3"]:
            errors.append(f"检索节点 {node['id']} dataset_id 不是汽车销售知识库")
        cfg = data["multiple_retrieval_config"]
        if cfg["top_k"] != 3 or cfg["score_threshold"] != 0.5:
            errors.append(f"检索节点 {node['id']} 参数应为 top_k=3 / 阈值 0.5")

    # ---------- LLM 节点模型
    for node in nodes:
        data = node["data"]
        if data["type"] not in ("llm", "question-classifier", "parameter-extractor"):
            continue
        model = data.get("model", {})
        if model.get("provider") != "langgenius/deepseek/deepseek":
            errors.append(f"{node['id']} 模型 provider 不是 deepseek")
        if model.get("name") != "deepseek-flash":
            errors.append(f"{node['id']} 模型名不是 deepseek-flash")

    # ---------- 输出
    size = JSON_PATH.stat().st_size
    print(f"file: {JSON_PATH}")
    print(f"nodes={len(nodes)} edges={len(edges)} bytes={size}")
    print(f"node types: {sorted({n['data']['type'] for n in nodes})}")
    if warnings:
        print(f"\n[warnings] {len(warnings)}")
        for w in warnings:
            print("  -", w)
    if errors:
        print(f"\n[errors] {len(errors)}")
        for e in errors:
            print("  -", e)
        return 1
    print("\nOK: 结构校验全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
