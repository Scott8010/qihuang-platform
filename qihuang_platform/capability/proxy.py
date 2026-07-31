"""
中台能力代理客户端 — 将商业化平台请求透传到现有 API (8601)

策略：
- 不动现有 api/ 代码
- 在平台层做鉴权验证后，以内部 API Key 转发到 8601
- 响应统一包装为 {code, message, data, trace_id}
"""
import httpx
from typing import Optional, Dict, Any
from qihuang_platform.gateway.response import success, error


# 现有 API 基础地址
BACKEND_BASE = "http://localhost:8601"

# 内部 API Key（平台→现有API的认证凭据）
INTERNAL_API_KEY = "qihuang-platform-internal-key-dev"


class BackendProxy:
    """透传代理到现有 8601 API"""

    def __init__(self, base_url: str = BACKEND_BASE, api_key: str = INTERNAL_API_KEY):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self._client: Optional[httpx.AsyncClient] = None

    async def get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                headers={"X-API-Key": self.api_key},
                timeout=120.0,
            )
        return self._client

    async def close(self):
        if self._client:
            await self._client.aclose()
            self._client = None

    async def forward(
        self,
        method: str,
        path: str,
        params: Optional[Dict[str, Any]] = None,
        json_body: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        """
        透传请求到现有 API。

        返回统一格式的响应字典。
        """
        client = await self.get_client()
        try:
            resp = await client.request(
                method=method,
                url=path,
                params=params,
                json=json_body,
                headers=headers or {},
            )
            # 尝试解析 JSON
            try:
                body = resp.json()
            except Exception:
                body = resp.text

            if resp.is_success:
                return success(data=body)
            else:
                return error(
                    code_key="SERVICE_UNAVAILABLE",
                    message=f"后端服务返回错误: {resp.status_code}",
                    data=body,
                )
        except httpx.TimeoutException:
            return error(code_key="UPSTREAM_TIMEOUT", message="后端服务超时")
        except httpx.ConnectError:
            return error(code_key="SERVICE_UNAVAILABLE", message="后端服务不可达 (8601)")
        except Exception as e:
            return error(code_key="INTERNAL_ERROR", message=f"透传异常: {str(e)}")


# 全局单例
proxy = BackendProxy()
