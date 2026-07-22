import requests, json, sys

# Step 1: Find HIP 36583 system_id64
r = requests.post('https://spansh.co.uk/api/systems/search', json={
    'filters': {'name': {'value': ['HIP 36583'], 'comparison': '='}},
    'size': 1, 'page': 0
}, timeout=30)
data = r.json()
results = data.get('results', [])
if not results:
    print("System not found")
    sys.exit(1)

sys_item = results[0]
print('=== SYSTEM ===')
print('id64:', sys_item.get('id64'))
print('name:', sys_item.get('name'))
print()

# Step 2: Get full system data via /api/system/<id>
sid = sys_item['id64']
r2 = requests.get(f'https://spansh.co.uk/api/system/{sid}', timeout=30)
sys_full = r2.json()

# Check minor_faction_presences
print('=== minor_faction_presences (first 5) ===')
factions = sys_full.get('minor_faction_presences', [])
print(f'Total factions: {len(factions)}')
for f in factions[:5]:
    states = f.get('active_states', [])
    print(f'  {f.get("name")}: active_states={states}')

# Check for BOOM
has_boom = False
for f in factions:
    for s in f.get('active_states', []):
        if isinstance(s, str) and s.upper() == 'BOOM':
            has_boom = True
        if isinstance(s, dict) and s.get('name', '').upper() == 'BOOM':
            has_boom = True
print(f'\nHas BOOM: {has_boom}')

# Check bodies
bodies = sys_full.get('bodies', [])
print(f'\n=== Bodies: {len(bodies)} total ===')
for b in bodies:
    print(f'  type={b.get("type")}, name={b.get("name")}, id64={b.get("id64")}')

# Step 3: Check all planet bodies for platinum
print('\n=== Checking planet bodies for platinum ===')
has_plat = False
for b in bodies:
    bt = (b.get('type') or '').lower()
    if 'planet' not in bt:
        continue
    bid = b.get('id64')
    if not bid:
        continue
    
    r3 = requests.get(f'https://spansh.co.uk/api/body/{bid}', timeout=30)
    body_data = r3.json()
    
    # Print all top keys
    print(f'\nBody "{b["name"]}" (id64={bid}) type={b.get("type")}')
    print(f'  Top keys: {list(body_data.keys())[:10]}')
    
    # Check signals in various possible locations
    signals = body_data.get('signals', [])
    print(f'  signals key top-level: type={type(signals).__name__}, len={len(signals) if isinstance(signals, list) else "N/A"}')
    
    if isinstance(signals, list):
        for sg in signals:
            print(f'  signal group: {json.dumps(sg, indent=4)[:300]}')
            sig_type = sg.get('type', 'unknown')
            items = sg.get('signals', [])
            for item in items:
                name = item.get('name', '') if isinstance(item, dict) else str(item)
                if 'platinum' in name.lower():
                    print(f'    >>> FOUND PLATINUM!')
                    has_plat = True
    else:
        # Maybe signals is a dict or signals are elsewhere
        # Check for 'materials' or 'composition'
        mats = body_data.get('materials', [])
        print(f'  materials: {json.dumps(mats)[:200]}')
        composition = body_data.get('composition', {})
        print(f'  composition: {json.dumps(composition)[:200]}')
        rings = body_data.get('rings', [])
        print(f'  rings: {len(rings)}')

print(f'\n=== FINAL RESULT ===')
print(f'has_platinum: {has_plat}')
print(f'has_boom: {has_boom}')