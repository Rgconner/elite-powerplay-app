import os, sys
os.chdir('/app')
sys.path.insert(0, '.')
from db.session import engine
from sqlalchemy import text
with engine.connect() as c:
    r = c.execute(text("DELETE FROM spansh_enrichment"))
    c.commit()
    print("Deleted", r.rowcount, "rows")