import urllib.request, json, sys

def post_json(url, data):
    req = urllib.request.Request(
        url, data=json.dumps(data).encode(), 
        headers={"Content-Type": "application/json"}
    )
    return json.loads(urllib.request.urlopen(req, timeout=30).read())

def get_json(url):
    req = urllib.request.Request(url)
    return json.loads(urllib.request.urlopen(req, timeout=30).read())

# Step 1: Find HIP 36583
print("=== Searching for HIP 36583 ===")
data = post_json("https://spansh.co.uk/api/systems/search", {
    "filters": {"name": {"value": ["HIP 36583"], "comparison": "="}},
    "size": 1, "page": 0
})
results = data.get("results", [])
if not results:
    print("System not found")
    sys.exit(1)

sys_item = results[0]
sid = sys_item["id64"]
print(f"id64={sid}, name={sys_item.get('name')}")

# Step 2: Get full system data
print(f"\n=== Fetching system {sid} ===")
sys_full = get_json(f"https://spansh.co.uk/api/system/{sid}")

# Check minor_faction_presences
factions = sys_full.get("minor_faction_presences", [])
print(f"Factions: {len(factions)}")
has_boom = False
for f in factions:
    for s in f.get("active_states", []):
        name = s if isinstance(s, str) else s.get("name", "")
        if name.upper() == "BOOM":
            has_boom = True
print(f"Has BOOM: {has_boom}")

# Check bodies
bodies = sys_full.get("bodies", [])
print(f"\nBodies: {len(bodies)}")
for b in bodies[:10]:
    print(f"  type='{b.get('type')}', name='{b.get('name')}', id64={b.get('id64')}")

# Step 3: Check planet bodies for platinum
print("\n=== Checking planets for platinum ===")
has_plat = False
for b in bodies:
    bt = (b.get("type") or "").lower()
    if "planet" not in bt:
        continue
    bid = b.get("id64")
    if not bid:
        continue
    
    body = get_json(f"https://spansh.co.uk/api/body/{bid}")
    print(f"\nBody '{b['name']}' type={b.get('type')}")
    print(f"  Top keys: {list(body.keys())}")
    
    signals = body.get("signals")
    print(f"  signals type={type(signals).__name__}, value={json.dumps(signals)[:500] if signals else 'None/null'}")
    
    if isinstance(signals, list):
        for sg in signals:
            items = sg.get("signals", []) if isinstance(sg, dict) else []
            for item in items:
                name = item.get("name", "") if isinstance(item, dict) else str(item)
                if "platinum" in name.lower():
                    print(f"  >>> FOUND PLATINUM in signal item: {item}")
                    has_plat = True
    
    # Also check rings for platinum
    rings = body.get("rings", [])
    for ring in rings:
        mat = ring.get("materials", {})
        if isinstance(mat, dict):
            for mname, mval in mat.items():
                if "platinum" in mname.lower():
                    print(f"  >>> FOUND PLATINUM in ring materials: {mname}={mval}")
                    has_plat = True
        elif isinstance(mat, list):
            for m in mat:
                mname = m.get("name", "") if isinstance(m, dict) else str(m)
                if "platinum" in mname.lower():
                    print(f"  >>> FOUND PLATINUM in ring materials list: {m}")
                    has_plat = True

print(f"\n=== FINAL ===")
print(f"has_platinum={has_plat}")
print(f"has_boom={has_boom}")