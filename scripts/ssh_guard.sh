#!/bin/bash
# SSH 防爆破守卫 - 零依赖替代 fail2ban（OpenCloudOS 无 fail2ban/EPEL 源）
# 部署：/root/ssh_guard.sh + cron 每 5 分钟
# 逻辑：扫描 /var/log/secure 失败登录，单 IP 失败 >= THRESHOLD 次即 firewalld 永久封禁
THRESHOLD=30
LOGFILE="/var/log/secure"
BANLOG="/root/ssh_guard_banned.log"
# 白名单：本机 + 老黄常用出口 IP（防误封）
WHITELIST="127.0.0.1 116.234.27.49 111.231.63.73"

[ -f "$LOGFILE" ] || exit 0

# 当前已封禁 IP（避免重复封禁 + 重复 reload）
BANNED_NOW=$(firewall-cmd --list-rich-rules 2>/dev/null | grep -oE '([0-9]{1,3}\.){3}[0-9]{1,3}')

CHANGED=0
while read -r COUNT IP; do
    [ -z "$IP" ] && continue
    [ "$COUNT" -lt "$THRESHOLD" ] && continue
    echo "$WHITELIST" | grep -qw "$IP" && continue
    echo "$BANNED_NOW" | grep -qw "$IP" && continue
    firewall-cmd --permanent --add-rich-rule="rule family=ipv4 source address=$IP reject" >/dev/null 2>&1
    echo "$(date '+%F %T') BANNED $IP (failed=$COUNT)" >> "$BANLOG"
    CHANGED=1
done < <(grep 'Failed password' "$LOGFILE" 2>/dev/null | grep -oE '([0-9]{1,3}\.){3}[0-9]{1,3}' | sort | uniq -c | sort -rn | head -50)

[ "$CHANGED" = "1" ] && firewall-cmd --reload >/dev/null 2>&1
exit 0
