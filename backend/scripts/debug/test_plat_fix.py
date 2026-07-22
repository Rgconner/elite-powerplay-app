"""Quick test: verify the fixed _check_body_for_platinum logic against live API."""
import urllib.request, json

def check_platinum(body):
    """The FIXED logic: check rings[].signals[]"""
    rings = body.get("rings") or []
    for ring in rings:
        ring_signals = ring.get("signals") or []
        for sig in ring_signals:
            if isinstance(sig, dict) and sig.get("name", "").lower() == "platinum":
                return True
    return False

def old_check_platinum(body):
    """The OLD broken logic: check body.signals and ring.materials"""
    try:
        signals = body.get("signals") or []
        for sig_group in signals:
            items = sig_group.get("signals") or []
            for item in items:
                if isinstance(item, dict) and item.get("name", "").lower() == "platinum":
                    return True
        rings = body.get("rings") or []
        for ring in rings:
            mat = ring.get("materials", {})
            if isinstance(mat, dict):
                for mname in mat:
                    if "platinum" in mname.lower():
                        return True
            elif isinstance(mat, list):
                for m in mat:
                    mname = m.get("name", "") if isinstance(m, dict) else str(m)
                    if "platinum" in mname.lower():
                        return True
    except:
        pass
    return False

# Fetch the known-platinum body
url = "https://spansh.co.uk/api/body/1116893302247901539"
req = urllib.request.Request(url)
raw = json.loads(urllib.request.urlopen(req, timeout=30).read())
body = raw.get("record", raw)

name = body.get("name", "?")
rings = body.get("rings", [])

print(f"Body: {name}")
print(f"Rings: {len(rings)}")
for ring in rings:
    sigs = ring.get("signals", [])
    plat = [s for s in sigs if s.get("name", "").lower() == "platinum"]
    print(f"  {ring.get('name')} ({ring.get('type')}): {len(sigs)} signals, platinum={len(plat) > 0}")
    for s in sigs:
        print(f"    {s.get('name')}: count={s.get('count')}")

print()
print(f"OLD logic (broken): {old_check_platinum(body)}")
print(f"NEW logic (fixed):  {check_platinum(body)}")