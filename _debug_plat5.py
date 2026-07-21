import urllib.request, json, sys

def get_json(url):
    req = urllib.request.Request(url)
    return json.loads(urllib.request.urlopen(req, timeout=60).read())

sid = 594660018531

# Use the bodies search API which gives us full body data
sys_search = json.loads(urllib.request.urlopen(
    urllib.request.Request("https://spansh.co.uk/api/bodies/search",
        data=json.dumps({
            "filters": {"system_name": {"value": ["HIP 36583"], "comparison": "="}},
            "size": 50
        }).encode(),
        headers={"Content-Type": "application/json"}
    ), timeout=30).read())
results = sys_search.get("results", [])
print(f"Bodies search returned {len(results)} results")

for r in results:
    # Bodies search returns flat data with no 'record' wrapper
    bt = (r.get("type") or "").lower()
    name = r.get("name", "?")
    
    # Check for rings
    rings = r.get("rings", [])
    has_plat_ring = False
    if rings:
        for ring in rings:
            mat = ring.get("materials", {})
            if isinstance(mat, dict):
                for mname, mval in mat.items():
                    if "platinum" in mname.lower():
                        has_plat_ring = True
                        print(f"  >>> PLATINUM in ring of {name}: {mname}={mval}")
            elif isinstance(mat, list):
                for m in mat:
                    mname = m.get("name", "") if isinstance(m, dict) else str(m)
                    if "platinum" in mname.lower():
                        has_plat_ring = True
                        print(f"  >>> PLATINUM in ring of {name}: {m}")
    
    # Check for materials/composition
    composition = r.get("composition", {})
    if isinstance(composition, dict):
        mat = composition.get("materials", {})
        if isinstance(mat, dict):
            for mname, mval in mat.items():
                if "platinum" in mname.lower():
                    print(f"  >>> PLATINUM in composition of {name}: {mname}={mval}")
    
    # Check signals
    signals = r.get("signals", [])
    if signals:
        for sg in signals:
            items = sg.get("signals", []) if isinstance(sg, dict) else []
            for item in items:
                item_name = item.get("name", "") if isinstance(item, dict) else str(item)
                if "platinum" in item_name.lower():
                    print(f"  >>> PLATINUM in signals of {name}: {item}")

    # Print bodies with rings for debugging
    if rings and bt == "planet":
        print(f"Body '{name}' type={r.get('type')} landable={r.get('is_landable')} has {len(rings)} rings")
        for ring in rings:
            ring_name = ring.get("name", "?")
            ring_type = ring.get("type", "?")
            mats = ring.get("materials", {})
            print(f"  Ring: {ring_name} type={ring_type} materials={json.dumps(mats)[:200]}")

# Also check the full body API for a specific body
# Let's look at body "HIP 36583 2 a" which might have rings
print("\n=== Checking body API with record unwrapping ===")
body_id = 1224979693304793443  # HIP 36583 2 a
body_raw = get_json(f"https://spansh.co.uk/api/body/{body_id}")
rec = body_raw.get("record", body_raw)  # Unwrap record
print(f"Keys in record: {list(rec.keys())}")
print(f"Has rings: {'rings' in rec}")
rings = rec.get("rings", [])
if rings:
    for ring in rings:
        print(f"  Ring: {json.dumps(ring)[:300]}")
        mat = ring.get("materials", {})
        for mname, mval in mat.items() if isinstance(mat, dict) else []:
            if "platinum" in mname.lower():
                print(f"  >>> FOUND PLATINUM in ring: {mname}={mval}")