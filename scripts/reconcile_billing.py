"""真计费对账 CLI（#656 收尾摊 · 离线巡检 / cron 友好）

真值链三层对账：CallLog(实时真扣费真值源) → Order(type=usage 月度快照单) → Bill(月度结算单)
抓漏结算 / 数值漂移 / 裸 0 / 双写嫌疑四类异常；fix 模式对漏结算租户自动补 usage 快照单（幂等）。

用法:
  # 全租户对账（只读，打印人类可读摘要）:
  python scripts/reconcile_billing.py --period 2026-09
  # 仅某租户明细 + 异常检测:
  python scripts/reconcile_billing.py --period 2026-09 --tenant-id <tenant_uuid>
  # 自动补漏结算单（幂等）并输出 JSON（供 cron + 监控）:
  python scripts/reconcile_billing.py --period 2026-09 --fix --json
  # 当前月:
  python scripts/reconcile_billing.py

退出码: 0=无异常（或全修复） / 2=存在未修复异常（供监控告警）。
"""
import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")  # 加载 .env（QH_DATABASE_URL 等）

from qihuang_platform.db.config import init_db, SessionLocal  # noqa: E402
from qihuang_platform.billing.reconcile import (  # noqa: E402
    reconcile_all,
    reconcile_tenant,
    detect_calllog_anomalies,
    ensure_usage_snapshot_for,
)


def _default_period() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m")


def _print_tenant_block(rec: dict, anomalies: dict) -> None:
    cl = rec.get("calllog", {})
    print(f"  ─ 租户 {rec.get('tenant_id')}  周期 {rec.get('period')}")
    print(f"     真扣费: {cl.get('calls')} 笔调用 / "
          f"{cl.get('tokens')} token / ¥{cl.get('cost_cents', 0)/100:.2f}")
    if rec.get("healthy"):
        print("     状态: ✅ 三层一致")
    else:
        for g in rec.get("gaps", []):
            print(f"     ⚠️  [{g['severity']}] {g['type']}: {g['detail']}")
    bz = anomalies.get("bare_zero", {})
    dw = anomalies.get("double_write_suspect", {})
    if bz.get("count"):
        print(f"     🔴 裸0(成功agent调用 cost<=0): {bz['count']} 笔 "
              f"样本 {bz.get('samples')[:3]}")
    if dw.get("trace_ids_with_dup"):
        print(f"     🔴 双写嫌疑(trace_id 重复): {dw['trace_ids_with_dup']} 个 "
              f"/ 共 {dw['count']} 条 样本 {dw.get('samples')[:3]}")


def main():
    ap = argparse.ArgumentParser(description="8602 真计费对账 CLI")
    ap.add_argument("--period", default=_default_period(),
                    help="账单周期 YYYY-MM（默认当前月）")
    ap.add_argument("--tenant-id", default=None,
                    help="指定租户（留空=全租户）")
    ap.add_argument("--fix", action="store_true",
                    help="对漏结算租户自动补 usage 快照单（幂等）")
    ap.add_argument("--json", action="store_true",
                    help="输出 JSON（供监控/cron 解析）")
    args = ap.parse_args()

    init_db()
    db = SessionLocal()
    try:
        if args.tenant_id:
            rec = reconcile_tenant(db, args.tenant_id, args.period)
            anomalies = detect_calllog_anomalies(db, args.tenant_id, args.period)
            fixed = False
            if args.fix and not rec["healthy"]:
                for gap in rec["gaps"]:
                    if gap["type"] == "missing_usage_order":
                        fx = ensure_usage_snapshot_for(db, args.tenant_id, args.period)
                        fixed = bool(fx.get("ok") and not fx.get("skipped"))
                        if fixed:
                            rec = reconcile_tenant(db, args.tenant_id, args.period)
                        break
            if args.fix:
                db.commit()
            out = {
                "mode": "tenant",
                "tenant_id": args.tenant_id,
                "period": args.period,
                "reconcile": rec,
                "anomalies": anomalies,
                "fixed": fixed,
            }
        else:
            result = reconcile_all(db, args.period, fix=args.fix)
            if args.fix:
                db.commit()
            out = {"mode": "all", **result}

        if args.json:
            print(json.dumps(out, ensure_ascii=False, default=str))
        else:
            if out["mode"] == "tenant":
                _print_tenant_block(out["reconcile"], out["anomalies"])
                print(f"  修复: {'已补 usage 单' if out['fixed'] else '无需修复/未开启'}")
            else:
                summ = out.get("summary", {})
                print(f"对账周期 {out['period']} · 共 {summ.get('total')} 租户")
                print(f"  ✅ 健康 {summ.get('healthy')} · "
                      f"⚠️ 有缺口 {summ.get('with_gaps')} · "
                      f"缺口项 {summ.get('total_gaps')}")
                if args.fix:
                    print(f"  🔧 自动补漏结算单: {summ.get('fixed')} 张")
                for t in out.get("tenants", []):
                    if not t.get("healthy"):
                        _print_tenant_block(t, {"bare_zero": {"count": 0, "samples": []},
                                                "double_write_suspect": {"trace_ids_with_dup": 0,
                                                                         "count": 0, "samples": []}})

        # 退出码：存在未修复异常 → 2（供监控告警）
        has_unfixed = False
        if out["mode"] == "tenant":
            has_unfixed = (not out["reconcile"].get("healthy")) and not out["fixed"]
        else:
            has_unfixed = bool(out.get("summary", {}).get("with_gaps"))
        sys.exit(2 if has_unfixed else 0)
    except Exception as e:  # noqa: BLE001
        db.rollback()
        print(f"对账失败: {e}", file=sys.stderr)
        sys.exit(1)
    finally:
        db.close()


if __name__ == "__main__":
    main()
