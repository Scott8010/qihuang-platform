"""活态化趋势采集（方案 2：变化曲线）

collect_living_snapshot(): 周期性记录「活态生态」瞬时健康度到 KgConfidenceSnapshot，
形成时间序列，使成效月报能绘制「越用越聪明」趋势线。

采集项：
  - 模型互考矩阵 + 盲点（8601 GET /kg/api/quiz，真实运行数据）
  - 反馈统计 / 活态节点数（8602 本地 KgFeedback）
  - 活态节点平均置信度（对 KgFeedback 出现的 kg_id 抽样，调 8601 取 confidence）

容错：任一数据源失败均不阻断整行落库；字段 nullable。
"""
import json
import logging
import os
from typing import Optional

from sqlalchemy import func, select

from qihuang_platform.db.config import SessionLocal
from qihuang_platform.living.models import KgFeedback, KgConfidenceSnapshot
from qihuang_platform.living.kg_write_client import kg_client

logger = logging.getLogger("living.trend")

# 活态节点置信度抽样上限（避免一次性对海量节点发请求）
_LIVING_SAMPLE_CAP = 50


def _parse_quiz(quiz: dict) -> dict:
    """从 8601 互考矩阵抽出报告所需的汇总字段。"""
    if not isinstance(quiz, dict) or "error" in quiz:
        return {}
    caps = {c.get("model_key"): c.get("accuracy") for c in quiz.get("capabilities", [])}
    quiz_total = quiz.get("quiz_total") or sum(
        c.get("quiz_count", 0) for c in quiz.get("capabilities", [])
    )
    blind_spots = quiz.get("blind_spots", []) or []
    blind_top = sorted(
        blind_spots, key=lambda b: b.get("blind_spots", 0), reverse=True
    )[:15]
    return {
        "caps": caps,
        "quiz_total": quiz_total,
        "blind_spot_count": len(blind_spots),
        "blind_spots_json": json.dumps(
            [{"name": b.get("name"), "count": b.get("blind_spots")} for b in blind_top],
            ensure_ascii=False,
        ),
    }


async def collect_living_snapshot(quiz_json_path: Optional[str] = None) -> dict:
    """采集一次活态生态健康度快照并落库。

    quiz_json_path: 离线注入互考矩阵的 JSON 路径（本地验证用；生产环境不传，直连 8601）。
    返回采集摘要 dict（含 error 字段表示失败）。
    """
    db = SessionLocal()
    try:
        # —— 1. 互考矩阵 + 盲点 ——
        if quiz_json_path and os.path.exists(quiz_json_path):
            with open(quiz_json_path, "r", encoding="utf-8") as f:
                quiz = json.load(f)
            logger.info("[living.trend] 使用离线 quiz_json: %s", quiz_json_path)
        else:
            quiz = await kg_client.get_quiz_summary()
        q = _parse_quiz(quiz)
        caps = q.get("caps", {})

        # —— 2. 反馈统计 / 活态节点 ——
        total_feedback = db.scalar(select(func.count()).select_from(KgFeedback)) or 0
        living_ids = db.scalars(select(KgFeedback.kg_id).distinct()).all()
        living_node_count = len(living_ids)

        # —— 3. 活态节点平均置信度（抽样）——
        living_mean = None
        if living_node_count > 0:
            vals = []
            for kid in living_ids[:_LIVING_SAMPLE_CAP]:
                if kid and not str(kid).startswith("pending:"):
                    c = await kg_client.get_confidence(kid)
                    if c is not None:
                        vals.append(c)
            if vals:
                living_mean = round(sum(vals) / len(vals), 4)

        # —— 4. 模型信任均值（聚合层 model_trust 杠杆）——
        accs = [v for v in (
            caps.get("deepseek"), caps.get("qwen"), caps.get("glm"), caps.get("kimi")
        ) if v is not None]
        model_trust_mean = round(sum(accs) / len(accs), 4) if accs else None

        # —— 5. 落库 ——
        snap = KgConfidenceSnapshot(
            quiz_total=q.get("quiz_total", 0) or 0,
            deepseek_acc=caps.get("deepseek"),
            qwen_acc=caps.get("qwen"),
            glm_acc=caps.get("glm"),
            kimi_acc=caps.get("kimi"),
            model_trust_mean=model_trust_mean,
            blind_spot_count=q.get("blind_spot_count", 0) or 0,
            blind_spots_json=q.get("blind_spots_json"),
            living_node_count=living_node_count,
            living_mean_confidence=living_mean,
            total_feedback=total_feedback,
        )
        db.add(snap)
        db.commit()
        db.refresh(snap)
        summary = {
            "snapshot_at": snap.snapshot_at.isoformat(),
            "quiz_total": snap.quiz_total,
            "model_trust_mean": model_trust_mean,
            "blind_spot_count": snap.blind_spot_count,
            "living_node_count": living_node_count,
            "living_mean_confidence": living_mean,
            "total_feedback": total_feedback,
        }
        logger.info("[living.trend] 快照已落库: %s", summary)
        return summary
    except Exception as e:
        db.rollback()
        logger.exception(f"[living.trend] 采集异常: {e}")
        return {"error": str(e)}
    finally:
        db.close()
