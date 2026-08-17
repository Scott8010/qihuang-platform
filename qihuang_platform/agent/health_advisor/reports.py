"""
health-advisor · 报告生成（T5 · full 模式）

探查结论（2026-08-16 实测）：
  平台当前无「健康顾问辨证报告」端点——8602 capability/routers/health.py 无 reports 路由，
  8601 /api/reports 是 auto_growth 自生长汇报列表（非本 Agent 报告）。MVP 文档假设的
  med/reports(report_id+pdf_path) 属假设性，真实需自行实现。

故 T5 在 health-advisor 内部实现：
  - generate_report：把 ConsultResponse 辨证结果 markdown 化 + 生成 report_id
  - 存储：内存 dict 占位（TODO P0-3 后换 DB/文件落盘）
"""
from __future__ import annotations

import time
import uuid
from typing import Dict, Optional

from .schema import ConsultResponse

# TODO(P0-3): 生产可写目录落盘（部署时放开）
# from pathlib import Path
# REPORT_DIR = Path(__file__).parent / "reports"

_store: Dict[str, dict] = {}


def _render(resp: ConsultResponse) -> str:
    """把辨证结果渲染为 Markdown 报告。"""
    lines = ["# 中医健康顾问辨证报告", ""]
    lines.append(f"- 报告追踪号(trace)：`{resp.trace_id}`")
    lines.append(f"- 会话ID：`{resp.session_id}`")
    lines.append(f"- 信息完整度：{'完整' if not resp.partial else '部分（建议补充舌象/脉象以获得更精准辨证）'}")
    lines.append("")
    if resp.constitution and resp.constitution.type:
        lines.append(f"## 体质辨识\n{resp.constitution.type}：{resp.constitution.desc or ''}")
    if resp.syndrome and resp.syndrome.name:
        lines.append(
            f"## 辨证倾向\n{resp.syndrome.name}"
            f"（置信度：{resp.syndrome.confidence or '未知'}）"
        )
    if resp.formulas:
        lines.append("## 推荐方剂")
        for f in resp.formulas:
            items = "、".join(f.items) if f.items else "（组成未详）"
            note = f"（{f.note}）" if f.note else ""
            lines.append(f"- **{f.name}**：{items}{note}")
    if resp.suggestions:
        lines.append("## 调理建议")
        for s in resp.suggestions:
            lines.append(f"- {s}")
    lines.append("")
    lines.append(f"> {resp.disclaimer}")
    return "\n".join(lines)


async def generate_report(resp: ConsultResponse, trace_id: str) -> str:
    """生成报告，返回 report_id（存入内存存储，预留 LLM 润色与文件落盘）。"""
    report_id = f"ha_{int(time.time())}_{uuid.uuid4().hex[:4]}"
    content = _render(resp)
    _store[report_id] = {
        "report_id": report_id,
        "trace_id": trace_id,
        "session_id": resp.session_id,
        "partial": resp.partial,
        "content": content,
        "created_at": time.time(),
    }
    # TODO(P0-3): 同时落盘 REPORT_DIR / f"{report_id}.md"
    return report_id


def get_report(report_id: str) -> Optional[dict]:
    """按 report_id 查询报告（T8 联调端点用）。"""
    return _store.get(report_id)
