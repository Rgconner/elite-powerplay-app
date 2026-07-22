import requests, json

# Get a full sample system record from the Spansh search API to see all fields
r = requests.post("https://spansh.co.uk/api/systems/search", json={
    "filters": {
        "controlling_power": {"value": ["Aisling Duval"], "comparison": "="}
    },
    "size": 3,
    "page": 0,
    "sort": [{"name": {"direction": "asc"}}]
}, timeout=30)

data = r.json()
print(f"Total count: {data.get('count')}")
print(f"Number of results: {len(data.get('results', []))}")
print()

if data.get("results"):
    sys1 = data["results"][0]
    print("=== FIRST RESULT KEYS ===")
    print(json.dumps({k: v for k, v in sys1.items() if k != "bodies" and k != "stations" and k != "factions"}, indent=2))
    print()
    print("All top-level keys:", sorted(sys1.keys()))
    print()
    # Focus on PP fields
    pp_keys = [k for k in sys1 if "power" in k.lower() or "control" in k.lower() or k in ("allegiance","security","population")]
    print("PP-related keys:", pp_keys)
    for k in pp_keys:
        print(f"  {k}: {repr(sys1.get(k))}")

print()
print("=== power_state field values available ===")
r2 = requests.get("https://spansh.co.uk/api/systems/field_values/power_state", timeout=10)
print(r2.json())
