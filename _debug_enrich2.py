import asyncio, sys
from routers.spansh import _enrich_system, _fetch_system, _check_system_for_boom, _check_body_for_platinum, _fetch_body

async def main():
    sid = 594660018531
    sys.stdout.write("Step 1: Fetching system...\n")
    sys.stdout.flush()
    system = await _fetch_system(sid)
    sys.stdout.write(f"  system is None: {system is None}\n")
    sys.stdout.flush()
    
    if system:
        has_boom = _check_system_for_boom(system)
        sys.stdout.write(f"  has_boom: {has_boom}\n")
        sys.stdout.flush()
        
        bodies = system.get("bodies", [])
        sys.stdout.write(f"  bodies: {len(bodies)}\n")
        sys.stdout.flush()
        
        planets = [b for b in bodies if "planet" in (b.get("type") or "").lower()]
        sys.stdout.write(f"  planets: {len(planets)}\n")
        sys.stdout.flush()
        
        # Check first planet
        if planets:
            p = planets[0]
            pid = p.get("id64")
            sys.stdout.write(f"  First planet: {p.get('name')} id64={pid}\n")
            sys.stdout.flush()
            
            sys.stdout.write("  Fetching body...\n")
            sys.stdout.flush()
            body = await _fetch_body(pid)
            if body:
                sys.stdout.write(f"  body keys: {list(body.keys())[:10]}\n")
                sys.stdout.flush()
                plat = _check_body_for_platinum(body)
                sys.stdout.write(f"  body platinum: {plat}\n")
                sys.stdout.flush()
            else:
                sys.stdout.write("  body is None!\n")
                sys.stdout.flush()
    
    sys.stdout.write("\nStep 2: Running full _enrich_system...\n")
    sys.stdout.flush()
    result = await _enrich_system(sid)
    sys.stdout.write(f"  Result: {result}\n")
    sys.stdout.flush()

asyncio.run(main())