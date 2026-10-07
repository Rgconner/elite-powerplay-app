import requests

urls = [
    ("systems_populated", "https://downloads.spansh.co.uk/systems_populated.json.gz"),
    ("powerplay",         "https://downloads.spansh.co.uk/powerplay.json.gz"),
    ("galaxy_powerplay",  "https://downloads.spansh.co.uk/galaxy_powerplay.json.gz"),
    ("galaxy_1_week",     "https://downloads.spansh.co.uk/galaxy_1_week.json.gz"),
    ("galaxy",            "https://downloads.spansh.co.uk/galaxy.json.gz"),
    ("factions",          "https://downloads.spansh.co.uk/factions.json.gz"),
    ("spansh_api_pp",     "https://spansh.co.uk/api/download/powerplay"),
    ("pg_systems",        "https://downloads.spansh.co.uk/pg_systems.json.gz"),
    ("eddb_systems",      "https://downloads.spansh.co.uk/eddb_systems.csv.gz"),
    ("stars",             "https://downloads.spansh.co.uk/stars.json.gz"),
    ("bodies",            "https://downloads.spansh.co.uk/bodies.json.gz"),
    ("systems",           "https://downloads.spansh.co.uk/systems.json.gz"),
]

for name, url in urls:
    try:
        r = requests.head(url, timeout=10, allow_redirects=True)
        size = int(r.headers.get("Content-Length", 0))
        if size:
            size_str = str(round(size / 1_048_576, 1)) + " MB"
        else:
            size_str = "unknown"
        status = "OK " if r.status_code == 200 else str(r.status_code)
        print(status + "  " + size_str.rjust(12) + "  " + name.ljust(20) + "  " + url)
    except Exception as e:
        print("ERR               " + name.ljust(20) + "  " + str(e)[:60])
