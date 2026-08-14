"""共享多模态视觉客户端（OpenAI 兼容 vision 端点）。

把图片引用解析为视觉端点可用的 image_url，并调用 chat/completions 视觉模型。
供 fortune（户型图解析）与 compliance（内容图片/视频审核）共用，避免两处漂移。

配置（环境变量，进程级）：
  {ENV_PREFIX}_API_BASE  e.g. https://api.openai.com/v1
  {ENV_PREFIX}_API_KEY
  {ENV_PREFIX}_MODEL     e.g. gpt-4o-mini / qwen-vl / deepseek-vl
compliance 默认优先读 COMPLIANCE_VISION_*，缺失则回退 GEO_VISION_*（共用同一视觉网关）。
未配置或失败均安全回退（由调用方决定降级策略，本模块只抛/回退，不阻断主流程）。
"""
from __future__ import annotations

import base64
import json
import mimetypes
import os
import re
import urllib.request


def to_image_url(ref: str) -> str:
    """把图片引用转成视觉端点可用的 image_url。

    - data URI：直用（已内联，最快、不依赖视觉端点跨网抓取）
    - http(s) URL：服务端先下载转 base64 data URI，规避视觉端点出网白名单/慢链路超时；
      下载失败则回退原样（交由视觉端点尝试，再失败由上层回退）
    - 本地路径：读文件转 base64
    - 其它：原样返回（可能失败，由上层捕获回退）
    """
    if not ref:
        return ref
    if ref.startswith("data:"):
        return ref
    if ref.startswith(("http://", "https://")):
        try:
            req = urllib.request.Request(ref, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=20) as resp:
                ctype = resp.headers.get_content_type() or "image/jpeg"
                b64 = base64.b64encode(resp.read()).decode("ascii")
            return f"data:{ctype};base64,{b64}"
        except Exception:
            return ref
    if os.path.exists(ref):
        mime = mimetypes.guess_type(ref)[0] or "image/jpeg"
        with open(ref, "rb") as f:
            b64 = base64.b64encode(f.read()).decode("ascii")
        return f"data:{mime};base64,{b64}"
    return ref


def vision_chat_json(base: str, key: str, model: str, image_ref: str, prompt: str) -> str:
    """调用 OpenAI 兼容视觉端点，返回模型文本（期望 JSON 或描述文本）。"""
    url = f"{base.rstrip('/')}/chat/completions"
    payload = {
        "model": model,
        "messages": [{
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": to_image_url(image_ref)}},
            ],
        }],
        "temperature": 0.2,
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        out = json.loads(resp.read().decode("utf-8"))
    return out["choices"][0]["message"]["content"]


def normalize_vision_json(content: str) -> dict:
    """从视觉模型输出中抽取首个 JSON 对象（兼容纯 JSON / ```json 代码块 / 夹带文字）。

    通用抽取，不绑定具体业务键；业务方自行对返回 dict 做字段归一化。
    """
    raw: dict = {}
    try:
        raw = json.loads(content)
    except Exception:
        raw = {}
    if not isinstance(raw, dict) or not raw:
        m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", content, re.S)
        if m:
            try:
                raw = json.loads(m.group(1))
            except Exception:
                raw = {}
    if not isinstance(raw, dict) or not raw:
        m = re.search(r"\{.*?\}", content, re.S)
        if m:
            try:
                raw = json.loads(m.group(0))
            except Exception:
                raw = {}
    if not isinstance(raw, dict):
        raw = {}
    return raw


def _read_vision_env(env_prefix: str, fallback_prefix: str):
    base = os.environ.get(f"{env_prefix}_API_BASE") or os.environ.get(f"{fallback_prefix}_API_BASE", "")
    key = os.environ.get(f"{env_prefix}_API_KEY") or os.environ.get(f"{fallback_prefix}_API_KEY", "")
    model = os.environ.get(f"{env_prefix}_MODEL") or os.environ.get(f"{fallback_prefix}_MODEL", "gpt-4o-mini")
    return base.rstrip("/"), key, model


def vision_analyze(image_ref: str, prompt: str,
                   env_prefix: str = "GEO_VISION", fallback_prefix: str = "GEO_VISION") -> dict:
    """高层入口：图片走视觉模型解析，返回结构化结果。

    返回 dict：
      - mode="vision"        ：成功，含 text（模型输出）/ model / raw
      - mode="image_pending" ：未配置视觉模型，仅占位（不阻断）
      - mode="image_error"   ：调用失败，安全回退（不阻断）
    各 mode 均带 note 说明，便于前端如实展示（数据真实性原则）。
    """
    if not image_ref:
        return {"provided": False, "mode": "image_pending", "note": "未提供图片"}
    base, key, model = _read_vision_env(env_prefix, fallback_prefix)
    if not (base and key):
        return {"provided": True, "mode": "image_pending",
                "note": f"图片已接收，但未配置视觉模型（{env_prefix}_API_BASE/KEY），"
                        f"当前仅按文本审核。",
                "raw_hint": image_ref[:120]}
    try:
        content = vision_chat_json(base, key, model, image_ref, prompt)
        return {"provided": True, "mode": "vision", "model": model,
                "text": content, "raw": content[:500]}
    except Exception as e:
        return {"provided": True, "mode": "image_error",
                "note": f"视觉模型解析失败（{e}），回退为仅文本审核。",
                "raw_hint": image_ref[:120]}
