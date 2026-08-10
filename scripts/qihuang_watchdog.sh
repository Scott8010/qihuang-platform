#!/usr/bin/env bash
# -*- coding: utf-8 -*-
#
# 岐黄智脑平台 · 进程自愈看门狗
# 探活 http://127.0.0.1:8602/platform/health
#   - 正常(200): 清零失败计数, 退出
#   - 连续失败 >=2 次: 重启 qihuang-admin 服务
#   - 重启后仍失败: PushPlus 推送"自愈失败, 需人工介入"
#
# 部署: 由 cron 每 2 分钟调用:
#   */2 * * * * /bin/bash /root/qihuang_watchdog.sh >>/root/watchdog.cron 2>&1
#
set -u

HEALTH_URL=http://127.0.0.1:8602/platform/health
ALERT=/root/qihuang_alert.py
STATE=/root/.qihuang_watchdog_failcount
MAX_FAIL=2
RESTART_LOG=/root/watchdog.log

fail_count=$(cat "$STATE" 2>/dev/null || echo 0)

code=$(curl -s -o /dev/null -w "%{http_code}" --max-time 8 "$HEALTH_URL" 2>/dev/null)

if [ "$code" = "200" ]; then
    echo 0 > "$STATE"
    exit 0
fi

# 探活失败
fail_count=$((fail_count + 1))
echo "$fail_count" > "$STATE"
echo "[$(date '+%F %T')] health=$code fail_count=$fail_count" >> "$RESTART_LOG"

if [ "$fail_count" -ge "$MAX_FAIL" ]; then
    echo "[$(date '+%F %T')] restarting qihuang-admin (health was $code)" >> "$RESTART_LOG"
    systemctl restart qihuang-admin
    sleep 12
    code2=$(curl -s -o /dev/null -w "%{http_code}" --max-time 8 "$HEALTH_URL" 2>/dev/null)
    if [ "$code2" = "200" ]; then
        echo 0 > "$STATE"
        python3 "$ALERT" "岐黄平台自愈成功" "health 曾=$code, 已自动重启, 现恢复=$code2" >> "$RESTART_LOG" 2>&1
        echo "[$(date '+%F %T')] recovered (now $code2)" >> "$RESTART_LOG"
    else
        python3 "$ALERT" "⚠️岐黄平台自愈失败" "health 曾=$code, 重启后仍=$code2, 需人工介入" >> "$RESTART_LOG" 2>&1
        echo "[$(date '+%F %T')] SELF-HEAL FAILED (still $code2)" >> "$RESTART_LOG"
    fi
fi
