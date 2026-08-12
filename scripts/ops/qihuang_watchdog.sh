#!/usr/bin/env bash
# -*- coding: utf-8 -*-
#
# 岐黄智脑平台 · 进程自愈看门狗 (生产加固版 v2)
# ============================================================
# 探活对象:
#   8602 商业化平台  -> 自愈: systemctl restart qihuang-admin
#   8601 知识库      -> 自愈: docker restart app-api-1
#   容器 app-neo4j-1 / qh-postgres / qh-redis -> 自愈: docker start
#   资源 磁盘/内存   -> 仅告警, 不重启
# 防重启风暴: 每个组件单次故障仅重启一次 (restarted 标记, 健康即清零)
# 防告警刷屏: 持续异常汇总告警节流 30 分钟 (alert_summary_last 时间戳)
# 自愈成功为一次性正向事件, 立即推送; 全健康时不推送 (仅写日志)
#
# 部署: cron 每 2 分钟
#   */2 * * * * /bin/bash /root/qihuang_watchdog.sh >>/root/watchdog.cron 2>&1
#
set -u

ALERT=/root/qihuang_alert.py
STATE_DIR=/root/.qihuang_watchdog
mkdir -p "$STATE_DIR"
MAX_FAIL=2
RESTART_SLEEP=15
ALERT_COOLDOWN=1800   # 秒, 持续异常汇总告警节流
LOG=/root/watchdog.log

OVERALL_OK=1
RESULT_MSGS=()

probe_http() {  # $1=url -> 0 健康 / 1 异常
    local code
    code=$(curl -s -o /dev/null -w "%{http_code}" --max-time 8 "$1" 2>/dev/null)
    [ "$code" = "200" ] && return 0 || return 1
}
container_up() {  # $1=name -> 0 运行 / 1 停止
    local st
    st=$(docker inspect -f '{{.State.Running}}' "$1" 2>/dev/null)
    [ "$st" = "true" ] && return 0 || return 1
}

# 节流告警: 同 key 30 分钟内最多一次 (返回 0=已推送 1=被节流)
maybe_alert() {  # $1=key $2=title $3=content
    local key="$1" title="$2" content="$3"
    local lastf="$STATE_DIR/alert_${key}_last"
    local now; now=$(date +%s)
    local last; last=$(cat "$lastf" 2>/dev/null || echo 0)
    if [ $((now - last)) -ge "$ALERT_COOLDOWN" ]; then
        python3 "$ALERT" "$title" "$content" >> "$LOG" 2>&1
        echo "$now" > "$lastf"
        return 0
    fi
    return 1
}

# 通用 HTTP 自愈
watch_http() {  # $1=显示名 $2=url $3=重启命令
    local name="$1" url="$2" rcmd="$3"
    local fc="$STATE_DIR/${name}_fail" rg="$STATE_DIR/${name}_restarted"
    if probe_http "$url"; then
        echo 0 > "$fc"; echo 0 > "$rg"
        return 0
    fi
    local n; n=$(cat "$fc" 2>/dev/null || echo 0); n=$((n + 1)); echo "$n" > "$fc"
    if [ "$n" -ge "$MAX_FAIL" ]; then
        if [ "$(cat "$rg" 2>/dev/null)" != "1" ]; then
            echo 1 > "$rg"
            eval "$rcmd" >/dev/null 2>&1
            sleep "$RESTART_SLEEP"
            if probe_http "$url"; then
                echo 0 > "$fc"; echo 0 > "$rg"
                python3 "$ALERT" "$name 自愈成功" "$name 曾异常, 已自动重启恢复" >> "$LOG" 2>&1
                return 0
            else
                OVERALL_OK=0
                RESULT_MSGS+=("$name: 自愈失败(重启后仍异常)")
                return 1
            fi
        else
            OVERALL_OK=0
            RESULT_MSGS+=("$name: 持续异常(已重启待恢复)")
            return 1
        fi
    else
        OVERALL_OK=0
        RESULT_MSGS+=("$name: 探活失败($n/$MAX_FAIL)")
        return 1
    fi
}

# 通用容器自愈
watch_container() {  # $1=容器名
    local c="$1"
    local fc="$STATE_DIR/${c}_down" rg="$STATE_DIR/${c}_restarted"
    if container_up "$c"; then
        echo 0 > "$fc"; echo 0 > "$rg"
        return 0
    fi
    local n; n=$(cat "$fc" 2>/dev/null || echo 0); n=$((n + 1)); echo "$n" > "$fc"
    if [ "$n" -ge "$MAX_FAIL" ]; then
        if [ "$(cat "$rg" 2>/dev/null)" != "1" ]; then
            echo 1 > "$rg"
            docker start "$c" >/dev/null 2>&1
            sleep "$RESTART_SLEEP"
            if container_up "$c"; then
                echo 0 > "$fc"; echo 0 > "$rg"
                python3 "$ALERT" "容器自愈成功" "$c 曾停止, 已自动 docker start" >> "$LOG" 2>&1
                return 0
            else
                OVERALL_OK=0
                RESULT_MSGS+=("$c: 自愈失败(重启后仍停止)")
                return 1
            fi
        else
            OVERALL_OK=0
            RESULT_MSGS+=("$c: 持续停止(已重启待恢复)")
            return 1
        fi
    else
        OVERALL_OK=0
        RESULT_MSGS+=("$c: 未运行($n/$MAX_FAIL)")
        return 1
    fi
}

# ---------- 执行 ----------
watch_http     "8602平台"   "http://127.0.0.1:8602/platform/health" "systemctl restart qihuang-admin"
watch_http     "8601知识库" "http://127.0.0.1:8601/health"           "docker restart app-api-1"
watch_container "app-neo4j-1"
watch_container "qh-postgres"
watch_container "qh-redis"

# ---------- 资源压力 (仅告警) ----------
DISK=$(df -P / 2>/dev/null | awk 'NR==2{gsub("%",""); print $5}')
MEM_AVAIL_MB=$(free -m 2>/dev/null | awk '/Mem:/{print $7}')
if [ "${DISK:-0}" -ge 85 ]; then
    OVERALL_OK=0; RESULT_MSGS+=("磁盘:${DISK}%")
fi
if [ "${MEM_AVAIL_MB:-999999}" -lt 500 ]; then
    OVERALL_OK=0; RESULT_MSGS+=("内存:${MEM_AVAIL_MB}MB")
fi

# ---------- 汇总 (节流) ----------
if [ "$OVERALL_OK" -eq 1 ]; then
    echo "[$(date '+%F %T')] all healthy" >> "$LOG"
else
    SUMMARY="$(IFS='; '; echo "${RESULT_MSGS[*]}")"
    maybe_alert "summary" "⚠️ 岐黄健康检查异常" "$SUMMARY"
fi
exit 0
