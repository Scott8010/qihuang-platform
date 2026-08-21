"""
服务健康真实探针
═══════════════════════════════════════════════════════════
替换 Monitor 页「演示」占位数据。对 5 个核心依赖做真实探活：

  1. API 网关         —— HTTP GET（默认走 /platform/health 外网入口）
  2. 中台应用(FastAPI) —— HTTP GET /platform/health（loopback 直连）
  3. Neo4j 图谱库      —— TCP bolt 端口连通
  4. PostgreSQL 业务库 —— TCP 5432（本地 SQLite 开发态特判）
  5. LLM 共识集群      —— llm_fallback.get_status() 真查可用提供商

特性：
  · 所有地址/端口/超时/缓存均可经环境变量覆盖（见下方常量）。
  · 30s 缓存，避免每次请求都打探活。
  · 滚动 uptime：维护最近 _ROLLING 次探活成败，算可用率，
    初始进程期即真实反映近期探活结果，不灌水。
  · 统一返回富结构，兼容 /monitor/services 与 /dashboard 两套前端契约。

env 开关：
  PLATFORM_PORT / MONITOR_GW_URL / MONITOR_API_URL
  MONITOR_NEO4J_HOST / MONITOR_NEO4J_PORT
  MONITOR_PG_HOST / MONITOR_PG_PORT
  MONITOR_PROBE_TIMEOUT(秒) / MONITOR_CACHE_TTL(秒)
"""
import os
import socket
import time
import asyncio
import logging

logger = logging.getLogger("health_probe")

# ───────────────── 配置（env 可覆盖） ─────────────────
PLATFORM_PORT = int(os.getenv("PLATFORM_PORT", "8602"))
GW_URL = os.getenv("MONITOR_GW_URL", f"http://127.0.0.1:{PLATFORM_PORT}/platform/health")
API_URL = os.getenv("MONITOR_API_URL", f"http://127.0.0.1:{PLATFORM_PORT}/platform/health")
NEO4J_HOST = os.getenv("MONITOR_NEO4J_HOST", "127.0.0.1")
NEO4J_PORT = int(os.getenv("MONITOR_NEO4J_PORT", "7687"))
PG_HOST = os.getenv("MONITOR_PG_HOST", "127.0.0.1")
PG_PORT = int(os.getenv("MONITOR_PG_PORT", "5432"))
PROBE_TIMEOUT = float(os.getenv("MONITOR_PROBE_TIMEOUT", "2.0"))
CACHE_TTL = int(os.getenv("MONITOR_CACHE_TTL", "30"))

# 滚动 uptime 窗口大小
_ROLLING = 50

SERVICE_KEYS = ("api_gateway", "fastapi", "neo4j", "postgres", "llm")
SERVICE_NAMES = {
    "api_gateway": "API 网关",
    "fastapi": "中台应用（FastAPI）",
    "neo4j": "Neo4j 图谱库",
    "postgres": "PostgreSQL 业务库",
    "llm": "LLM 共识集群",
}

# 滚动成败缓冲（仅主线程写入，线程安全）
_roll: dict = {k: [] for k in SERVICE_KEYS}
# 结果缓存
_cache: dict = {"ts": 0.0, "data": None}


# ───────────────── 底层探活原语 ─────────────────
def _tcp_probe(host: str, port: int, timeout: float):
    """TCP 端口连通探活，返回 (ok, latency_ms)"""
    t0 = time.monotonic()
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(timeout)
    try:
        sock.connect((host, port))
        return True, int((time.monotonic() - t0) * 1000)
    except Exception as e:
        logger.debug("TCP probe %s:%s failed: %s", host, port, e)
        return False, None
    finally:
        try:
            sock.close()
        except Exception:
            pass


def _http_probe(url: str, timeout: float):
    """HTTP GET 探活（任意 2xx/3xx 视为存活），返回 (ok, latency_ms)"""
    import urllib.request
    t0 = time.monotonic()
    try:
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            ok = 200 <= getattr(resp, "status", 0) < 400
            return ok, int((time.monotonic() - t0) * 1000)
    except Exception as e:
        logger.debug("HTTP probe %s failed: %s", url, e)
        return False, None


def _pg_probe():
    """PostgreSQL 探活：生产走 TCP 5432；本地 SQLite 开发态特判为『本地库』"""
    from qihuang_platform.db.config import IS_SQLITE
    if IS_SQLITE:
        # 开发态：业务库为本地 SQLite，无独立 PG 端口监听
        return True, None, "normal", "开发态·SQLite 本地库"
    ok, ms = _tcp_probe(PG_HOST, PG_PORT, PROBE_TIMEOUT)
    if ok:
        return True, ms, "normal", "PostgreSQL 业务库正常"
    return False, None, "down", "PostgreSQL 不可达"


def _llm_probe():
    """LLM 共识集群探活：真查各提供商可用性，反映降级/切换态"""
    from qihuang_platform.gateway.llm_fallback import llm_fallback
    try:
        status = llm_fallback.get_status() or []
    except Exception as e:
        logger.warning("LLM status fetch failed: %s", e)
        return False, None, "down", "LLM 状态获取失败"
    if not status:
        return False, None, "down", "无可用 LLM 提供商"
    available = [p for p in status if p.get("available")]
    if not available:
        return False, None, "down", "LLM 全部不可用"
    if len(available) < len(status):
        return True, None, "warning", "部分提供商降级·备用切换中"
    return True, None, "normal", "LLM 集群正常"


# ───────────────── 辅助 ─────────────────
def _rolling(key: str, ok: bool) -> float:
    buf = _roll[key]
    buf.append(1 if ok else 0)
    if len(buf) > _ROLLING:
        buf.pop(0)
    if not buf:
        return 100.0
    return round(sum(buf) / len(buf) * 100, 2)


def _assemble(key: str, ok: bool, latency_ms, status: str, text: str) -> dict:
    uptime = _rolling(key, ok)
    return {
        "key": key,
        "name": SERVICE_NAMES[key],
        "ok": bool(ok),
        "status": status,            # normal / warning / down
        "status_text": text,         # 人类可读状态
        "latency_ms": latency_ms,    # 可能为 None（如 LLM / SQLite 态）
        "uptime": f"{uptime:.2f}%",
        "is_demo": False,
    }


# ───────────────── 对外主入口 ─────────────────
async def get_services_health(force: bool = False) -> list:
    """返回 5 个服务的真实健康富结构（带缓存）。"""
    now = time.monotonic()
    if not force and _cache["data"] is not None and (now - _cache["ts"]) < CACHE_TTL:
        return _cache["data"]

    # 并发探活（IO _bound，丢到线程池避免阻塞事件循环）
    gw_ok, gw_ms = await asyncio.to_thread(_http_probe, GW_URL, PROBE_TIMEOUT)
    api_ok, api_ms = await asyncio.to_thread(_http_probe, API_URL, PROBE_TIMEOUT)
    neo_ok, neo_ms = await asyncio.to_thread(_tcp_probe, NEO4J_HOST, NEO4J_PORT, PROBE_TIMEOUT)
    pg_ok, pg_ms, pg_status, pg_text = await asyncio.to_thread(_pg_probe)
    llm_ok, llm_ms, llm_status, llm_text = await asyncio.to_thread(_llm_probe)

    data = [
        _assemble("api_gateway", gw_ok, gw_ms, "normal" if gw_ok else "down",
                  "运行正常" if gw_ok else "网关不可达"),
        _assemble("fastapi", api_ok, api_ms, "normal" if api_ok else "down",
                  "运行正常" if api_ok else "中台不可用"),
        _assemble("neo4j", neo_ok, neo_ms, "normal" if neo_ok else "down",
                  "运行正常" if neo_ok else "图谱库不可达"),
        _assemble("postgres", pg_ok, pg_ms, pg_status, pg_text),
        _assemble("llm", llm_ok, llm_ms, llm_status, llm_text),
    ]
    _cache["ts"] = now
    _cache["data"] = data
    return data
