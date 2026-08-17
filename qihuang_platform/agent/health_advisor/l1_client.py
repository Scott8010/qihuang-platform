"""
health-advisor · L1 能力客户端

方案B：主用 8601 的 `/reasoning/api/sizhen` 一次拿全（体质+方剂+调理+外治+舌脉+综述），
diagnose / formulas / chat 仅作补充。

调用方式严格复用平台既有范式（capability/routers/health.py）：
    from qihuang_platform.capability.proxy import proxy
    await proxy.forward("POST", "/reasoning/api/sizhen", json_body=body)
proxy.forward 透传 8601 原始 JSON 并返回 dict（无外层 code 包裹）。
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from qihuang_platform.capability.proxy import proxy


class L1Client:
    @staticmethod
    async def sizhen(
        *,
        symptoms: Optional[str] = None,
        tongue: Optional[str] = None,
        pulse: Optional[str] = None,
        face: Optional[str] = None,
    ) -> Dict[str, Any]:
        body = {
            k: v
            for k, v in {
                "symptoms": symptoms,
                "tongue": tongue,
                "pulse": pulse,
                "face": face,
            }.items()
            if v
        }
        return (await proxy.forward("POST", "/reasoning/api/sizhen", json_body=body)) or {}

    @staticmethod
    async def diagnose(symptoms: str) -> Dict[str, Any]:
        return (await proxy.forward("GET", "/reasoning/api/diagnose", params={"symptoms": symptoms})) or {}

    @staticmethod
    async def formulas(syndrome: str) -> Dict[str, Any]:
        return (await proxy.forward("GET", "/api/v1/formulas", params={"syndrome": syndrome})) or {}

    @staticmethod
    async def chat(message: str) -> Dict[str, Any]:
        return (await proxy.forward("POST", "/chat/api/ask", json_body={"message": message})) or {}
