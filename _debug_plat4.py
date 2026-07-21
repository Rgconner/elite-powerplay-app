import urllib.request, json, sys

def get_json(url):
    req = urllib.request.Request(url)
    return json.loads(urllib.request.urlopen(req, timeout=60).read())

sid = 594660018531

# Get the system record (wrapped in 'record' key)
resp = get_json(f"https://spansh.co.uk/api/system/{sid}")
rec = resp["record"]  # <-- THIS is the bug! Need to unwrap

print(f"Record keys: {list(rec.keys())}")
print(f"Body count: {rec.get('body_count')}")
print(f"Minor faction presences count: {len(rec.get('minor_faction_presences', []))}")
print(f"Factions present: {[f.get('name') for f in rec.get('minor_faction_presences', [])]}")

# Check factions for BOOM
factions = rec.get("minor_faction_presences", [])
has_boom = False
for f in factions:
    for s in f.get("active_states", []):
        name = s if isinstance(s, str) else s.get("name", "")
        if name.upper() == "BOOM":
            has_boom = True
print(f"Has BOOM: {has_boom}")

# Check bodies
bodies = rec.get("bodies", [])
print(f"\nBodies: {len(bodies)}")
for b in bodies[:15]:
    bt = b.get("type", "")
    print(f"  type='{bt}', name='{b.get('name')}', id64={b.get('id64')}")

# Check planets for platinum
print("\n=== Checking planets ===")
has_plat = False
for b in bodies:
    bt = (b.get("type") or "").lower()
    if "planet" not in bt:
        continue
    bid = b.get("id64")
    if not bid:
        continue
    
    body = get_json(f"https://spansh.co.uk/api/body/{bid}")
    print(f"\nBody '{b['name']}' id64={bid}")
    print(f"  keys: {list(body.keys())}")
    
    if "signals" in body:
        sigs = body["signals"]
        print(f"  signals: {json.dumps(sigs)[:500]}")
        if isinstance(sigs, list):
            for sg in sigs:
                items = sg.get("signals", []) if isinstance(sg, dict) else []
                for item in items:
                    name = item.get("name", "") if isinstance(item, dict) else str(item)
                    if "platinum" in name.lower():
                        print(f"  >>> FOUND PLATINUM!")
                        has_plat = True
    else:
        print(f"  No 'signals' key in body response")
        # Print first 500 chars to see what's there
        body_str = json.dumps(body)
        print(f"  Body data: {body_str[:300]}")
    
    # Check rings too
    rings = body.get("rings", [])
    for ring in rings:
        mat = ring.get("materials", {})
        for mname, mval in mat.items() if isinstance(mat, dict) else []:
            if "platinum" in mname.lower():
                print(f"  >>> FOUND PLATINUM in ring: {mname}={mval}")
                has_plat = True

print(f"\n=== FINAL ===")
print(f"has_plat={has_plat}, has_boom={has_boom}")