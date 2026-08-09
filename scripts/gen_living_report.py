"""活态化成效月报生成器（方案 2：变化曲线）

读取 kg_confidence_snapshot 历史表，渲染内联 SVG 趋势图，输出静态 HTML。
完全 DB 驱动，报告生成时无需再连 8601（最新快照已含全部指标）。

用法:
  python scripts/gen_living_report.py
  python scripts/gen_living_report.py --out /path/to/report.html

默认输出: Desktop/岐黄大脑/2026-08-09/岐黄智脑活态化成效月报_2026-08.html
"""
import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")  # 加载 .env（QH_DATABASE_URL 等）

from sqlalchemy import select
from qihuang_platform.db.config import SessionLocal
from qihuang_platform.living.models import KgConfidenceSnapshot

DEFAULT_OUT = Path(
    "C:/Users/Administrator/Desktop/岐黄大脑/2026-08-09/岐黄智脑活态化成效月报_2026-08.html"
)

MODEL_COLORS = {
    "deepseek": "#2563eb",
    "qwen": "#16a34a",
    "glm": "#d97706",
    "kimi": "#dc2626",
}
MODEL_LABELS = {
    "deepseek": "DeepSeek",
    "qwen": "通义千问",
    "glm": "GLM-4",
    "kimi": "Kimi",
}


def _fmt_dt(dt) -> str:
    if dt is None:
        return "-"
    if isinstance(dt, str):
        return dt[:16]
    return dt.strftime("%Y-%m-%d %H:%M")


def _fmt_day(dt) -> str:
    if dt is None:
        return "-"
    if isinstance(dt, str):
        return dt[5:10]
    return dt.strftime("%m-%d")


# ───────────────────────── SVG 图表 ─────────────────────────
def line_chart(title, series, x_labels, ymin=0.0, ymax=1.0, w=680, h=280):
    """多序列折线图。series: [(key, color, label, [values])]；values 可为 None。"""
    ml, mr, mt, mb = 52, 16, 30, 40
    plot_w = w - ml - mr
    plot_h = h - mt - mb
    n = len(x_labels)

    def X(i):
        if n <= 1:
            return ml + plot_w / 2
        return ml + plot_w * i / (n - 1)

    def Y(v):
        if v is None:
            return None
        ratio = (v - ymin) / (ymax - ymin) if ymax > ymin else 0
        ratio = max(0.0, min(1.0, ratio))
        return mt + plot_h * (1 - ratio)

    p = [f'<svg viewBox="0 0 {w} {h}" xmlns="http://www.w3.org/2000/svg" font-family="system-ui,Segoe UI,Arial">']
    p.append(f'<text x="{ml}" y="16" font-size="13" font-weight="600" fill="#111827">{title}</text>')
    # y 网格
    for g in range(5):
        gv = ymin + (ymax - ymin) * g / 4
        gy = Y(gv)
        p.append(f'<line x1="{ml}" y1="{gy:.1f}" x2="{ml+plot_w}" y2="{gy:.1f}" stroke="#eef0f3"/>')
        p.append(f'<text x="{ml-8}" y="{gy+4:.1f}" text-anchor="end" font-size="10" fill="#9ca3af">{gv:.2f}</text>')
    # x 标签
    for i, lab in enumerate(x_labels):
        p.append(f'<text x="{X(i):.1f}" y="{mt+plot_h+20:.1f}" text-anchor="middle" font-size="10" fill="#9ca3af">{lab}</text>')
    # 序列
    for (key, color, label, vals) in series:
        pts = " ".join(f"{X(i):.1f},{Y(v):.1f}" for i, v in enumerate(vals) if v is not None)
        if pts:
            p.append(f'<polyline points="{pts}" fill="none" stroke="{color}" stroke-width="2.2"/>')
            for i, v in enumerate(vals):
                if v is not None:
                    p.append(f'<circle cx="{X(i):.1f}" cy="{Y(v):.1f}" r="3" fill="{color}"/>')
    # 图例
    lx = ml
    for (key, color, label, vals) in series:
        p.append(f'<rect x="{lx}" y="{mt-2}" width="10" height="10" rx="2" fill="{color}"/>')
        p.append(f'<text x="{lx+14}" y="{mt+7}" font-size="10" fill="#374151">{label}</text>')
        lx += 26 + len(label) * 11
    p.append("</svg>")
    return "".join(p)


def bar_chart(title, labels, values, color="#7c3aed", w=680, h=240):
    ml, mr, mt, mb = 52, 16, 30, 40
    plot_w = w - ml - mr
    plot_h = h - mt - mb
    ymax = max(values) * 1.15 if values and max(values) > 0 else 1
    bw = plot_w / max(1, len(labels)) * 0.6
    gap = plot_w / max(1, len(labels))

    p = [f'<svg viewBox="0 0 {w} {h}" xmlns="http://www.w3.org/2000/svg" font-family="system-ui,Segoe UI,Arial">']
    p.append(f'<text x="{ml}" y="16" font-size="13" font-weight="600" fill="#111827">{title}</text>')
    for g in range(5):
        gv = ymax * g / 4
        gy = mt + plot_h * (1 - gv / ymax)
        p.append(f'<line x1="{ml}" y1="{gy:.1f}" x2="{ml+plot_w}" y2="{gy:.1f}" stroke="#eef0f3"/>')
        p.append(f'<text x="{ml-8}" y="{gy+4:.1f}" text-anchor="end" font-size="10" fill="#9ca3af">{gv:.0f}</text>')
    for i, (lab, v) in enumerate(zip(labels, values)):
        bx = ml + gap * i + (gap - bw) / 2
        bh = plot_h * (v / ymax) if ymax else 0
        by = mt + plot_h - bh
        p.append(f'<rect x="{bx:.1f}" y="{by:.1f}" width="{bw:.1f}" height="{bh:.1f}" rx="3" fill="{color}"/>')
        p.append(f'<text x="{bx+bw/2:.1f}" y="{by-5:.1f}" text-anchor="middle" font-size="10" fill="#374151">{v}</text>')
        p.append(f'<text x="{bx+bw/2:.1f}" y="{mt+plot_h+20:.1f}" text-anchor="middle" font-size="10" fill="#9ca3af">{lab}</text>')
    p.append("</svg>")
    return "".join(p)


def cap_bar_chart(snap, w=680, h=240):
    labels, values = [], []
    for k in ("deepseek", "qwen", "glm", "kimi"):
        v = getattr(snap, f"{k}_acc")
        if v is not None:
            labels.append(MODEL_LABELS[k])
            values.append(round(v * 100, 1))
    colors = list(MODEL_COLORS.values())[: len(labels)]
    ml, mr, mt, mb = 52, 16, 30, 40
    plot_w = w - ml - mr
    plot_h = h - mt - mb
    ymax = 100
    bw = plot_w / max(1, len(labels)) * 0.55
    gap = plot_w / max(1, len(labels))
    p = [f'<svg viewBox="0 0 {w} {h}" xmlns="http://www.w3.org/2000/svg" font-family="system-ui,Segoe UI,Arial">']
    p.append(f'<text x="{ml}" y="16" font-size="13" font-weight="600" fill="#111827">模型互考正确率（最新快照）</text>')
    for g in range(5):
        gv = ymax * g / 4
        gy = mt + plot_h * (1 - gv / ymax)
        p.append(f'<line x1="{ml}" y1="{gy:.1f}" x2="{ml+plot_w}" y2="{gy:.1f}" stroke="#eef0f3"/>')
        p.append(f'<text x="{ml-8}" y="{gy+4:.1f}" text-anchor="end" font-size="10" fill="#9ca3af">{gv:.0f}</text>')
    for i, (lab, v, c) in enumerate(zip(labels, values, colors)):
        bx = ml + gap * i + (gap - bw) / 2
        bh = plot_h * (v / ymax)
        by = mt + plot_h - bh
        p.append(f'<rect x="{bx:.1f}" y="{by:.1f}" width="{bw:.1f}" height="{bh:.1f}" rx="3" fill="{c}"/>')
        p.append(f'<text x="{bx+bw/2:.1f}" y="{by-5:.1f}" text-anchor="middle" font-size="11" fill="#374151">{v}%</text>')
        p.append(f'<text x="{bx+bw/2:.1f}" y="{mt+plot_h+20:.1f}" text-anchor="middle" font-size="10" fill="#9ca3af">{lab}</text>')
    p.append("</svg>")
    return "".join(p)


# ───────────────────────── 月报主体 ─────────────────────────
def build_html(rows):
    if not rows:
        return """<div style="font-family:system-ui;padding:40px;color:#6b7280">
        尚无趋势快照。请先运行 <code>python scripts/seed_living_snapshot.py</code> 落首个采集点。</div>"""

    latest = rows[-1]
    x_labels = [_fmt_day(r.snapshot_at) for r in rows]

    # 模型精度趋势
    series = []
    for k in ("deepseek", "qwen", "glm", "kimi"):
        vals = [getattr(r, f"{k}_acc") for r in rows]
        if any(v is not None for v in vals):
            series.append((k, MODEL_COLORS[k], MODEL_LABELS[k], vals))
    model_trend = line_chart("模型互考正确率趋势（越用越聪明）", series, x_labels, 0, 1)

    # 互考题量趋势
    quiz_vals = [r.quiz_total for r in rows]
    quiz_trend = bar_chart("模型互考累计题量趋势", x_labels, quiz_vals, "#7c3aed")

    # 盲点趋势
    blind_vals = [r.blind_spot_count for r in rows]
    blind_trend = line_chart("知识盲点节点数趋势（越低越好）",
                             [("blind", "#ea580c", "盲点节点数", blind_vals)],
                             x_labels, 0, max(blind_vals) * 1.2 if blind_vals and max(blind_vals) > 0 else 1)

    # 活态节点平均置信度趋势
    living_vals = [r.living_mean_confidence for r in rows]
    if any(v is not None for v in living_vals):
        living_trend = line_chart("活态节点平均置信度趋势（反馈闭环生效）",
                                  [("living", "#0891b2", "平均置信度", living_vals)],
                                  x_labels, 0, 1)
        living_section = f"<div class='card'>{living_trend}</div>"
    else:
        living_section = """<div class='card' style='color:#9ca3af;display:flex;align-items:center;justify-content:center;height:200px'>
        活态节点平均置信度：暂无数据（KgFeedback 尚未采集，反馈闭环待真实业务喂养）</div>"""

    # 盲点 Top15 表
    blind_rows_html = ""
    if latest.blind_spots_json:
        try:
            blind_list = json.loads(latest.blind_spots_json)
            for i, b in enumerate(blind_list, 1):
                blind_rows_html += f"<tr><td>{i}</td><td>{b.get('name','-')}</td><td><span class='pill'>{b.get('count','-')}</span></td></tr>"
        except Exception:
            blind_rows_html = "<tr><td colspan='3'>盲点明细解析失败</td></tr>"
    else:
        blind_rows_html = "<tr><td colspan='3' style='color:#9ca3af'>无盲点明细</td></tr>"

    cards = [
        ("互考累计题量", latest.quiz_total, "#7c3aed"),
        ("参与互考模型", len([v for v in [latest.deepseek_acc, latest.qwen_acc, latest.glm_acc, latest.kimi_acc] if v is not None]), "#2563eb"),
        ("知识盲点节点", latest.blind_spot_count, "#ea580c"),
        ("知识反馈总数", latest.total_feedback, "#0891b2"),
    ]
    cards_html = "".join(
        f"<div class='stat' style='border-top:3px solid {c}'><div class='num'>{v}</div><div class='lab'>{l}</div></div>"
        for (l, v, c) in cards
    )

    gen_at = _fmt_dt(latest.snapshot_at)
    n_snap = len(rows)

    html = f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>岐黄智脑 · 活态化成效月报</title>
<style>
  * {{ box-sizing: border-box; }}
  body {{ margin:0; background:#f5f7fa; color:#1f2937; font-family:system-ui,"Segoe UI",Arial,"Microsoft YaHei"; }}
  .wrap {{ max-width:760px; margin:0 auto; padding:28px 20px 60px; }}
  h1 {{ font-size:22px; margin:0 0 4px; }}
  .sub {{ color:#6b7280; font-size:13px; margin-bottom:20px; }}
  .stats {{ display:grid; grid-template-columns:repeat(4,1fr); gap:12px; margin-bottom:22px; }}
  .stat {{ background:#fff; border-radius:12px; padding:14px; box-shadow:0 1px 3px rgba(0,0,0,.06); }}
  .stat .num {{ font-size:26px; font-weight:700; }}
  .stat .lab {{ font-size:12px; color:#6b7280; margin-top:4px; }}
  .card {{ background:#fff; border-radius:12px; padding:16px; box-shadow:0 1px 3px rgba(0,0,0,.06); margin-bottom:16px; }}
  .card svg {{ width:100%; height:auto; display:block; }}
  table {{ width:100%; border-collapse:collapse; font-size:13px; }}
  th,td {{ text-align:left; padding:8px 10px; border-bottom:1px solid #f0f0f0; }}
  th {{ color:#6b7280; font-weight:600; }}
  .pill {{ background:#fff1e6; color:#ea580c; border-radius:10px; padding:1px 8px; font-size:12px; }}
  .note {{ background:#eef6ff; border-left:3px solid #2563eb; padding:10px 14px; border-radius:8px; font-size:12.5px; color:#374151; margin-bottom:16px; }}
  .foot {{ color:#9ca3af; font-size:12px; margin-top:24px; text-align:center; }}
</style></head>
<body><div class="wrap">
  <h1>岐黄智脑 · 活态化成效月报</h1>
  <div class="sub">生成时间 {gen_at} · 已采集 {n_snap} 个趋势快照 · 数据来源 8601 互考矩阵 + 8602 反馈闭环</div>

  <div class="stats">{cards_html}</div>

  <div class="note">「变化曲线」已启动采集：活态调度每日自动落点（互考 + 反馈闭环），后续月份将累积成趋势线，直观证明「越用越聪明」。
  当前反馈总数=0 属正常——租户业务数据（回路三）待 B1 营业执照就绪后激活。</div>

  <div class="card">{model_trend}</div>
  <div class="card">{cap_bar_chart(latest)}</div>
  <div class="card">{quiz_trend}</div>
  <div class="card">{blind_trend}</div>
  {living_section}

  <div class="card">
    <h3 style="margin:0 0 10px;font-size:14px">知识盲点 Top 15（最新快照）</h3>
    <table><thead><tr><th>#</th><th>知识点</th><th>命中次数</th></tr></thead>
    <tbody>{blind_rows_html}</tbody></table>
  </div>

  <div class="foot">岐黄智脑活态化改造 · 方案 2 变化曲线采集 · 自动生成</div>
</div></body></html>"""
    return html


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    args = ap.parse_args()

    db = SessionLocal()
    try:
        rows = db.scalars(
            select(KgConfidenceSnapshot).order_by(KgConfidenceSnapshot.snapshot_at.asc())
        ).all()
    finally:
        db.close()

    html = build_html(rows)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")
    print(f"REPORT WRITTEN: {out}  (snapshots={len(rows)})")


if __name__ == "__main__":
    main()
