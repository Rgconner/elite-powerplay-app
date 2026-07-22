import gzip, io, json, requests

# systems_populated.json.gz is only 4.1 MB — download and fully scan it
url = "https://downloads.spansh.co.uk/systems_populated.json.gz"
print("Downloading", url)
r = requests.get(url, timeout=120)
print("Status:", r.status_code, "Compressed:", len(r.content), "bytes")

data = gzip.decompress(r.content)
print("Decompressed:", len(data), "bytes /", round(len(data)/1_048_576, 1), "MB")

arr = json.loads(data)
print("Total systems in file:", len(arr))
print()

# Gather all unique keys across the whole file
all_keys = set()
pp_fields = ["controlling_power", "power", "power_state",
             "power_state_reinforcement", "power_state_undermining",
             "powerState", "controllingPower", "controllingFaction"]
pp_found = 0
for i, obj in enumerate(arr):
    all_keys.update(obj.keys())
    if any(f in obj for f in pp_fields):
        pp_found += 1
        if pp_found <= 2:
            print("PP system found at index", i, "-", obj.get("name","?"))
            for k, v in obj.items():
                print("  ", k, "=", repr(v)[:100])
            print()

print("All unique keys across", len(arr), "systems:", sorted(all_keys))
print("PP-field systems found:", pp_found)
