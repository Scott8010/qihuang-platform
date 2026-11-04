"""安全护栏 wrapper —— 通用安全扫描（Prompt 注入 / PII 泄漏）。

定位：叠加在 L0+L1+L2 合规引擎之上，不替换其核心判定。
  - llm-guard 可用时优先用其模型；不可用（未安装/离线）时回退本地正则，保证审核主流程不中断。
  - 灰度策略：默认【仅打标不拦截】（命中记为 ORANGE/建议整改）；
    SECURITY_BLOCK_INJECTION=1 时注入命中升 RED 拦截。
  - 数据真实性原则：护栏缺失绝不伪造判定，仅在确有命中时追加 layer=SEC 命中。

接入点：engine_l2.ComplianceEngineL2.analyze 在 L0+L1+L2 融合后调用 security_scan()，
        返回的 SEC 命中并入 hits（格式与 _merge 输出一致）。
"""
from __future__ import annotations

import os
import re
from typing import Any

# ── llm-guard 可选依赖（防御性导入，缺失则回退本地正则）──
try:
    from llm_guard.input_scanners import PromptInjection, SensitiveDataScanner
    _LLM_GUARD_AVAILABLE = True
except Exception:  # pragma: no cover - 依赖缺失时降级
    _LLM_GUARD_AVAILABLE = False

# 灰度开关：注入命中是否升 RED 拦截（默认 False = 仅打标）
SECURITY_BLOCK_INJECTION = os.getenv("SECURITY_BLOCK_INJECTION", "0") == "1"

# 审核场景：platform=大平台（默认严）/ merchant=小微·个体养生门店（放宽联系方式公示）。
# 本产品服务对象为千万家小型/个体养生门店，默认 merchant；接大平台客户时设 AUDIT_MODE=platform。
AUDIT_MODE = os.getenv("AUDIT_MODE", "merchant")


def resolve_profile(tenant_profile: str | None = None) -> str:
    """解析审核场景：调用方显式指定 > 环境变量 AUDIT_MODE > 默认 merchant。"""
    return tenant_profile or AUDIT_MODE

# ── 本地正则回退（llm-guard 未装时也能扫 PII / 基础注入）──
_RE_PHONE = re.compile(r"1[3-9]\d{9}")
_RE_IDCARD = re.compile(r"(?<!\d)(?:\d{17}[\dXx]|\d{15})(?!\d)")
_RE_BANKCARD = re.compile(r"(?<!\d)(?:[3-9]\d{2,3}[ -]?\d{4}[ -]?\d{4}[ -]?\d{4})(?!\d)")
_RE_APIKEY = re.compile(r"(?:sk|api[_-]?key|token|secret)[-_:\s]*[A-Za-z0-9]{16,}", re.I)
# 轻量注入检测：覆盖常见越狱/指令覆盖套路（llm-guard 缺失时启用）
_RE_INJECTION = re.compile(
    r"(?:忽略|无视|忘记|忘掉|跳过).{0,14}(?:以上|前面|上述|所有|下面|之前).{0,10}(?:规则|条款|指令|提示|限制)|"
    r"(?:忽略|无视|绕过).{0,12}(?:只输出|输出空|返回空|不要管|不必管)"
)

# llm-guard scanner 懒加载缓存（避免每次扫描重复实例化模型）
_prompt_injection_scanner = None
_pii_scanner = None


def _get_prompt_injection() -> Any | None:
    global _prompt_injection_scanner
    if not _LLM_GUARD_AVAILABLE:
        return None
    if _prompt_injection_scanner is None:
        try:
            _prompt_injection_scanner = PromptInjection()
        except Exception:
            return None
    return _prompt_injection_scanner


def _get_pii_scanner() -> Any | None:
    global _pii_scanner
    if not _LLM_GUARD_AVAILABLE:
        return None
    if _pii_scanner is None:
        try:
            _pii_scanner = SensitiveDataScanner(redact=False)
        except Exception:
            return None
    return _pii_scanner


def _scan_injection(text: str) -> bool:
    """检测 Prompt 注入 / 越狱指令。优先 llm-guard，缺失回退正则。"""
    sc = _get_prompt_injection()
    if sc is not None:
        try:
            _, is_inj = sc.scan(text)
            return bool(is_inj)
        except Exception:
            return False
    return bool(_RE_INJECTION.search(text))


def _scan_pii(text: str, profile: str | None = None) -> bool:
    """检测个人敏感信息（手机号/身份证/银行卡/密钥）。

    profile="merchant"（小微·个体门店，默认）：商家公示自己的联系方式（手机/微信/二维码）
    是正常经营，不作「敏感信息泄漏」误报——仅检测身份证/银行卡/密钥等真实泄漏。
    profile="platform"（大平台）：保留手机号扫描（防止观众通过物料拿到商家电话跑单）。
    """
    profile = profile or AUDIT_MODE
    if profile == "merchant":
        # 小微门店：跳过手机号，避免把商家自有联系电话误判为泄漏
        return bool(
            _RE_IDCARD.search(text)
            or _RE_BANKCARD.search(text)
            or _RE_APIKEY.search(text)
        )
    sc = _get_pii_scanner()
    if sc is not None:
        try:
            _, pii, _ = sc.scan(text)
            return bool(pii)
        except Exception:
            return False
    return bool(
        _RE_PHONE.search(text)
        or _RE_IDCARD.search(text)
        or _RE_BANKCARD.search(text)
        or _RE_APIKEY.search(text)
    )


def security_scan(text: str, profile: str | None = None) -> list[dict[str, Any]]:
    """返回与 engine_l2._merge 输出格式一致的 SEC 层命中列表（layer=SEC）。

    profile 透传审核场景：merchant 模式下不把商家自有手机号误报为 PII 泄漏。
    """
    hits: list[dict[str, Any]] = []
    profile = profile or AUDIT_MODE

    if _scan_injection(text):
        hits.append({
            "clause_id": "SEC-INJ",
            "severity": "RED" if SECURITY_BLOCK_INJECTION else "ORANGE",
            "confidence": 0.9,
            "title": "疑似 Prompt 注入/越狱指令，可能试图操控合规判定"
                      + ("" if SECURITY_BLOCK_INJECTION else "（已标记，未拦截）"),
            "source_ref": "SECURITY",
            "suggested_replace": "移除操控性指令文本，仅提交真实经营文案",
            "layer": "SEC",
            "snippet": text[:60],
        })

    if _scan_pii(text, profile):
        # merchant 模式仅当真出现身份证/银行卡/密钥才到此分支
        title = ("疑似含个人敏感信息（身份证/银行卡/密钥），存在泄漏风险"
                 if profile == "merchant"
                 else "疑似含个人敏感信息（手机号/身份证/银行卡/密钥），存在泄漏风险")
        hits.append({
            "clause_id": "SEC-PII",
            "severity": "ORANGE",
            "confidence": 0.9,
            "title": title,
            "source_ref": "SECURITY",
            "suggested_replace": "移除个人敏感字段，或使用脱敏占位符",
            "layer": "SEC",
            "snippet": text[:60],
        })

    return hits


# 供健康检查/启动日志观测依赖状态（不抛异常）
def dependency_status() -> dict[str, Any]:
    return {
        "llm_guard_available": _LLM_GUARD_AVAILABLE,
        "block_injection": SECURITY_BLOCK_INJECTION,
    }
