"""活态化写入客户端 — 调用 8601 /kg/api 写通道（Admin Key 鉴权）

8602 侧聚合出的最终结果，经此客户端回写 Neo4j 图谱。
仅接受绝对值（confidence_abs），不接收 delta —— 防刷设计（见 P1 设计文档）。
"""
import os
import httpx
from typing import Optional, Dict, Any, List

# 8601 地址与 Admin Key（默认值与服务器实际一致；可用环境变量覆盖）
KG_API_BASE = os.getenv("QH_KG_API_BASE", "http://localhost:8601").rstrip("/")
KG_ADMIN_KEY = os.getenv("QH_KG_ADMIN_KEY", "qh_admin_default_2026")


class KgWriteClient:
    """8601 /kg/api 写通道客户端（带 Admin Key 鉴权）。"""

    def __init__(self, base_url: str = KG_API_BASE, admin_key: str = KG_ADMIN_KEY):
        self.base_url = base_url
        self.admin_key = admin_key
        self._client: Optional[httpx.AsyncClient] = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                headers={"X-API-Key": self.admin_key},
                timeout=30.0,
            )
        return self._client

    async def close(self):
        if self._client:
            await self._client.aclose()
            self._client = None

    async def get_confidence(self, kg_id: str, target: str = "node") -> Optional[float]:
        """读取节点/关系当前 confidence（聚合前取值）。失败返回 None。"""
        try:
            c = await self._get_client()
            r = await c.get(f"/kg/api/node/{kg_id}/confidence", params={"target": target})
            if r.status_code == 200:
                return r.json().get("confidence")
        except Exception:
            return None
        return None

    async def resolve(self, name: str) -> Dict[str, Any]:
        """按名称解析知识节点 kg_id（名字→kg_id 桥，供前端反馈入口用）。返回 8601 原始响应或 {error}。"""
        try:
            c = await self._get_client()
            r = await c.get("/kg/api/resolve", params={"name": name})
            if r.status_code == 200:
                return r.json()
            return {"error": f"kg_api_http_{r.status_code}", "raw": r.text[:200]}
        except Exception as e:
            return {"error": f"kg_api_unreachable: {e}"}

    async def batch_update_confidence(self, items: List[Dict[str, Any]]) -> Dict[str, Any]:
        """批量回写 confidence（绝对值）。"""
        try:
            c = await self._get_client()
            r = await c.post("/kg/api/confidence/batch", json={"items": items})
            if r.status_code == 200:
                return r.json()
            return {"error": f"kg_api_http_{r.status_code}", "raw": r.text[:200]}
        except Exception as e:
            return {"error": f"kg_api_unreachable: {e}"}

    async def apply_correction(self, kg_id, field, new_value, expert_id, reason) -> Dict[str, Any]:
        """专家纠偏：改字段 + 写版本谱系。"""
        try:
            c = await self._get_client()
            r = await c.post("/kg/api/correction", json={
                "kg_id": kg_id, "field": field, "new_value": new_value,
                "expert_id": expert_id, "reason": reason,
            })
            if r.status_code == 200:
                return r.json()
            return {"error": f"kg_api_http_{r.status_code}", "raw": r.text[:200]}
        except Exception as e:
            return {"error": f"kg_api_unreachable: {e}"}

    async def mark_gap(self, kg_id_a, kg_id_b, conflict_type, evidence) -> Dict[str, Any]:
        """标记知识缺口/矛盾。"""
        try:
            c = await self._get_client()
            r = await c.post("/kg/api/gap", json={
                "kg_id_a": kg_id_a, "kg_id_b": kg_id_b,
                "conflict_type": conflict_type, "evidence": evidence,
            })
            if r.status_code == 200:
                return r.json()
            return {"error": f"kg_api_http_{r.status_code}", "raw": r.text[:200]}
        except Exception as e:
            return {"error": f"kg_api_unreachable: {e}"}

    async def get_quiz_summary(self) -> Dict[str, Any]:
        """读取模型互考能力矩阵 + 知识盲点（透传 8601 /kg/api/quiz，活态化 A）。"""
        try:
            c = await self._get_client()
            r = await c.get("/kg/api/quiz")
            if r.status_code == 200:
                return r.json()
            return {"error": f"kg_api_http_{r.status_code}", "raw": r.text[:200]}
        except Exception as e:
            return {"error": f"kg_api_unreachable: {e}"}

    async def run_quiz(self, max_quizzes: int = 10) -> Dict[str, Any]:
        """触发一轮模型互考（透传 8601 /kg/api/quiz/run，活态化 A）。

        该过程涉及多次 LLM 调用（出题/作答/评分），耗时较长，
        故单独放宽超时至 180s（默认客户端超时为 30s，会触发 ReadTimeout）。
        """
        try:
            c = await self._get_client()
            r = await c.post(
                "/kg/api/quiz/run",
                params={"max_quizzes": max_quizzes},
                timeout=180.0,
            )
            if r.status_code == 200:
                return r.json()
            return {"error": f"kg_api_http_{r.status_code}", "raw": r.text[:200]}
        except Exception as e:
            return {"error": f"kg_api_unreachable: {e}"}


# 全局单例（测试可 monkeypatch 替换）
kg_client = KgWriteClient()
