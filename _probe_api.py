import requests, json

# Probe the correct Spansh API endpoints for PP data
# Based on Spansh documentation and known working patterns

tests = [
    # Try the filtered systems search API (Spansh v2 uses this format)
    ("systems_filter_pp", "GET", "https://spansh.co.uk/api/systems/field_values/controlling_power"),
    ("systems_filter_ps", "GET", "https://spansh.co.uk/api/systems/field_values/power_state"),
    # Try a Sol lookup to see if PP fields appear in the full system response
    ("sol_full",          "GET", "https://spansh.co.uk/api/systems/id/10477373803"),
    ("sol_name",          "GET", "https://spansh.co.uk/api/systems?q=Sol&full=1"),
    # Spansh search with filter
    ("search_pp",         "POST", "https://spansh.co.uk/api/systems/search"),
]

for name, method, url in tests:
    try:
        if method == "GET":
            r = requests.get(url, timeout=15)
        else:
            r = requests.post(url, json={
                "filters": {"controlling_power": {"value": ["Aisling Duval"], "comparison": "="}},
                "size": 3,
                "page": 0,
                "sort": [{"controlling_power": {"direction": "asc"}}]
            }, timeout=15)
        print(f"{r.status_code:3}  {name:25}  {url}")
        body = r.text[:400]
        print(f"     {body}")
        print()
    except Exception as e:
        print(f"ERR  {name:25}  {e}")
        print()

# Also try the Spansh stations/systems API that the EDMC plugin uses
print("=== Trying EDMC-style system lookup for Sol ===")
r = requests.get("https://www.edsm.net/api-system-v1/powerPlay?systemName=Sol", timeout=15)
print(f"EDSM PP status={r.status_code}: {r.text[:300]}")
print()

# Try Spansh's new v2 API
r2 = requests.get("https://spansh.co.uk/api/v2/systems?controlling_power=Aisling+Duval&size=3", timeout=15)
print(f"Spansh v2 systems: {r2.status_code}: {r2.text[:300]}")
