import gzip, io, json, requests

# Peek at the first ~2MB of galaxy.json.gz to find PP fields
# (108 GB compressed would take hours - just grab first chunk)
url = "https://downloads.spansh.co.uk/galaxy.json.gz"
print("Peeking at", url, "(first 4 MB compressed)...")

r = requests.get(url, stream=True, timeout=60)
print("Status:", r.status_code)

chunk = b""
for c in r.iter_content(chunk_size=1024*1024):
    chunk += c
    if len(chunk) >= 4 * 1024 * 1024:
        break
r.close()
print("Got", len(chunk), "compressed bytes")

try:
    # Try partial decompression
    buf = io.BytesIO(chunk)
    gz = gzip.GzipFile(fileobj=buf)
    raw = gz.read(2 * 1024 * 1024)  # 2MB decompressed
    print("Decompressed:", len(raw), "bytes")
    text = raw.decode("utf-8", "replace")
    print("First 800 chars:")
    print(text[:800])
    print()

    # Try to find first complete JSON object
    depth = 0
    start = text.find("{")
    end = -1
    if start >= 0:
        for i, ch in enumerate(text[start:], start):
            if ch == "{": depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    end = i + 1
                    break
    if end > start >= 0:
        obj = json.loads(text[start:end])
        print("First object keys:", list(obj.keys()))
        pp_keys = [k for k in obj if "power" in k.lower() or "control" in k.lower()]
        print("PP-like keys:", pp_keys)
except Exception as e:
    print("Error:", e)
    print("Raw bytes (first 200):", chunk[:200])

print()

# Also check the Spansh search/filter API for PP systems
print("=== Checking Spansh search API for PP systems ===")
api_urls = [
    "https://spansh.co.uk/api/systems?controlling_power=Aisling+Duval&size=1",
    "https://spansh.co.uk/api/search?q=power_state:Stronghold&size=1",
    "https://spansh.co.uk/api/systems/search?q=Aisling+Duval&filter[controlling_power]=Aisling+Duval",
    "https://spansh.co.uk/api/systems?q=sol&filters[power_state][value]=Stronghold&filters[power_state][comparison]=eq",
]
for url in api_urls:
    try:
        r2 = requests.get(url, timeout=10)
        body = r2.text[:300]
        print(f"  {r2.status_code}  {url}")
        print(f"       {body[:200]}")
        print()
    except Exception as e:
        print(f"  ERR {url}: {e}")
