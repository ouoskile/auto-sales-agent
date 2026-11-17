#!/usr/bin/env python3
"""把 docs/dify/knowledge/*.md 批量导入 Dify 知识库（宿主机侧编排脚本）。

流程（每个文档）：
1. POST /console/api/files/upload 上传文件 -> upload_file_id
2. POST /console/api/datasets/{dataset_id}/documents 建文档 -> document_id
3. 轮询 GET /console/api/datasets/{dataset_id}/documents/{document_id}/indexing-status

复用 tools/dify/dify.py 的 job 模式（自动把文件与 job.json 拷进 docker-api-1 容器）。
用法：
    python tools/dify/import_kb.py
    python tools/dify/import_kb.py --files 01_门店车型库.md 02_销售标准话术库.md
    python tools/dify/import_kb.py --status
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
MANIFEST = os.path.join(HERE, "kb_manifest.json")
KB_DIR = os.path.join(ROOT, "docs", "dify", "knowledge")
DATASET_ID = "403fbc9d-3c82-4077-8033-6761821f68f3"


def run_job(payload: dict) -> dict:
    """写临时 job 文件 -> 调 dify.py -> 解析 stdout JSON。"""
    os.makedirs(JOBS, exist_ok=True)
    tmp = os.path.join(JOBS, f"_auto_{int(time.time() * 1000)}_{os.getpid()}.json")
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


def delete_document(document_id: str) -> dict:
    try:
        return run_job(
            {
                "method": "DELETE",
                "path": f"/console/api/datasets/{DATASET_ID}/documents/{document_id}",
            }
        )
    except RuntimeError as exc:
        # DELETE 常返回 204 No Content（无 JSON body），dify.py 会以 [status 204] 表达成功
        if "204" in str(exc):
            return {"status": 204}
        raise


def upload(path: str) -> str:
    res = run_job(
        {
            "method": "POST",
            "path": "/console/api/files/upload",
            "files": [{"field": "file", "path": path}],
            "data": {"source": "datasets"},
        }
    )
    return res["id"]


def create_document(file_id: str) -> list[str]:
    res = run_job(
        {
            "method": "POST",
            "path": f"/console/api/datasets/{DATASET_ID}/documents",
            "json": {
                "indexing_technique": "high_quality",
                "data_source": {
                    "info_list": {
                        "data_source_type": "upload_file",
                        "file_info_list": {"file_ids": [file_id]},
                    }
                },
                "process_rule": {"mode": "automatic"},
                "doc_form": "text_model",
                "doc_language": "Chinese",
            },
        }
    )
    return [d["id"] for d in res.get("documents", [])]


def indexing_status(document_ids: list[str]) -> list[dict]:
    res = run_job(
        {
            "method": "GET",
            "path": f"/console/api/datasets/{DATASET_ID}/documents",
            "params": {"page": 1, "limit": 50},
        }
    )
    rows = res.get("data", [])
    wanted = set(document_ids)
    return [
        {
            "id": r["id"],
            "name": r.get("name"),
            "status": r.get("indexing_status"),
            "segments": r.get("segment_count"),
            "tokens": r.get("tokens"),
            "words": r.get("word_count"),
            "enabled": r.get("enabled"),
        }
        for r in rows
        if r["id"] in wanted
    ]


def load_manifest(path: str = MANIFEST) -> dict:
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"dataset_id": DATASET_ID, "documents": []}


def save_manifest(manifest: dict, path: str = MANIFEST) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)


def default_files(kb_dir: str = KB_DIR) -> list[str]:
    names = sorted(n for n in os.listdir(kb_dir) if n.endswith(".md"))
    return [os.path.join(kb_dir, n) for n in names]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--files", nargs="*", default=None, help="仅导入指定文件名（kb-dir 内）")
    parser.add_argument("--status", action="store_true", help="只查询索引状态")
    parser.add_argument("--kb-dir", default=KB_DIR, help="知识库文档目录（默认 docs/dify/knowledge）")
    parser.add_argument("--manifest", default=MANIFEST, help="manifest 路径（默认 tools/dify/kb_manifest.json）")
    parser.add_argument("--purge", action="store_true", help="先删除 manifest 中已登记的 Dify 文档再导入")
    parser.add_argument("--delete-only", action="store_true", help="只删除 manifest 中登记的文档，不导入")
    args = parser.parse_args()

    manifest = load_manifest(args.manifest)

    if args.status:
        ids = [d["document_id"] for d in manifest["documents"]]
        if not ids:
            print("manifest 为空，先导入")
            return 1
        for row in indexing_status(ids):
            print(json.dumps(row, ensure_ascii=False))
        return 0

    if (args.purge or args.delete_only) and manifest["documents"]:
        for doc in list(manifest["documents"]):
            print(f"DELETE {doc['name']} ({doc['document_id']})", flush=True)
            try:
                delete_document(doc["document_id"])
            except Exception as exc:  # noqa: BLE001 - 删除失败不阻塞后续导入
                print(f"  delete failed: {exc}", flush=True)
        manifest["documents"] = []
        save_manifest(manifest, args.manifest)
    if args.delete_only:
        print("delete-only: 删除完成，未导入")
        return 0

    paths = default_files(args.kb_dir)
    if args.files:
        paths = [os.path.join(args.kb_dir, name) for name in args.files]

    known = {d["name"] for d in manifest["documents"]}
    for path in paths:
        name = os.path.basename(path)
        if name in known:
            print(f"SKIP {name}（manifest 已有）")
            continue
        print(f"UPLOAD {name}", flush=True)
        file_id = upload(path)
        doc_ids = create_document(file_id)
        print(f"  file_id={file_id} documents={doc_ids}", flush=True)
        for doc_id in doc_ids:
            manifest["documents"].append(
                {"name": name, "file_id": file_id, "document_id": doc_id, "source": os.path.relpath(path, ROOT)}
            )
        save_manifest(manifest, args.manifest)

    print("\n轮询索引状态：")
    ids = [d["document_id"] for d in manifest["documents"]]
    for attempt in range(20):
        rows = indexing_status(ids)
        states = {r["id"]: r["status"] for r in rows}
        print(f"try {attempt + 1}: " + json.dumps(states, ensure_ascii=False), flush=True)
        if rows and all(r["status"] in ("completed", "error") for r in rows) and len(rows) == len(ids):
            for row in rows:
                print(json.dumps(row, ensure_ascii=False))
            return 0 if all(r["status"] == "completed" for r in rows) else 2
        time.sleep(5)
    print("索引轮询超时")
    return 3


if __name__ == "__main__":
    raise SystemExit(main())
