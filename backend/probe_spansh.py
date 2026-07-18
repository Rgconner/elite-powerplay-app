#!/usr/bin/env python3
"""Diagnostic probe for the Spansh systems_populated.json.gz file.

Run this on the server to find out:
  1. Whether the download succeeds
  2. What the top-level JSON structure looks like
  3. What fields the first system object has
  4. Whether controlling_power / power_state are present

Usage (from backend/ with venv active):
    python probe_spansh.py
"""

import gzip
import io
import json
import sys

import requests

URL = "https://downloads.spansh.co.uk/systems_populated.json.gz"
PEEK_BYTES = 8192  # read first 8 KB of decompressed JSON


def main() -> None:
    print(f"Probing: {URL}")
    print("-" * 60)

    try:
        resp = requests.get(URL, stream=True, timeout=60)
        resp.raise_for_status()
    except Exception as exc:
        print(f"ERROR — HTTP request failed: {exc}")
        sys.exit(1)

    print(f"HTTP status : {resp.status_code}")
    print(f"Content-Type: {resp.headers.get('Content-Type', 'n/a')}")
    print(f"Content-Enc : {resp.headers.get('Content-Encoding', 'n/a')}")
    print(f"Content-Len : {resp.headers.get('Content-Length', 'unknown')} bytes (compressed)")
    print()

    # Read the first chunk of the response body (compressed)
    raw_chunk = b""
    for chunk in resp.iter_content(chunk_size=65536):
        raw_chunk += chunk
        if len(raw_chunk) >= 65536:
            break
    resp.close()

    print(f"Downloaded  : {len(raw_chunk):,} compressed bytes for inspection")

    # Try to decompress
    try:
        buf = io.BytesIO(raw_chunk)
        with gzip.GzipFile(fileobj=buf) as gz:
            decompressed = gz.read(PEEK_BYTES)
    except Exception as exc:
        print(f"ERROR — gzip decompression failed: {exc}")
        print("Raw bytes (first 200):", raw_chunk[:200])
        sys.exit(1)

    text = decompressed.decode("utf-8", errors="replace")
    print(f"Decompressed: {len(text)} chars (first {PEEK_BYTES} bytes)")
    print()
    print("=== RAW JSON PREFIX (first 500 chars) ===")
    print(text[:500])
    print()

    # Try to detect structure
    stripped = text.lstrip()
    if stripped.startswith("["):
        print("✓ Top-level structure: ARRAY  →  ijson prefix should be 'item'")
    elif stripped.startswith("{"):
        print("⚠ Top-level structure: OBJECT  →  ijson prefix is NOT 'item'")
        # Try to find the array key
        try:
            partial = json.loads(text + "]}")  # may fail, just try
        except Exception:
            pass
        # Show first key
        colon_pos = stripped.find(":")
        if colon_pos > 0:
            key = stripped[1:colon_pos].strip().strip('"')
            print(f"   First key detected: '{key}'")
            print(f"   Try ijson prefix:   '{key}.item'")
    else:
        print(f"⚠ Unexpected first char: {repr(stripped[:20])}")

    print()

    # Try to parse the first complete object from the stream
    # Find first '{' and matching '}'
    depth = 0
    start = text.find("{")
    end = -1
    if start >= 0:
        for i, ch in enumerate(text[start:], start):
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    end = i + 1
                    break

    if start >= 0 and end > start:
        try:
            obj = json.loads(text[start:end])
            print("=== FIRST SYSTEM OBJECT KEYS ===")
            for key, val in obj.items():
                display = repr(val) if not isinstance(val, (dict, list)) else f"{type(val).__name__}({len(val)} items)" if isinstance(val, list) else f"dict({list(val.keys())})"
                print(f"  {key:<40} = {display}")
            print()

            # Check for PP fields
            pp_fields = [
                "controlling_power", "power", "power_state",
                "power_state_reinforcement", "power_state_undermining",
                "power_state_control_progress",
            ]
            print("=== PP 2.0 FIELD CHECK ===")
            for f in pp_fields:
                present = f in obj
                val = obj.get(f, "<missing>")
                status = "✓" if present else "✗ MISSING"
                print(f"  {status}  {f:<40} = {repr(val)}")
        except json.JSONDecodeError as exc:
            print(f"Could not parse first object: {exc}")
            print("Raw first-object text:", text[start:start+300])
    else:
        print("Could not locate a JSON object in the decompressed content.")

    print()
    print("Done.")


if __name__ == "__main__":
    main()
