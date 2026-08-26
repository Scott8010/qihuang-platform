#!/usr/bin/env bash
# Fix cdn.yshealth.com.cn.conf - add location / reverse proxy to 127.0.0.1:8602
# Safe to re-run: greps for existing proxy_pass first.
set -e

CDN=${1:-/etc/nginx/conf.d/cdn.yshealth.com.cn.conf}
if [ ! -f "$CDN" ]; then
  echo "[fix-cdn-nginx] $CDN not found, nothing to do"
  exit 0
fi

# Already fixed?
if grep -q 'proxy_pass http://127.0.0.1:8602;' "$CDN"; then
  echo "[fix-cdn-nginx] already has 8602 proxy, skip"
  exit 0
fi

BACKUP="${CDN}.bak.$(date +%Y%m%d_%H%M%S)"
cp -p "$CDN" "$BACKUP"
echo "[fix-cdn-nginx] backup -> $BACKUP"

# Insert a server-block-internal location before the LAST '}' line of the file
# (most nginx server blocks end with a single '}' on its own line).
# Use Python for safe multi-line insertion; fall back to awk if python3 is missing.

LOCATION_CONTENT='    # nginx-fix-cdn: forward unmatched paths to 8602 (was returning nginx 404 for SNI=cdn.yshealth.com.cn)
    location / {
        proxy_pass http://127.0.0.1:8602;
        proxy_set_header Host              $host;
        proxy_set_header X-Real-IP         $remote_addr;
        proxy_set_header X-Forwarded-For   $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 120s;
        proxy_connect_timeout 10s;
    }
'

if command -v python3 >/dev/null 2>&1; then
  python3 - "$CDN" "$LOCATION_CONTENT" <<'PYEOF'
import sys, re
path = sys.argv[1]
loc  = sys.argv[2]
src = open(path, encoding='utf-8').read()
# Insert location before the LAST '}' that closes the outermost server block.
# Strategy: find every top-level "}" (line that is exactly "}"), insert before the last one.
lines = src.splitlines(keepends=True)
brace_close_indexes = [i for i, ln in enumerate(lines) if ln.strip() == '}']
if not brace_close_indexes:
    print('[fix-cdn-nginx] ERROR: no top-level "}" found, abort', file=sys.stderr)
    sys.exit(1)
last_brace = brace_close_indexes[-1]
new_lines = lines[:last_brace] + [loc] + lines[last_brace:]
open(path, 'w', encoding='utf-8').write(''.join(new_lines))
print(f'[fix-cdn-nginx] inserted location before line {last_brace+1}')
PYEOF
elif command -v awk >/dev/null 2>&1; then
  awk -v loc="$LOCATION_CONTENT" 'BEGIN{added=0} {if($0 ~ /^}$/ && !added){printf "%s", loc; added=1} print}' "$CDN" > "$CDN.tmp"
  mv "$CDN.tmp" "$CDN"
else
  echo '[fix-cdn-nginx] ERROR: no python3 and no awk, abort' >&2
  exit 1
fi

echo "[fix-cdn-nginx] === after ==="
sed -n '$-10,$p' "$CDN" || true
nginx -t
nginx -s reload
sleep 1
echo "[fix-cdn-nginx] self check"
curl -sk --resolve cdn.yshealth.com.cn:443:127.0.0.1 -o /dev/null -w "GET https://cdn.yshealth.com.cn/platform/health        -> %{http_code}\n" --max-time 5 https://cdn.yshealth.com.cn/platform/health
curl -sk --resolve cdn.yshealth.com.cn:443:127.0.0.1 -o /dev/null -w "GET https://cdn.yshealth.com.cn/billing/v1/wallet/demo -> %{http_code}\n" --max-time 5 https://cdn.yshealth.com.cn/billing/v1/wallet/demo
