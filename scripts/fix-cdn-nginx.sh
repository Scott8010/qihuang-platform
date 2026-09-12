#!/usr/bin/env bash
# Production nginx repair (run via CI on push with 'nginx-fix-cdn' in commit msg).
# Phase 1: remove DUPLICATE default_server across /etc/nginx/conf.d/*.conf
#          (a dup default_server makes `nginx -t` fail -> reload never runs -> stale config).
# Phase 2: fix cdn.yshealth.com.cn.conf (drop orphaned location block outside the
#          server block, ensure a valid `location / { proxy_pass 127.0.0.1:8602; }`).
# Safe to re-run (idempotent).
set -e

# ---------- Phase 1: dedupe default_server (use os.listdir, not glob, for portability) ----------
if command -v python3 >/dev/null 2>&1; then
python3 - <<'PYEOF'
import re, os
conf_dir = '/etc/nginx/conf.d'
confs = []
if os.path.isdir(conf_dir):
    confs = [os.path.join(conf_dir, f) for f in os.listdir(conf_dir) if f.endswith('.conf')]
seen = {}
changed = []
for f in sorted(confs):
    try:
        lines = open(f, encoding='utf-8').read().splitlines(keepends=True)
    except OSError:
        continue
    out = []
    file_changed = False
    for ln in lines:
        m = re.search(r'listen\s+.*?(\d+)([^;]*default_server[^;]*);', ln)
        if m:
            port = m.group(1)
            rest = m.group(2)
            ssl = 'ssl' in rest
            key = (port, ssl)
            if seen.get(key):
                new_rest = re.sub(r'\s*default_server', '', rest, count=1)
                new_rest = re.sub(r'\s+', ' ', new_rest).strip()
                ln = ('    listen %s %s;\n' % (port, new_rest)) if new_rest else ('    listen %s;\n' % port)
                file_changed = True
                changed.append('%s :%s%s' % (f, port, ' ssl' if ssl else ''))
            else:
                seen[key] = True
        out.append(ln)
    if file_changed:
        open(f, 'w', encoding='utf-8').write(''.join(out))
if changed:
    print('[fix-nginx] stripped duplicate default_server on: ' + ', '.join(changed))
else:
    print('[fix-nginx] no duplicate default_server found')
PYEOF
else
  echo '[fix-nginx] WARNING: python3 missing, skipping default_server dedupe' >&2
fi

# ---------- Phase 2: fix cdn.yshealth.com.cn.conf ----------
CDN=${1:-/etc/nginx/conf.d/cdn.yshealth.com.cn.conf}
if [ ! -f "$CDN" ]; then
  echo "[fix-cdn-nginx] $CDN not found, nothing to do"
  exit 0
fi

BACKUP="${CDN}.bak.$(date +%Y%m%d_%H%M%S)"
cp -p "$CDN" "$BACKUP"
echo "[fix-cdn-nginx] backup -> $BACKUP"

LOCATION_CONTENT='    # nginx-fix-cdn: forward unmatched paths to 8602 (fix for SNI=cdn.yshealth.com.cn 404)
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
lines = src.splitlines(keepends=True)

# 1) locate the top-level server block (first "server {" -> matching "}")
start = None
depth = 0
end = None
for i, ln in enumerate(lines):
    s = ln.strip()
    if start is None and s.startswith('server') and '{' in s:
        start = i
        depth = s.count('{') - s.count('}')  # count the "server {" brace itself
        continue
    if start is not None:
        depth += s.count('{') - s.count('}')
        if depth <= 0:
            end = i
            break
if start is None:
    print('[fix-cdn-nginx] ERROR: no server block found', file=sys.stderr)
    sys.exit(1)

# server_lines = lines[start:end+1]; everything AFTER end is orphaned junk -> discard
server_lines = lines[start:end+1]

# 2) already have valid proxy inside server block?
joined = ''.join(server_lines)
if 'proxy_pass http://127.0.0.1:8602;' in joined:
    print('[fix-cdn-nginx] 8602 proxy already present inside server block; keeping (orphaned junk dropped).')
    open(path, 'w', encoding='utf-8').write(''.join(server_lines))
    sys.exit(0)

# 3) replace ONLY the catch-all "location /" (NOT "location /3d/" etc.) with proxy block
CATCHALL = re.compile(r'location\s+/\s*\{')
new_server = []
i = 0
n = len(server_lines)
replaced = False
while i < n:
    s = server_lines[i].strip()
    if CATCHALL.match(s):
        j = i
        block = []
        d = 0
        while j < n:
            t = server_lines[j].strip()
            block.append(server_lines[j])
            d += t.count('{') - t.count('}')
            j += 1
            if d <= 0:
                break
        blk = ''.join(block)
        if ('return 404' in blk) or ('proxy_pass' not in blk):
            new_server.append(loc)
            replaced = True
            i = j
            continue
        else:
            new_server.extend(block)
            i = j
            continue
    new_server.append(server_lines[i])
    i += 1

if not replaced:
    braces = [k for k, ln in enumerate(new_server) if ln.strip() == '}']
    last = braces[-1]
    new_server = new_server[:last] + [loc] + new_server[last:]

open(path, 'w', encoding='utf-8').write(''.join(new_server))
print('[fix-cdn-nginx] rewrote server block: dropped orphaned junk, ensured 8602 proxy')
PYEOF
else
  echo '[fix-cdn-nginx] ERROR: python3 missing, abort' >&2
  exit 1
fi

echo "[fix-cdn-nginx] === resulting cdn.conf ==="
cat -n "$CDN"
nginx -t
nginx -s reload
sleep 1
echo "[fix-cdn-nginx] self check (cdn SNI)"
curl -sk --resolve cdn.yshealth.com.cn:443:127.0.0.1 -o /dev/null -w "GET https://cdn.yshealth.com.cn/platform/health        -> %{http_code}\n" --max-time 5 https://cdn.yshealth.com.cn/platform/health
curl -sk --resolve cdn.yshealth.com.cn:443:127.0.0.1 -o /dev/null -w "GET https://cdn.yshealth.com.cn/billing/v1/wallet/demo -> %{http_code}\n" --max-time 5 https://cdn.yshealth.com.cn/billing/v1/wallet/demo
echo "[fix-cdn-nginx] self check (boss IP URL)"
curl -sk -o /dev/null -w "GET https://111.231.63.73/platform/health        -> %{http_code}\n" --max-time 5 https://111.231.63.73/platform/health
curl -sk -o /dev/null -w "GET https://111.231.63.73/billing/v1/wallet/demo -> %{http_code}\n" --max-time 5 https://111.231.63.73/billing/v1/wallet/demo
