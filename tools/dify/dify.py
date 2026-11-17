#!/usr/bin/env python3
"""宿主机侧的 Dify 控制台 API 调用入口（仅标准库）。

把 tools/dify/dify_console.py 同步进 docker-api-1:/tmp，用容器自带的
/app/api/.venv/bin/python 执行，从而复用容器内的 requests 与内网地址 127.0.0.1:5001。

用法：
    python tools/dify/dify.py login
    python tools/dify/dify.py models text-embedding
    python tools/dify/dify.py job tools/dify/jobs/xxx.json

job 文件内容见 dify_console.py 的 cmd_job 文档（method/path/json/params/files/data/out/raw）。
job 模式会自动把文件与 job 描述拷进容器（/tmp/dify_jobs/）。
"""

from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys
import uuid

HERE = os.path.dirname(os.path.abspath(__file__))
CONSOLE = os.path.join(HERE, "dify_console.py")
CONTAINER = "docker-api-1"
REMOTE = "/tmp/dify_console.py"
REMOTE_JOB_DIR = "/tmp/dify_jobs"


def run(cmd: list[str], **kw) -> subprocess.CompletedProcess:
    proc = subprocess.run(cmd, capture_output=True, **kw)
    return proc


def sync_console() -> None:
    with open(CONSOLE, "rb") as f:
        payload = f.read()
    proc = subprocess.run(
        ["docker", "exec", "-i", CONTAINER, "sh", "-c", f"cat > {REMOTE}"],
        input=payload,
        capture_output=True,
    )
    if proc.returncode != 0:
        sys.stderr.write(proc.stderr.decode("utf-8", "replace"))
        raise SystemExit("同步 dify_console.py 到容器失败")


def exec_console(args: list[str]) -> int:
    inner = "cd /app/api && .venv/bin/python " + REMOTE + " " + " ".join(shlex.quote(a) for a in args)
    proc = subprocess.run(["docker", "exec", CONTAINER, "sh", "-lc", inner])
    return proc.returncode


def prepare_job(job_path: str) -> tuple[str, str]:
    """把 job 及其引用文件拷到容器，返回（容器内 job 路径, 容器内 job 目录）。"""
    with open(job_path, "rb") as f:
        job = json.load(f)
    token = uuid.uuid4().hex[:10]
    job_dir = f"{REMOTE_JOB_DIR}/{token}"
    subprocess.run(["docker", "exec", CONTAINER, "mkdir", "-p", job_dir], capture_output=True)
    # 逐个拷贝 files[].path
    for spec in job.get("files") or []:
        src = spec["path"]
        dst = f"{job_dir}/{os.path.basename(src)}"
        spec["path"] = dst
        proc = subprocess.run(["docker", "cp", src, f"{CONTAINER}:{dst}"], capture_output=True)
        if proc.returncode != 0:
            sys.stderr.write(proc.stderr.decode("utf-8", "replace"))
            raise SystemExit(f"拷贝 {src} 到容器失败")
    if job.get("out"):
        job["out"] = f"{job_dir}/{os.path.basename(job['out'])}"
    data = json.dumps(job, ensure_ascii=False).encode("utf-8")
    remote_job = f"{job_dir}/job.json"
    proc = subprocess.run(
        ["docker", "exec", "-i", CONTAINER, "sh", "-c", f"cat > {remote_job}"],
        input=data,
        capture_output=True,
    )
    if proc.returncode != 0:
        raise SystemExit("写入容器内 job.json 失败")
    return remote_job, job_dir


def pull_out(job_path: str, job_dir: str) -> None:
    with open(job_path, "rb") as f:
        job = json.load(f)
    out = job.get("out")
    if not out:
        return
    dst = out
    remote = f"{job_dir}/{os.path.basename(out)}"
    proc = subprocess.run(["docker", "cp", f"{CONTAINER}:{remote}", dst], capture_output=True)
    if proc.returncode == 0:
        print(f"saved {dst}")
    else:
        sys.stderr.write(proc.stderr.decode("utf-8", "replace"))


def main() -> None:
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    sync_console()
    args = sys.argv[1:]
    if args[0] == "job":
        if len(args) < 2:
            raise SystemExit("用法: dify.py job <job.json>")
        job_path = args[1]
        remote_job, job_dir = prepare_job(job_path)
        code = exec_console(["job", "--file", remote_job])
        pull_out(job_path, job_dir)
        raise SystemExit(code)
    raise SystemExit(exec_console(args))


if __name__ == "__main__":
    main()
