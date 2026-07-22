import requests, json

# Understand the control_progress field as a threshold indicator
# Key observations so far:
#   - control_progress can be > 1.0 (e.g. 3.715 for Facece Stronghold)
#   - Fortified systems with progress > 1.0 seem "over-reinforced" 
#   - progress = 1.0 seems to be a state transition threshold
#   - Negative progress exists (Evena: -0.0167, Na Zha: -0.0050)
#
# Hypothesis: control_progress is a normalized net score where:
#   >= 1.0 means ready/past the next level up (reinforcement threshold met)
#   <= 0.0 means at risk of dropping to next level down
#   The "days to failure" is derivable from current rate of change
#
# Let's find systems near 0.0 and 1.0 to confirm thresholds

print("=== Exploited systems near progress=0 (at risk of losing system) ===")
r = requests.post("https://spansh.co.uk/api/systems/search", json={
    "filters": {
        "power_state": {"value": ["Exploited"], "comparison": "="},
        "power_state_control_progress": {"min": -0.1, "max": 0.05}
    },
    "size": 15, "page": 0,
    "sort": [{"power_state_control_progress": {"direction": "asc"}}],
}, timeout=30)
for s in r.json().get("results", []):
    rv = s.get("power_state_reinforcement", 0) or 0
    uv = s.get("power_state_undermining", 0) or 0
    pv = s.get("power_state_control_progress", 0) or 0
    net = rv - uv
    print(f"  {s['name'][:30]:<30} R={rv:>8,} U={uv:>8,} net={net:>+9,} progress={pv:+.4f}")

print()
print("=== Fortified systems near progress=0 (at risk of dropping to Exploited) ===")
r2 = requests.post("https://spansh.co.uk/api/systems/search", json={
    "filters": {
        "power_state": {"value": ["Fortified"], "comparison": "="},
        "power_state_control_progress": {"min": -0.1, "max": 0.1}
    },
    "size": 15, "page": 0,
    "sort": [{"power_state_control_progress": {"direction": "asc"}}],
}, timeout=30)
for s in r2.json().get("results", []):
    rv = s.get("power_state_reinforcement", 0) or 0
    uv = s.get("power_state_undermining", 0) or 0
    pv = s.get("power_state_control_progress", 0) or 0
    net = rv - uv
    print(f"  {s['name'][:30]:<30} R={rv:>8,} U={uv:>8,} net={net:>+9,} progress={pv:+.4f}")

print()
print("=== Stronghold systems near progress=0 (at risk of dropping to Fortified) ===")
r3 = requests.post("https://spansh.co.uk/api/systems/search", json={
    "filters": {
        "power_state": {"value": ["Stronghold"], "comparison": "="},
        "power_state_control_progress": {"min": -0.2, "max": 0.15}
    },
    "size": 15, "page": 0,
    "sort": [{"power_state_control_progress": {"direction": "asc"}}],
}, timeout=30)
for s in r3.json().get("results", []):
    rv = s.get("power_state_reinforcement", 0) or 0
    uv = s.get("power_state_undermining", 0) or 0
    pv = s.get("power_state_control_progress", 0) or 0
    net = rv - uv
    print(f"  {s['name'][:30]:<30} R={rv:>8,} U={uv:>8,} net={net:>+9,} progress={pv:+.4f}")

print()
print("=== Exploited near progress=1.0 (close to becoming Fortified) ===")
r4 = requests.post("https://spansh.co.uk/api/systems/search", json={
    "filters": {
        "power_state": {"value": ["Exploited"], "comparison": "="},
        "power_state_control_progress": {"min": 0.85, "max": 1.1}
    },
    "size": 15, "page": 0,
    "sort": [{"power_state_control_progress": {"direction": "desc"}}],
}, timeout=30)
d4 = r4.json()
print(f"  Count near 1.0: {d4.get('count',0)}")
for s in d4.get("results", []):
    rv = s.get("power_state_reinforcement", 0) or 0
    uv = s.get("power_state_undermining", 0) or 0
    pv = s.get("power_state_control_progress", 0) or 0
    net = rv - uv
    print(f"  {s['name'][:30]:<30} R={rv:>8,} U={uv:>8,} net={net:>+9,} progress={pv:+.4f}")

print()
print("=== Fortified near progress=1.0 (close to becoming Stronghold) ===")
r5 = requests.post("https://spansh.co.uk/api/systems/search", json={
    "filters": {
        "power_state": {"value": ["Fortified"], "comparison": "="},
        "power_state_control_progress": {"min": 0.85, "max": 1.5}
    },
    "size": 15, "page": 0,
    "sort": [{"power_state_control_progress": {"direction": "desc"}}],
}, timeout=30)
d5 = r5.json()
print(f"  Count near/above 1.0: {d5.get('count',0)}")
for s in d5.get("results", []):
    rv = s.get("power_state_reinforcement", 0) or 0
    uv = s.get("power_state_undermining", 0) or 0
    pv = s.get("power_state_control_progress", 0) or 0
    net = rv - uv
    print(f"  {s['name'][:30]:<30} R={rv:>8,} U={uv:>8,} net={net:>+9,} progress={pv:+.4f}")

print("\nDone.")
