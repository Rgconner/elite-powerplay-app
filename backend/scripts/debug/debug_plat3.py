import urllib.request, json, sys

def get_json(url):
    req = urllib.request.Request(url)
    return json.loads(urllib.request.urlopen(req, timeout=60).read())

sid = 594660018531
print(f"=== Fetching system {sid} full response ===")
sys_full = get_json(f"https://spansh.co.uk/api/system/{sid}")

print(f"Top-level keys: {list(sys_full.keys())}")
print(f"Number of keys: {len(sys_full)}")
print()

# Flatten and look at everything
for k, v in sys_full.items():
    if isinstance(v, list):
        print(f"  {k}: list of {len(v)} items")
        if v and len(v) > 0:
            print(f"    first item: {json.dumps(v[0], indent=2)[:200]}")
            print(f"    first item type: {type(v[0]).__name__}")
    elif isinstance(v, dict):
        print(f"  {k}: dict with {len(v)} keys {list(v.keys())[:5]}")
    else:
        print(f"  {k}: {type(v).__name__} = {str(v)[:100]}")

# Also check if there's a different endpoint for bodies
print("\n=== Searching Spansh bodies for HIP 36583 ===")
sys_search = json.loads(urllib.request.urlopen(
    urllib.request.Request("https://spansh.co.uk/api/systems/search",
        data=json.dumps({"filters": {"name": {"value": ["HIP 36583"], "comparison": "="}}, "size": 1}).encode(),
        headers={"Content-Type": "application/json"}
    ), timeout=30).read())
sys_item = sys_search.get("results", [{}])[0]
print(f"Search result keys: {list(sys_item.keys())}")
print(f"Has 'bodies' key: {'bodies' in sys_item}")

# Try searching bodies directly
print("\n=== Searching for bodies in HIP 36583 ===")
try:
    body_search = json.loads(urllib.request.urlopen(
        urllib.request.Request("https://spansh.co.uk/api/bodies/search",
            data=json.dumps({"filters": {"system_name": {"value": ["HIP 36583"], "comparison": "="}}, "size": 10}).encode(),
            headers={"Content-Type": "application/json"}
        ), timeout=30).read())
    body_results = body_search.get("results", [])
    print(f"Body search results: {len(body_results)}")
    for br in body_results[:5]:
        print(f"  {json.dumps(br, indent=2)[:200]}")
except Exception as e:
    print(f"Body search failed: {e}")