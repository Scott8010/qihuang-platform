"""
LLM降级链 — DeepSeek主用 -> GLM-4-plus备用 -> 规则引擎兜底

降级策略:
1. 主用LLM(DeepSeek)请求失败/超时 -> 自动切换备用LLM(GLM-4)
2. 备用LLM也失败 -> 规则引擎兜底 + degraded:true 标记
3. 辩证类返回规则引擎兜底结果, 生成类返回 LLM-DOWN-001(503)
"""
import time
import random
from typing import Optional, Dict, Any
from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass
class LLMStatus:
    """LLM服务状态"""
    name: str
    available: bool = True
    last_check: float = 0.0
    fail_count: int = 0
    last_error: str = ""


@dataclass
class FallbackResult:
    """降级链返回结果"""
    data: Dict[str, Any]
    degraded: bool = False
    used_llm: str = ""
    fallback_chain: list = field(default_factory=list)
    error: str = ""


class LLMFallbackChain:
    """LLM降级链管理器"""

    def __init__(self):
        self.providers = [
            LLMStatus(name="deepseek"),
            LLMStatus(name="glm-4"),
        ]
        self._health_check_interval = 60  # 60秒检查一次
        self._max_fail_count = 3  # 连续失败3次标记不可用

    def _now(self) -> float:
        return time.time()

    def record_success(self, provider_name: str):
        """记录LLM调用成功"""
        for p in self.providers:
            if p.name == provider_name:
                p.available = True
                p.fail_count = 0
                p.last_check = self._now()
                break

    def record_failure(self, provider_name: str, error: str = ""):
        """记录LLM调用失败"""
        for p in self.providers:
            if p.name == provider_name:
                p.fail_count += 1
                p.last_error = error
                p.last_check = self._now()
                if p.fail_count >= self._max_fail_count:
                    p.available = False
                break

    def get_available_provider(self) -> Optional[LLMStatus]:
        """获取当前可用的LLM提供商"""
        now = self._now()
        for p in self.providers:
            # 健康检查: 如果上次检查超过间隔时间，重置为可用尝试
            if not p.available and (now - p.last_check) > self._health_check_interval:
                p.available = True
                p.fail_count = 0
            if p.available:
                return p
        return None

    def get_status(self) -> list:
        """获取所有LLM状态"""
        return [
            {
                "name": p.name,
                "available": p.available,
                "fail_count": p.fail_count,
                "last_error": p.last_error,
                "last_check": datetime.fromtimestamp(
                    p.last_check, tz=timezone.utc
                ).isoformat() if p.last_check else None,
            }
            for p in self.providers
        ]

    async def call_with_fallback(
        self,
        prompt: str,
        system_prompt: str = "",
        is_generative: bool = False,
        mock_llm_call=None,
    ) -> FallbackResult:
        """
        带降级的LLM调用

        Args:
            prompt: 用户输入
            system_prompt: 系统提示词
            is_generative: True=生成类(失败返回503), False=辩证类(失败返回规则引擎兜底)
            mock_llm_call: 模拟LLM调用函数(用于测试), 签名: (provider_name, prompt) -> dict|None

        Returns:
            FallbackResult
        """
        chain = []
        result = FallbackResult(data={}, fallback_chain=chain)

        for provider in self.providers:
            if not provider.available:
                chain.append(f"{provider.name}: 不可用(跳过)")
                continue

            chain.append(f"{provider.name}: 尝试调用...")

            try:
                # 实际调用 or 模拟调用
                if mock_llm_call:
                    llm_result = mock_llm_call(provider.name, prompt)
                else:
                    # TODO: 实际LLM调用，这里用模拟逻辑
                    # 真实环境会调用DeepSeek/GLM-4的API
                    llm_result = self._mock_call(provider.name, prompt)

                if llm_result:
                    self.record_success(provider.name)
                    chain.append(f"{provider.name}: 成功")
                    result.data = llm_result
                    result.used_llm = provider.name
                    result.degraded = False
                    return result
                else:
                    raise Exception("LLM返回空结果")

            except Exception as e:
                self.record_failure(provider.name, str(e))
                chain.append(f"{provider.name}: 失败 - {str(e)}")
                continue

        # 所有LLM都失败
        if is_generative:
            # 生成类: 返回503
            result.error = "LLM_DOWN"
            result.data = {
                "error": "LLM-DOWN-001",
                "message": "AI服务暂不可用，请稍后重试",
            }
            result.degraded = True
        else:
            # 辩证类: 规则引擎兜底
            chain.append("规则引擎兜底")
            result.data = self._rule_engine_fallback(prompt)
            result.degraded = True
            result.used_llm = "rule_engine"

        return result

    def _mock_call(self, provider_name: str, prompt: str) -> Optional[dict]:
        """模拟LLM调用（开发环境用）"""
        # 模拟10%失败率
        if random.random() < 0.1:
            raise Exception(f"{provider_name} 模拟超时")
        return {
            "content": f"[{provider_name}] 基于输入'{prompt[:50]}'的分析结果",
            "provider": provider_name,
            "tokens": len(prompt) // 2 + 100,
        }

    def _rule_engine_fallback(self, prompt: str) -> dict:
        """规则引擎兜底（辩证类）"""
        return {
            "content": "基于规则引擎的初步分析（LLM不可用时的降级结果）",
            "syndromes": [],
            "reasoning_chain": ["规则引擎兜底模式"],
            "degraded": True,
            "disclaimer": "当前为降级模式，结果仅供参考，建议稍后重试获取完整AI分析",
        }


# 全局单例
llm_fallback = LLMFallbackChain()
