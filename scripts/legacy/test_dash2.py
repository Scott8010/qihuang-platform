import urllib.request, json

req = urllib.request.Request(
    'http://localhost:8602/dev/admin-login',
    data=b'{"username":"admin"}',
    headers={'Content-Type': 'application/json'},
    method='POST'
)
tk = json.loads(urllib.request.urlopen(req).read())['data']['access_token']

req = urllib.request.Request(
    'http://localhost:8602/admin/v1/dashboard',
    headers={'Authorization': 'Bearer ' + tk}
)
r = json.loads(urllib.request.urlopen(req).read())['data']

# Check for new fields
checks = {
    'tenants.new_this_month': 'new_this_month' in r.get('tenants', {}),
    'api.today_calls': 'today_calls' in r.get('api', {}),
    'api.call_diff': 'call_diff' in r.get('api', {}),
    'kg.pending': 'pending' in r.get('kg', {}),
    'recent_ops': 'recent_ops' in r,
    'trend': 'trend' in r,
    'services': 'services' in r,
}

for k, v in checks.items():
    status = 'OK' if v else 'MISSING'
    print(f"  {k}: {status}")

missing = [k for k, v in checks.items() if not v]
if missing:
    print(f"\nMissing fields: {', '.join(missing)}")
else:
    print("\nAll new dashboard fields present!")
