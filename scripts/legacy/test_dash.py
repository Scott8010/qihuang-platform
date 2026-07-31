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
r = json.loads(urllib.request.urlopen(req).read())
print(json.dumps(r, indent=2, ensure_ascii=False)[:800])
