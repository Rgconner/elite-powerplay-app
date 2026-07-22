import asyncio, json, httpx, sys

SPANSH_SYSTEM_URL = "https://spansh.co.uk/api/system/{}"

async def main():
    sys.stdout.write("Fetching system 594660018531...\n")
    sys.stdout.flush()
    
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(SPANSH_SYSTEM_URL.format(594660018531))
        sys.stdout.write(f"Status: {resp.status_code}\n")
        sys.stdout.flush()
        
        raw = resp.json()
        sys.stdout.write(f"Top-level keys: {list(raw.keys())}\n")
        sys.stdout.flush()
        
        # Check if record envelope exists
        if "record" in raw:
            rec = raw["record"]
            sys.stdout.write(f"record keys: {list(rec.keys())[:10]}\n")
            sys.stdout.flush()
        else:
            rec = raw
            sys.stdout.write("No 'record' key - data is flat\n")
            sys.stdout.flush()
        
        # Check for minor_faction_presences
        factions = rec.get("minor_faction_presences", [])
        sys.stdout.write(f"Factions: {len(factions)}\n")
        sys.stdout.flush()
        
        # Check BOOM
        has_boom = False
        for f in factions:
            for s in f.get("active_states", []):
                name = s if isinstance(s, str) else s.get("name", "")
                if name.upper() == "BOOM":
                    has_boom = True
                    sys.stdout.write(f"  Found BOOM in {f.get('name')}\n")
                    sys.stdout.flush()
        
        sys.stdout.write(f"has_boom: {has_boom}\n")
        sys.stdout.flush()
        
        # Check bodies for planets
        bodies = rec.get("bodies", [])
        sys.stdout.write(f"Bodies: {len(bodies)}\n")
        sys.stdout.flush()
        
        planets = [b for b in bodies if "planet" in (b.get("type") or "").lower()]
        sys.stdout.write(f"Planets: {len(planets)}\n")
        sys.stdout.flush()

asyncio.run(main())