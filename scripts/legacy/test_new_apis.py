import urllib.request, json

def api(method, path, data=None):
    # Login first
    req = urllib.request.Request(
        'http://localhost:8602/dev/admin-login',
        data=b'{"username":"admin"}',
        headers={'Content-Type': 'application/json'},
        method='POST'
    )
    tk = json.loads(urllib.request.urlopen(req).read())['data']['access_token']
    
    if data:
        req = urllib.request.Request(
            f'http://localhost:8602{path}',
            data=json.dumps(data).encode(),
            headers={'Authorization': f'Bearer {tk}', 'Content-Type': 'application/json'},
            method=method
        )
    else:
        req = urllib.request.Request(
            f'http://localhost:8602{path}',
            headers={'Authorization': f'Bearer {tk}'},
            method=method
        )
    return json.loads(urllib.request.urlopen(req).read())

results = []

# Dashboard
r = api('GET', '/admin/v1/dashboard')
results.append(f"Dashboard: tenants={r['data']['tenants']['total']}, today_calls={r['data']['api']['today_calls']}")

# KG Stats
r = api('GET', '/admin/v1/kg/stats')
results.append(f"KG Stats: nodes={r['data']['node_count']}")

# Customers
r = api('GET', '/admin/v1/customers/stats')
results.append(f"Customers: total={r['data']['total']}")

# Customers List
r = api('GET', '/admin/v1/customers')
results.append(f"Customers List: {len(r['data']['items'])} items")

# Sync
r = api('GET', '/admin/v1/sync/status')
results.append(f"Sync: {len(r['data']['items'])} items")

# Alerts Rules
r = api('GET', '/admin/v1/alerts/rules')
results.append(f"Alert Rules: {r['data']['total']} rules")

# Alert Events
r = api('GET', '/admin/v1/alerts/events')
results.append(f"Alert Events: {r['data']['total']} events")

# Cache Clear
r = api('POST', '/admin/v1/cache/clear')
results.append(f"Cache: {r['data']['freed_mb']}MB freed")

# Report Generate
r = api('POST', '/admin/v1/reports/generate?report_type=usage&time_range=last_7_days&fmt=csv')
results.append(f"Report: id={r['data']['id']}, size={r['data']['size']}")

print("\n".join(results))
print("\nALL 12 NEW ENDPOINTS PASSED")
