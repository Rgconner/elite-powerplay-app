import requests, json

# Deep-dive into PP 2.0 mechanics via the Spansh API
# Goal: understand what the reinforcement/undermining numbers mean
# in terms of state transitions and thresholds

# Get a sample of systems in each state to understand the data ranges
states = ["Exploited", "Fortified", "Stronghold", "Unoccupied"]

for state in states:
    r = requests.post("https://spansh.co.uk/api/systems/search", json={
        "filters": {
            "power_state": {"value": [state], "comparison": "="}
        },
        "size": 5,
        "page": 0,
        "sort": [{"power_state_undermining": {"direction": "desc"}}],
    }, timeout=30)
    data = r.json()
    print(f"\n=== {state} (total: {data.get('count',0)}) — top 5 by undermining ===")
    for s in data.get("results", []):
        r_val = s.get("power_state_reinforcement", 0) or 0
        u_val = s.get("power_state_undermining", 0) or 0
        p_val = s.get("power_state_control_progress", 0) or 0
        net = r_val - u_val
        print(f"  {s['name'][:35]:<35} power={s.get('controlling_power','?')[:20]:<20} "
              f"R={r_val:>8,}  U={u_val:>8,}  net={net:>+9,}  progress={p_val:.4f}")

# Also get top 5 by REINFORCEMENT to see the spread
print("\n\n=== Top Fortified systems by reinforcement ===")
r2 = requests.post("https://spansh.co.uk/api/systems/search", json={
    "filters": {
        "power_state": {"value": ["Fortified"], "comparison": "="}
    },
    "size": 10,
    "page": 0,
    "sort": [{"power_state_reinforcement": {"direction": "desc"}}],
}, timeout=30)
for s in r2.json().get("results", []):
    r_val = s.get("power_state_reinforcement", 0) or 0
    u_val = s.get("power_state_undermining", 0) or 0
    p_val = s.get("power_state_control_progress", 0) or 0
    print(f"  {s['name'][:35]:<35} R={r_val:>8,}  U={u_val:>8,}  progress={p_val:.6f}")

print("\n\n=== Top Stronghold systems ===")
r3 = requests.post("https://spansh.co.uk/api/systems/search", json={
    "filters": {
        "power_state": {"value": ["Stronghold"], "comparison": "="}
    },
    "size": 10,
    "page": 0,
    "sort": [{"power_state_reinforcement": {"direction": "desc"}}],
}, timeout=30)
for s in r3.json().get("results", []):
    r_val = s.get("power_state_reinforcement", 0) or 0
    u_val = s.get("power_state_undermining", 0) or 0
    p_val = s.get("power_state_control_progress", 0) or 0
    print(f"  {s['name'][:35]:<35} R={r_val:>8,}  U={u_val:>8,}  progress={p_val:.6f}")

print("\n\n=== Exploited systems with high undermining ===")
r4 = requests.post("https://spansh.co.uk/api/systems/search", json={
    "filters": {
        "power_state": {"value": ["Exploited"], "comparison": "="}
    },
    "size": 10,
    "page": 0,
    "sort": [{"power_state_undermining": {"direction": "desc"}}],
}, timeout=30)
for s in r4.json().get("results", []):
    r_val = s.get("power_state_reinforcement", 0) or 0
    u_val = s.get("power_state_undermining", 0) or 0
    p_val = s.get("power_state_control_progress", 0) or 0
    net = r_val - u_val
    print(f"  {s['name'][:35]:<35} R={r_val:>8,}  U={u_val:>8,}  net={net:>+9,}  progress={p_val:.6f}")

print("\n\nDone.")
