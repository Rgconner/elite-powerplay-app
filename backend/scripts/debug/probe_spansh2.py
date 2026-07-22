#!/usr/bin/env python3
"""Advanced Spansh probe: scan systems_populated.json.gz for PP fields,
AND test all known alternative Spansh PP download URLs.

Run from backend/ with venv active:
    python probe_spansh2.py
"""
import gzip
import io
import json
import sys

import requests

# ── 1. Test all candidate URLs ─────────────────────────────────────────────

CANDIDATE_URLS = [
    "https://downloads.spansh.co.uk/systems_populated.json.gz",
    "https://downloads.spansh.co.uk/powerplay.json.gz",
    "https://downloads.spansh.co.uk/galaxy_powerplay.json.gz",
    "https://downloads.spansh.co.uk/galaxy_1_week.json.gz",
    "https://downloads.spansh.co.uk/galaxy.json.gz",
    "https://spansh.co.uk/api/download/powerplay",
    "https://downloads.spansh.co.uk/factions.json.gz",
    "https://downloads.spansh.co.uk/bodies.json.gz",
]

print("=" * 70)
print("STEP 1: Checking all candidate Spansh URLs (HEAD requests)")
print("=" * 70)
for url in CANDIDATE_URLS:
    try:
        r = requests.head(url, timeout=15, allow_redirects=True)
        size = r.headers.get("Content-Length", "unknown")
        ct   = r.headers.get("Content-Type", "n/a")
        mark = "✓" if r.status_code == 200 else "✗"
        print(f"  {mark} {r.status_code}  {str(size):>12s} bytes  {ct:<30s}  {url}")
    except Exception as exc:
        print(f"  ✗ ERR  {'':>12s}       {'n/a':<30s}  {url}  ({exc})")

print()

# ── 2. Scan systems_populated.json.gz for PP fields ────────────────────────

SYS_URL = "https://downloads.spansh.co.uk/systems_populated.json.gz"

print("=" * 70)
print(f"STEP 2: Scanning {SYS_URL}")
print("=" * 70)

import ijson

try:
    print("Downloading (may take a minute for large file)...")
    resp = requests.get(SYS_URL, stream=True, timeout=300)
    resp.raise_for_status()
    chunks = []
    for chunk in resp.iter_content(1024 * 1024):
        chunks.append(chunk)
    compressed = b"".join(chunks)
    print(f"Downloaded: {len(compressed):,} bytes compressed")
except Exception as exc:
    print(f"ERROR downloading: {exc}")
    sys.exit(1)

try:
    data = gzip.decompress(compressed)
    print(f"Decompressed: {len(data):,} bytes ({len(data)/1_048_576:.1f} MB)")
except Exception as exc:
    print(f"ERROR decompressing: {exc}")
    sys.exit(1)

PP_FIELDS = [
    "controlling_power", "power", "power_state",
    "power_state_reinforcement", "power_state_undermining",
    "power_state_control_progress",
]

buf = io.BytesIO(data)
total = 0
pp_count = 0
first_pp_obj = None
all_keys_seen: set = set()

print("Scanning all systems for PP fields...")
for obj in ijson.items(buf, "item"):
    total += 1
    all_keys_seen.update(obj.keys() if isinstance(obj, dict) else [])
    if isinstance(obj, dict) and any(f in obj for f in PP_FIELDS):
        pp_count += 1
        if first_pp_obj is None:
            first_pp_obj = obj
        if pp_count <= 3:
            print(f"\n  PP system #{pp_count} (overall #{total}): {obj.get('name','?')}")
            for k, v in obj.items():
                val = repr(v) if not isinstance(v, (list, dict)) else (
                    f"list({len(v)} items, first={repr(v[0]) if v else ''})" if isinstance(v, list)
                    else f"dict(keys={list(v.keys())})"
                )
                print(f"    {k:<45} {val[:80]}")
    if total % 10_000 == 0:
        print(f"  ... scanned {total:,} systems, {pp_count} PP systems found so far")

print(f"\nFINAL: {total:,} total systems, {pp_count} with PP fields")
print(f"All keys seen across all objects: {sorted(all_keys_seen)}")

if pp_count == 0:
    print("\n⚠ NO PP FIELDS FOUND IN systems_populated.json.gz")
    print("  This file does NOT contain Power Play data.")
    print("  A different Spansh endpoint is needed.")
    print("  Check the URL results above for an alternative.")
else:
    print(f"\n✓ PP data IS present: {pp_count} systems have controlling_power / power_state")

print("\nDone.")
