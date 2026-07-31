import sys, json, urllib.request

req = urllib.request.urlopen("http://localhost:8602/platform/openapi.json")
d = json.loads(req.read())
paths = list(d.get("paths", {}).keys())
print(f"Total routes: {len(paths)}")
print()
groups = {}
for p in paths:
    parts = p.split("/")
    prefix = "/".join(parts[:3]) if len(parts) >= 3 else p
    groups.setdefault(prefix, []).append(p)
for prefix in sorted(groups):
    print(f"  {prefix} ({len(groups[prefix])} routes)")
