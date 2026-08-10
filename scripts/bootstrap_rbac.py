#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
岐黄智脑 · RBAC 初始化与体检脚本（幂等，可重复执行）

做三件事：
  1. 把 admin 收编进 users 表 —— 建库内正式账号并绑定 super_admin，
     环境变量口令从此降级为「库不可用时的应急通道」。
  2. 补齐空壳角色权限 —— org_admin / teacher / edu_researcher 原本 0 权限。
  3. 清理测试脏用户 —— 用户名匹配 vh_pw_* 或用户名为空的残留账号。

用法：
    python scripts/bootstrap_rbac.py                      # 打本地 8602
    E2E_BASE=https://yshealth.com.cn python scripts/bootstrap_rbac.py
    ... --dry-run                                          # 只体检不改动
"""
from __future__ import annotations

import os
import re
import sys
import json
import argparse
import urllib.error
import urllib.request

BASE = os.getenv("E2E_BASE", "http://127.0.0.1:8602").rstrip("/")
ADMIN_USER = os.getenv("QH_ADMIN_USER", "admin")
ADMIN_PASS = os.getenv("QH_ADMIN_PASS", "QhAdmin@2026")

# 脏数据判定：验证脚本留下的临时账号 + 用户名为空的坏记录
DIRTY_USERNAME_RE = re.compile(r"^(vh_pw_\d+|vh_direct_\d+|e2e_\w+|test_user_\d+)$")

# 空壳角色补齐方案（权限 code 见 GET /admin/v1/permissions）
ROLE_PERM_PLAN: dict[str, list[str]] = {
    # 机构管理员：管本机构的人和组织 + 看监控审计 + 通用核心能力
    # 有意不给 core:diagnose / core:prescription:review —— 管理岗不碰诊疗
    "org_admin": [
        "admin:user:manage", "admin:org:manage",
        "admin:monitor:view", "admin:audit:view",
        "core:graph:query", "core:agent:chat", "core:literature:search",
    ],
    # 教师：教学三件套 + 图谱查询 + AI 对话
    "teacher": [
        "edu:coach:session", "edu:exam:manage", "edu:progress:view",
        "core:graph:query", "core:agent:chat",
    ],
    # 教研专家：教师全集 + 文献检索 + 3D 教具 + 审计查看
    "edu_researcher": [
        "edu:coach:session", "edu:exam:manage", "edu:progress:view",
        "core:graph:query", "core:agent:chat", "core:literature:search",
        "module:3d", "admin:audit:view",
    ],
}

TOKEN = ""
CHANGES: list[str] = []
SKIPS: list[str] = []


def call(method: str, path: str, body: dict | None = None) -> tuple[int, dict]:
    url = f"{BASE}{path}"
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    if TOKEN:
        req.add_header("Authorization", f"Bearer {TOKEN}")
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, json.loads(r.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        raw = e.read().decode() or "{}"
        try:
            return e.code, json.loads(raw)
        except json.JSONDecodeError:
            return e.code, {"raw": raw}


def login() -> None:
    global TOKEN
    st, r = call("POST", "/admin/v1/login", {"username": ADMIN_USER, "password": ADMIN_PASS})
    if st != 200 or not r.get("data", {}).get("access_token"):
        print(f"[FATAL] 登录失败 status={st} resp={r}")
        sys.exit(1)
    TOKEN = r["data"]["access_token"]
    src = r["data"].get("auth_source", "unknown")
    print(f"[OK] 登录成功 · 通道={src} · 角色={r['data'].get('roles')}")


# ───────────────────────── 1. admin 收编 ─────────────────────────

def ensure_admin_in_db(dry: bool) -> None:
    print("\n── 1. admin 账号收编 ──")
    st, r = call("GET", "/admin/v1/users")
    users = r.get("data", []) if st == 200 else []
    target = next((u for u in users if u.get("username") == ADMIN_USER), None)

    if target is None:
        if dry:
            SKIPS.append(f"[dry] 将创建库内账号 {ADMIN_USER} 并绑定 super_admin")
            print(f"  [dry-run] 库中无 {ADMIN_USER}，将创建")
            return
        st, r = call("POST", "/admin/v1/users", {
            "username": ADMIN_USER, "password": ADMIN_PASS,
            "display_name": "系统管理员",
        })
        if st != 200:
            print(f"  [FAIL] 创建失败 status={st} resp={r}")
            return
        uid = r["data"]["id"]
        CHANGES.append(f"创建库内管理员账号 {ADMIN_USER} (id={uid[:8]})")
        print(f"  [NEW] 已创建 {ADMIN_USER} id={uid}")
        # create_user 会自动挂 health_user 默认角色，摘掉它
        call("DELETE", "/admin/v1/roles/revoke", {"user_id": uid, "role_name": "health_user"})
    else:
        uid = target["id"]
        print(f"  [SKIP] {ADMIN_USER} 已在库中 id={uid}")

    st, r = call("GET", f"/admin/v1/users/{uid}")
    roles = [x["name"] for x in r.get("data", {}).get("roles", [])] if st == 200 else []
    if "super_admin" not in roles:
        if dry:
            SKIPS.append(f"[dry] 将给 {ADMIN_USER} 绑定 super_admin")
        else:
            st, _ = call("POST", "/admin/v1/roles/assign",
                         {"user_id": uid, "role_name": "super_admin"})
            CHANGES.append(f"{ADMIN_USER} 绑定 super_admin")
            print(f"  [BIND] super_admin → {ADMIN_USER} (status={st})")
    else:
        print(f"  [SKIP] 角色已就位: {roles}")

    # 顺手摘掉误挂的 health_user
    if "health_user" in roles and not dry:
        call("DELETE", "/admin/v1/roles/revoke", {"user_id": uid, "role_name": "health_user"})
        CHANGES.append(f"{ADMIN_USER} 摘除误挂的 health_user")
        print("  [FIX] 摘除误挂的 health_user")


# ─────────────────────── 2. 空壳角色补齐 ───────────────────────

def fill_empty_roles(dry: bool) -> None:
    print("\n── 2. 空壳角色补齐 ──")
    st, r = call("GET", "/admin/v1/roles")
    if st != 200:
        print(f"  [FAIL] 拉取角色失败 status={st}")
        return
    by_name = {x["name"]: x for x in r.get("data", [])}

    st, rp = call("GET", "/admin/v1/permissions")
    valid = {p["code"] for p in rp.get("data", [])} if st == 200 else set()

    for name, codes in ROLE_PERM_PLAN.items():
        role = by_name.get(name)
        if not role:
            print(f"  [WARN] 角色 {name} 不存在，跳过")
            continue
        have = {p["code"] for p in role.get("permissions", [])}
        want = {c for c in codes if c in valid}
        missing_codes = [c for c in codes if c not in valid]
        if missing_codes:
            print(f"  [WARN] {name} 计划中的权限不存在于权限表: {missing_codes}")
        if have == want:
            print(f"  [SKIP] {name} 权限已就位（{len(have)} 项）")
            continue
        if have:
            # 已有权限的角色不覆盖，避免误伤人工调整过的配置
            print(f"  [SKIP] {name} 已有 {len(have)} 项权限，不覆盖")
            continue
        if dry:
            SKIPS.append(f"[dry] {name} 将授予 {len(want)} 项权限")
            print(f"  [dry-run] {name} → {sorted(want)}")
            continue
        st, res = call("PUT", f"/admin/v1/roles/{role['id']}/permissions",
                       {"perm_codes": sorted(want)})
        if st == 200:
            n = res.get("data", {}).get("perm_count", len(want))
            CHANGES.append(f"角色 {name} 授予 {n} 项权限")
            print(f"  [SET] {name} ← {n} 项: {sorted(want)}")
        else:
            print(f"  [FAIL] {name} status={st} resp={res}")


# ─────────────────────── 3. 脏数据清理 ───────────────────────

def purge_dirty_users(dry: bool) -> None:
    print("\n── 3. 测试脏数据清理 ──")
    st, r = call("GET", "/admin/v1/users")
    if st != 200:
        print(f"  [FAIL] 拉取用户失败 status={st}")
        return
    users = r.get("data", [])
    dirty = [u for u in users
             if not (u.get("username") or "").strip() or DIRTY_USERNAME_RE.match(u.get("username") or "")]
    if not dirty:
        print("  [SKIP] 无脏数据")
        return
    for u in dirty:
        label = u.get("username") or "(空用户名)"
        if dry:
            SKIPS.append(f"[dry] 将删除脏用户 {label}")
            print(f"  [dry-run] 将删除 {label} id={u['id'][:8]}")
            continue
        st, res = call("DELETE", f"/admin/v1/users/{u['id']}")
        if st == 200:
            CHANGES.append(f"删除脏用户 {label}")
            print(f"  [DEL] {label} id={u['id'][:8]}")
        else:
            print(f"  [FAIL] 删除 {label} status={st} resp={res}")


# ─────────────────────────── 体检报告 ───────────────────────────

def report() -> None:
    print("\n── 体检报告（执行后状态）──")
    st, r = call("GET", "/admin/v1/roles")
    if st == 200:
        empty = []
        for x in r.get("data", []):
            n = len(x.get("permissions", []))
            flag = "  ⚠ 空壳" if n == 0 else ""
            print(f"  角色 {x['name']:<16} {x['display_name']:<10} 权限={n:<3} 用户={x['users']}{flag}")
            if n == 0:
                empty.append(x["name"])
        if empty:
            print(f"  ⚠ 仍有空壳角色: {empty}")
    st, r = call("GET", "/admin/v1/users")
    if st == 200:
        users = r.get("data", [])
        print(f"  用户总数 = {len(users)}")
        for u in users:
            roles = ",".join(x["name"] for x in u.get("roles", [])) or "无角色"
            print(f"    {u.get('username') or '(空)':<24} {u.get('display_name') or '-':<12} [{roles}]")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="只体检不改动")
    args = ap.parse_args()

    print(f"目标: {BASE}   模式: {'DRY-RUN（只读）' if args.dry_run else '执行'}")
    login()
    ensure_admin_in_db(args.dry_run)
    fill_empty_roles(args.dry_run)
    purge_dirty_users(args.dry_run)
    report()

    print("\n── 汇总 ──")
    if CHANGES:
        for c in CHANGES:
            print(f"  ✔ {c}")
    if SKIPS:
        for s in SKIPS:
            print(f"  · {s}")
    if not CHANGES and not SKIPS:
        print("  无需改动，环境已是目标状态")
    return 0


if __name__ == "__main__":
    sys.exit(main())
