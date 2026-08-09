"""清理 ui_test_* 残留测试用户（仅运维用途）。

用法:
  python scripts/cleanup_test_users.py --dry-run   # 列出将删除的用户 + 阻断项检查
  python scripts/cleanup_test_users.py --apply     # 实际删除

安全设计:
  - 仅匹配 username LIKE 'ui_test_%'，绝不碰其他账号
  - 删除前检查 med_case.doctor_id 等外键引用，存在阻断项则跳过该用户并报错
  - 先删 user_role 关联行，再删 user 行，避免 FK 约束冲突
"""
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

try:
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
except Exception:
    pass

from sqlalchemy import select, delete, func

from qihuang_platform.db.config import SessionLocal
from qihuang_platform.db.models import User, UserRole, Role, MedCase


def find_test_users(db):
    return db.scalars(
        select(User).where(User.username.like("ui_test_%")).order_by(User.username)
    ).all()


def list_roles(db, user_id):
    return db.scalars(
        select(Role.name)
        .join(UserRole, Role.id == UserRole.role_id)
        .where(UserRole.user_id == user_id)
    ).all()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="实际删除")
    ap.add_argument("--dry-run", action="store_true", help="仅列出不删除（默认）")
    args = ap.parse_args()

    db = SessionLocal()
    try:
        total = db.scalar(select(func.count()).select_from(User))
        users = find_test_users(db)
        print(f"[info] 用户总数={total}  | 匹配 ui_test_* = {len(users)}")

        blockers = []
        for u in users:
            roles = list_roles(db, u.id)
            # FK 阻断检查：是否被 med_case 引用
            mc_count = db.scalar(
                select(func.count()).select_from(MedCase).where(MedCase.doctor_id == u.id)
            )
            flag = ""
            if mc_count:
                flag = f"  ⚠️ 阻断: 关联 med_case={mc_count} 条, 跳过"
                blockers.append(u.id)
            print(
                f"  - {u.username}  tenant={u.tenant_id}  roles=[{','.join(roles) or '无'}]"
                f"{flag}"
            )

        if not args.apply:
            print("\n[dry-run] 未做任何删除。加 --apply 执行。")
            return

        # apply
        to_delete = [u for u in users if u.id not in blockers]
        ids = [u.id for u in to_delete]
        if ids:
            db.execute(delete(UserRole).where(UserRole.user_id.in_(ids)))
            for u in to_delete:
                db.delete(u)
            db.commit()
            print(f"\n[apply] 已删除 {len(ids)} 个测试用户（跳过 {len(blockers)} 个阻断项）。")
        else:
            print("\n[apply] 无用户可删。")
        if blockers:
            print(f"[warn] {len(blockers)} 个用户因 FK 阻断未删，需人工处理。")
    finally:
        db.close()


if __name__ == "__main__":
    main()
