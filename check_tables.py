import sys
sys.path.insert(0, ".")

import psycopg
from app.core.config import get_settings

conn = psycopg.connect(get_settings().postgres_dsn, autocommit=True)
rows = conn.execute(
    "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'"
).fetchall()

print("Tables in public schema:")
for r in rows:
    print(" -", r[0])