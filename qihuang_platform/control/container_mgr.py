"""
容器管理与自动恢复模块 — 运维端核心

功能:
1. docker ps 查询容器运行状态
2. docker restart 重启容器
3. 自动恢复: 检测到容器异常Down时自动拉起
4. 恢复日志: 记录每次自动恢复操作
"""
import subprocess
import json
import threading
import time
from datetime import datetime, timezone
from collections import deque
from typing import Optional


class ContainerInfo:
    def __init__(self, name: str, status: str = "unknown", image: str = "",
                 ports: str = "", uptime: str = "", cpu: str = "", memory: str = ""):
        self.name = name
        self.status = status
        self.image = image
        self.ports = ports
        self.uptime = uptime
        self.cpu = cpu
        self.memory = memory

    def to_dict(self):
        return {
            "name": self.name, "status": self.status, "image": self.image,
            "ports": self.ports, "uptime": self.uptime,
            "cpu": self.cpu, "memory": self.memory,
        }


class ContainerManager:
    """容器管理器 — 单例"""

    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._init()
        return cls._instance

    def _init(self):
        self._recovery_config: dict[str, bool] = {}       # container_name -> auto_recovery_enabled
        self._recovery_logs: deque = deque(maxlen=200)    # 最近200条恢复记录
        self._last_check_time: Optional[datetime] = None

    # ── Docker CLI 交互 ──

    def _run_docker(self, args: list) -> tuple[bool, str]:
        """执行docker命令，返回(success, output)"""
        try:
            result = subprocess.run(
                ["docker"] + args,
                capture_output=True, text=True, timeout=15,
                shell=False,
            )
            return result.returncode == 0, result.stdout.strip()
        except FileNotFoundError:
            return False, "DOCKER_NOT_FOUND"
        except subprocess.TimeoutExpired:
            return False, "TIMEOUT"
        except Exception as e:
            return False, str(e)

    def list_containers(self) -> list[ContainerInfo]:
        """获取所有容器状态"""
        ok, output = self._run_docker([
            "ps", "-a", "--format",
            "{{.Names}}\t{{.Status}}\t{{.Image}}\t{{.Ports}}",
            "--no-trunc",
        ])
        if not ok:
            # Docker不可用时返回mock数据用于开发调试
            return self._mock_containers()

        containers = []
        for line in output.split("\n"):
            if not line.strip():
                continue
            parts = line.split("\t")
            if len(parts) < 4:
                continue
            name, status, image, ports = parts[0], parts[1], parts[2], parts[3]

            # 判断状态
            if status.lower().startswith("up"):
                container_status = "running"
                # 尝试解析uptime
                uptime = status[3:] if len(status) > 3 else ""
            elif status.lower().startswith("exited"):
                container_status = "stopped"
                uptime = status
            else:
                container_status = "unknown"
                uptime = status

            containers.append(ContainerInfo(
                name=name, status=container_status, image=image,
                ports=ports, uptime=uptime,
            ))

        # 补上stats（docker stats --no-stream 较慢，异步获取）
        self._enrich_stats(containers)
        return containers

    def _enrich_stats(self, containers: list[ContainerInfo]):
        """获取CPU/内存统计"""
        names = [c.name for c in containers if c.status == "running"]
        if not names:
            return
        name_filter = "|".join(names)
        ok, output = self._run_docker([
            "stats", "--no-stream",
            "--format", "{{.Name}}\t{{.CPUPerc}}\t{{.MemPerc}}",
        ])
        if not ok:
            return
        for line in output.split("\n"):
            parts = line.split("\t")
            if len(parts) >= 3:
                name = parts[0]
                cpu = parts[1]
                mem = parts[2]
                for c in containers:
                    if c.name == name:
                        c.cpu = cpu
                        c.memory = mem

    def restart_container(self, name: str) -> tuple[bool, str]:
        """重启指定容器"""
        ok, output = self._run_docker(["restart", name])
        if ok:
            return True, f"容器 {name} 重启成功"
        elif output == "DOCKER_NOT_FOUND":
            return True, f"容器 {name} 重启指令已发送(Mock)"
        else:
            return False, f"容器 {name} 重启失败: {output}"

    def _mock_containers(self) -> list[ContainerInfo]:
        """开发环境Mock数据"""
        return [
            ContainerInfo("qihuang-api", "running", "qihuang-brain:v2.3", "8601->8601", "3天12小时", "12.4%", "256MB/2GB"),
            ContainerInfo("qihuang-platform", "running", "qihuang-platform:latest", "8602->8602", "3天12小时", "8.7%", "180MB/2GB"),
            ContainerInfo("postgres-qh", "running", "postgres:15-alpine", "5432->5432", "3天12小时", "2.1%", "512MB/2GB"),
            ContainerInfo("redis-qh", "running", "redis:7-alpine", "6379->6379", "3天12小时", "0.5%", "32MB/2GB"),
            ContainerInfo("neo4j-qh", "stopped", "neo4j:5-community", "7474,7687", "Exited (137) 2小时前", "-", "-"),
        ]

    def check_health(self) -> dict:
        """检查所有容器健康状态，对有自动恢复且异常的容器执行恢复"""
        self._last_check_time = datetime.now(timezone.utc)
        containers = self.list_containers()
        recovered = []

        for c in containers:
            if c.status != "running" and self._recovery_config.get(c.name, False):
                # 自动恢复
                ok, msg = self.restart_container(c.name)
                self._log_recovery(c.name, ok, msg)
                if ok:
                    recovered.append(c.name)

        return {
            "containers": [c.to_dict() for c in containers],
            "auto_recovery": dict(self._recovery_config),
            "recovered_count": len(recovered),
            "recovered": recovered,
            "checked_at": self._last_check_time.isoformat(),
        }

    # ── 自动恢复配置 ──

    def set_auto_recovery(self, name: str, enabled: bool) -> dict:
        self._recovery_config[name] = enabled
        action = "启用" if enabled else "停用"
        self._log_recovery(name, True, f"管理员{action}自动恢复")
        return {"name": name, "auto_recovery": enabled}

    def get_auto_recovery_config(self) -> dict:
        return dict(self._recovery_config)

    # ── 恢复日志 ──

    def _log_recovery(self, name: str, success: bool, detail: str):
        entry = {
            "time": datetime.now(timezone.utc).isoformat(),
            "container": name,
            "success": success,
            "detail": detail,
        }
        self._recovery_logs.append(entry)

    def get_recovery_logs(self, limit: int = 50) -> list:
        logs = list(self._recovery_logs)
        return logs[-limit:]


# 全局单例
container_mgr = ContainerManager()
