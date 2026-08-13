#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
deploy_gate.py — 岐黄智脑商业化平台(8602) 部署门禁脚本
========================================================
把铁律#18 SOP 的「阶段③ 提交push → 阶段④ 轮询CI四job全绿 → 阶段⑤ 部署后服务器实测」
自动化成一条命令。git push 之后运行它，自动确认部署「真成功」，不再靠肉眼猜。

流程
----
1. 读取当前 HEAD commit
2. 调 GitHub API 定位该 commit 对应的最新 Actions run（找不到则提示手动 workflow_dispatch）
3. 轮询该 run 直到 completed，检查四个 job 结论：
   - 代码检查 (lint) / 测试 Python 3.13 / 测试 Python 3.12 / 部署到生产服务器
   - skipped 视为通过（如 docs 改动触发的 run，deploy 按设计跳过）
4. 部署完成后实测生产服务器：health + 关键页面 + 关键端点
5. 输出绿/红报告；exit code 0 = 全绿，1 = 有红

依赖
----
- 环境变量 GH_TOKEN：GitHub PAT，需 actions:read 权限（触发 dispatch 还需 workflow 权限）
- Python 3.8+ 标准库，无第三方依赖、无 curl 依赖（Windows 沙箱下 curl 可能被拦）

用法
----
    python deploy_gate.py                         # 默认 repo=Scott8010/qihuang-platform, server=111.231.63.73:8602
    python deploy_gate.py --server http://x:8602  # 指定服务器
    python deploy_gate.py --timeout 900           # 轮询超时(秒)
    python deploy_gate.py --trigger               # 若找不到 run，用 GH_TOKEN 触发 workflow_dispatch 后轮询
"""
import os
import sys
import time
import json
import argparse
import subprocess
import urllib.request
import urllib.error

GITHUB_API = "https://api.github.com"
DEFAULT_REPO = "Scott8010/qihuang-platform"
# 注：生产服务只监听 127.0.0.1:8602，对外经 nginx 反代 + 强制 HTTPS + Host 匹配，
# 故门禁必须打域名(https)而非直连 IP:Port（直连会连不上，造成假阴性）。
DEFAULT_SERVER = "https://yshealth.com.cn"
EXPECTED_JOBS = ["代码检查", "测试 Python 3.13", "测试 Python 3.12", "部署到生产服务器"]
# 路径实测：健康检查 + React 控制台 + 旧版控制端
SERVER_PATHS = ["/platform/health", "/admin/", "/admin-static/admin.html"]
# fortune Agent 专项：401=路由已注册且鉴权生效(已上线)，404=未上线
FORTUNE_PATH = "/api/v1/agent/fortune/dashboard"


def _git_head() -> str:
    return subprocess.check_output(["git", "rev-parse", "HEAD"]).decode().strip()


def api_get(path: str, token: str) -> dict:
    url = GITHUB_API + path
    req = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    })
    with urllib.request.urlopen(req, timeout=25) as r:
        return json.load(r)


def api_post(path: str, token: str, payload: dict) -> int:
    url = GITHUB_API + path
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST", headers={
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "Content-Type": "application/json",
        "X-GitHub-Api-Version": "2022-11-28",
    })
    try:
        with urllib.request.urlopen(req, timeout=25) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code


def find_run(repo: str, head_sha: str, token: str, retries: int = 8, wait: int = 10):
    for i in range(retries):
        try:
            data = api_get(f"/repos/{repo}/actions/runs?per_page=20&head_sha={head_sha}", token)
        except Exception as e:
            print(f"⚠️ 查询 runs 失败: {e}")
            time.sleep(wait)
            continue
        runs = data.get("workflow_runs", [])
        if runs:
            return runs[0]
        if i < retries - 1:
            print(f"  ⏳ run 尚未生成，等 {wait}s ({i+1}/{retries})")
            time.sleep(wait)
    return None


def poll_run(repo: str, run_id: str, token: str, timeout: int):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            run = api_get(f"/repos/{repo}/actions/runs/{run_id}", token)
        except Exception as e:
            print(f"⚠️ 轮询 run 失败: {e}")
            time.sleep(15)
            continue
        if run.get("status") == "completed":
            return run
        print(f"  ⏳ run {run_id} status={run.get('status')} ... 等 15s")
        time.sleep(15)
    return None


def get_jobs(repo: str, run_id: str, token: str):
    try:
        data = api_get(f"/repos/{repo}/actions/runs/{run_id}/jobs?per_page=50", token)
        return data.get("jobs", [])
    except Exception:
        return []


def check_server(base: str, paths: list):
    results = []
    for p in paths:
        url = base.rstrip("/") + p
        try:
            # 用 GET（部分路由如 /platform/health 不接受 HEAD）
            req = urllib.request.Request(url, method="GET")
            with urllib.request.urlopen(req, timeout=12) as r:
                results.append((p, r.status, "ok"))
        except urllib.error.HTTPError as e:
            results.append((p, e.code, "http_err"))
        except Exception as e:
            results.append((p, 0, str(e)[:50]))
    return results


def main():
    ap = argparse.ArgumentParser(description="8602 部署门禁脚本")
    ap.add_argument("--repo", default=DEFAULT_REPO)
    ap.add_argument("--server", default=DEFAULT_SERVER)
    ap.add_argument("--timeout", type=int, default=600)
    ap.add_argument("--trigger", action="store_true",
                    help="若找不到对应 run，用 GH_TOKEN 触发 workflow_dispatch 后轮询")
    args = ap.parse_args()

    token = os.environ.get("GH_TOKEN")
    if not token:
        print("❌ 未找到 GH_TOKEN 环境变量（需要 GitHub PAT，权限 actions:read）")
        sys.exit(1)

    try:
        head = _git_head()
    except Exception as e:
        print(f"❌ 读取 git HEAD 失败（请在仓库根目录运行）: {e}")
        sys.exit(1)

    print(f"🔍 HEAD={head[:8]}  定位 CI run ...")
    run = find_run(args.repo, head, token)
    if not run:
        if args.trigger:
            print("🚀 未找到 run，尝试 workflow_dispatch 触发 ...")
            # 取第一个 workflow id
            try:
                wf = api_get(f"/repos/{args.repo}/actions/workflows", token)
                wid = wf.get("workflows", [{}])[0].get("id")
                if wid:
                    code = api_post(f"/repos/{args.repo}/actions/workflows/{wid}/dispatches",
                                    token, {"ref": "main"})
                    print(f"  dispatch -> HTTP {code}")
                    time.sleep(10)
                    run = find_run(args.repo, head, token)
            except Exception as e:
                print(f"⚠️ 触发失败: {e}")
        if not run:
            print("⚠️ 仍未找到对应 run（可能 push 事件未触发；可加 --trigger 自动触发，或去 GitHub 手动触发）")
            sys.exit(1)

    print(f"📋 RUN {run['id']}  status={run['status']}  conclusion={run['conclusion']}")
    run = poll_run(args.repo, run["id"], token, args.timeout)
    if not run:
        print("⏱️ 轮询超时，run 未完成")
        sys.exit(1)

    jobs = get_jobs(args.repo, run["id"], token)
    print(f"\n=== CI Jobs ({len(jobs)}) ===")
    all_ok = True
    for j in jobs:
        name = j.get("name", "?")
        concl = j.get("conclusion")
        if concl == "success":
            mark = "✅"
        elif concl == "skipped":
            mark = "⚠️(skipped)"
        else:
            mark = "❌"
            all_ok = False
        print(f"  {mark}  {name}")
        if name in EXPECTED_JOBS and concl not in ("success", "skipped"):
            all_ok = False

    print(f"\n=== 服务器实测 {args.server} ===")
    srv = check_server(args.server, SERVER_PATHS)
    for p, code, st in srv:
        ok = code in (200, 301, 307)
        mark = "✅" if ok else "❌"
        print(f"  {mark}  HTTP {code}  {p}")
        if not ok:
            all_ok = False

    # fortune Agent 专项校验：401/200=路由已注册(上线)；404=未上线
    print(f"\n=== fortune Agent 专项 {args.server}{FORTUNE_PATH} ===")
    fg = check_server(args.server, [FORTUNE_PATH])
    for p, code, st in fg:
        ok = code in (200, 401)
        mark = "✅" if ok else "❌"
        hint = "（路由已注册·鉴权生效=已上线）" if code == 401 else ("（已上线）" if code == 200 else "（404=路由未注册）")
        print(f"  {mark}  HTTP {code}  {hint}")
        if not ok:
            all_ok = False

    print("\n" + ("🟢 部署门禁通过：CI 全绿 + 服务器实测 OK" if all_ok
                   else "🔴 部署门禁未通过：见上方 ❌ 项"))
    sys.exit(0 if all_ok else 1)


if __name__ == "__main__":
    main()
