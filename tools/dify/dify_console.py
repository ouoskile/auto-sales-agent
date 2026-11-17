#!/usr/bin/env python3
"""Dify console API 客户端（在 docker-api-1 容器内以 .venv/bin/python 运行）。

用法（宿主机侧通过 docker exec 调用，见 tools/dify/dify.py 的包装）：
    python dify_console.py login
    python dify_console.py models [text-embedding|llm|all]
    python dify_console.py get /console/api/datasets
    python dify_console.py post /console/api/datasets --json-file /tmp/body.json
    python dify_console.py post /console/api/datasets --json-str '{"name":"x"}'
    python dify_console.py upload /console/api/datasets/<id>/document/create-by-file --file /tmp/kb/01.md --field indexing_technique=high_quality
    python dify_console.py export-app <app_id> --out /tmp/app_dsl.yml
    python dify_console.py import-app --file /tmp/app_dsl.yml

认证要点：Dify 1.19 控制台使用 cookie 会话（access_token + csrf_token），
所有 console 请求（含 GET）都必须带 X-CSRF-Token 头且与 csrf_token cookie 一致。
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import sys

import requests

BASE = os.environ.get("DIFY_BASE", "http://127.0.0.1:5001")
# 账号与密码只从环境变量读取，不写入仓库；运行前先 export DIFY_EMAIL / DIFY_PASSWORD
EMAIL = os.environ.get("DIFY_EMAIL", "")
PASSWORD = os.environ.get("DIFY_PASSWORD", "")


class Client:
    def __init__(self) -> None:
        self.s = requests.Session()
        self.login()

    def login(self) -> None:
        if not EMAIL or not PASSWORD:
            raise SystemExit("请先设置环境变量 DIFY_EMAIL 与 DIFY_PASSWORD（管理员账号），仓库中不保存凭据")
        body = {
            "email": EMAIL,
            "password": base64.b64encode(PASSWORD.encode()).decode(),
            "remember_me": True,
            "language": "zh-Hans",
        }
        r = self.s.post(f"{BASE}/console/api/login", json=body, timeout=30)
        if r.status_code != 200 or r.json().get("result") != "success":
            raise SystemExit(f"login failed: {r.status_code} {r.text[:300]}")
        csrf = self.s.cookies.get("csrf_token")
        if not csrf:
            raise SystemExit("login ok but no csrf_token cookie")
        self.s.headers.update({"X-CSRF-Token": csrf})

    def request(self, method: str, path: str, **kwargs):
        url = path if path.startswith("http") else f"{BASE}{path}"
        r = self.s.request(method, url, timeout=120, **kwargs)
        return r


def dump(r: requests.Response) -> None:
    ctype = r.headers.get("content-type", "")
    if "application/json" in ctype:
        try:
            print(json.dumps(r.json(), ensure_ascii=False, indent=2))
        except ValueError:
            print(r.text)
    else:
        print(r.text)
    print(f"[status {r.status_code}]", file=sys.stderr)


def cmd_login(c: Client) -> None:
    emb = c.request("GET", "/console/api/workspaces/current/models/model-types/text-embedding")
    llm = c.request("GET", "/console/api/workspaces/current/models/model-types/llm")
    emb_items = []
    if emb.status_code == 200:
        for prov in emb.json().get("data") or []:
            emb_items.extend(m.get("model") for m in prov.get("models") or [])
    llm_items = []
    if llm.status_code == 200:
        for prov in llm.json().get("data") or []:
            llm_items.extend(m.get("model") for m in prov.get("models") or [])
    print(
        json.dumps(
            {
                "login": "ok",
                "embedding_models": emb_items,
                "llm_models": llm_items[:10],
                "llm_count": len(llm_items),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


def cmd_models(c: Client, kind: str) -> None:
    kinds = ["text-embedding", "llm", "rerank", "speech2text"] if kind == "all" else [kind]
    out = {}
    for k in kinds:
        r = c.request("GET", f"/console/api/workspaces/current/models/model-types/{k}")
        if r.status_code != 200:
            out[k] = {"error": r.status_code, "body": r.text[:200]}
            continue
        items = []
        for prov in r.json().get("data") or []:
            for m in prov.get("models") or []:
                items.append(
                    {
                        "provider": prov.get("provider"),
                        "model": m.get("model"),
                        "model_type": m.get("model_type"),
                        "status": m.get("status"),
                    }
                )
        out[k] = items
    print(json.dumps(out, ensure_ascii=False, indent=2))


def body_from_args(args) -> dict | None:
    if getattr(args, "json_str", None):
        return json.loads(args.json_str)
    if getattr(args, "json_file", None):
        with open(args.json_file, "rb") as f:
            return json.load(f)
    return None


def cmd_request(c: Client, args, method: str) -> None:
    kwargs: dict = {}
    body = body_from_args(args)
    if body is not None:
        kwargs["json"] = body
    if getattr(args, "params", None):
        kwargs["params"] = dict(p.split("=", 1) for p in args.params)
    files = {}
    data = {}
    for spec in getattr(args, "file", None) or []:
        path = spec
        field = "file"
        if "=" in spec:
            field, path = spec.split("=", 1)
        files[field] = (os.path.basename(path), open(path, "rb"))
    for spec in getattr(args, "field", None) or []:
        k, v = spec.split("=", 1)
        data[k] = v
    try:
        if files:
            kwargs["files"] = files
            kwargs["data"] = data
        r = c.request(method, args.path, **kwargs)
        dump(r)
    finally:
        for f in files.values():
            f[1].close()


def cmd_export(c: Client, app_id: str, out: str | None) -> None:
    r = c.request("GET", f"/console/api/apps/{app_id}/export?include_secret=false")
    if r.status_code != 200:
        raise SystemExit(f"export failed: {r.status_code} {r.text[:300]}")
    if out:
        with open(out, "wb") as f:
            f.write(r.content)
        print(f"saved {out} ({len(r.content)} bytes)")
    else:
        sys.stdout.write(r.text)


def cmd_import(c: Client, path: str) -> None:
    with open(path, "rb") as f:
        content = f.read().decode("utf-8")
    r = c.request("POST", "/console/api/apps/imports", json={"mode": "yaml-content", "yaml_content": content})
    dump(r)


def cmd_job(c: Client, path: str) -> None:
    """通用任务模式：从 JSON 文件读取 {method,path,json,params,files,data,out,raw}。

    files 形如 [{"field": "file", "path": "/tmp/kb/01.md"}]，用于 multipart 上传；
    out 指定时把原始响应写入该路径（适合下载 DSL / 导出）。
    """
    with open(path, "rb") as f:
        job = json.load(f)
    method = job.get("method", "GET").upper()
    kwargs: dict = {}
    if job.get("params"):
        kwargs["params"] = job["params"]
    if job.get("json") is not None:
        kwargs["json"] = job["json"]
    if job.get("data"):
        kwargs["data"] = job["data"]
    handles = []
    try:
        if job.get("files"):
            files = {}
            for spec in job["files"]:
                fh = open(spec["path"], "rb")
                handles.append(fh)
                files[spec.get("field", "file")] = (os.path.basename(spec["path"]), fh)
            kwargs["files"] = files
            kwargs.setdefault("data", {})
        r = c.request(method, job["path"], **kwargs)
        if job.get("out"):
            with open(job["out"], "wb") as f:
                f.write(r.content)
            print(json.dumps({"status": r.status_code, "saved": job["out"], "bytes": len(r.content)}, ensure_ascii=False))
        elif job.get("raw"):
            sys.stdout.write(r.text)
            print(f"[status {r.status_code}]", file=sys.stderr)
        else:
            dump(r)
    finally:
        for fh in handles:
            fh.close()


def main() -> None:
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("login")
    pj = sub.add_parser("job")
    pj.add_argument("--file", required=True)

    pm = sub.add_parser("models")
    pm.add_argument("kind", nargs="?", default="text-embedding")

    for name in ("get", "post", "put", "delete", "upload"):
        sp = sub.add_parser(name)
        sp.add_argument("path")
        sp.add_argument("--json-str", dest="json_str")
        sp.add_argument("--json-file", dest="json_file")
        sp.add_argument("--params", nargs="*")
        sp.add_argument("--file", nargs="*")
        sp.add_argument("--field", nargs="*")

    pe = sub.add_parser("export-app")
    pe.add_argument("app_id")
    pe.add_argument("--out")

    pi = sub.add_parser("import-app")
    pi.add_argument("--file", required=True)

    args = p.parse_args()
    c = Client()

    if args.cmd == "login":
        cmd_login(c)
    elif args.cmd == "models":
        cmd_models(c, args.kind)
    elif args.cmd == "job":
        cmd_job(c, args.file)
    elif args.cmd == "export-app":
        cmd_export(c, args.app_id, args.out)
    elif args.cmd == "import-app":
        cmd_import(c, args.file)
    else:
        method = {"get": "GET", "post": "POST", "put": "PUT", "delete": "DELETE", "upload": "POST"}[args.cmd]
        cmd_request(c, args, method)


if __name__ == "__main__":
    main()
