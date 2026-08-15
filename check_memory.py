import sys
sys.path.insert(0, ".")

import psycopg
from app.core.config import get_settings

conn = psycopg.connect(get_settings().postgres_dsn, autocommit=True)

print("=== user_memory_facts ===")
rows = conn.execute(
    "SELECT id, user_id, fact, category, confidence, created_at "
    "FROM user_memory_facts ORDER BY created_at DESC"
).fetchall()
if not rows:
    print("(empty)")
for r in rows:
    print(f"  id={r[0]}  user_id={r[1]!r}  fact={r[2]!r}  category={r[3]}  confidence={r[4]}  created_at={r[5]}")

print()
print("=== session_summaries ===")
rows = conn.execute(
    "SELECT id, user_id, session_id, summary, created_at "
    "FROM session_summaries ORDER BY created_at DESC"
).fetchall()
if not rows:
    print("(empty)")
for r in rows:
    print(f"  id={r[0]}  user_id={r[1]!r}  session_id={r[2][:8]}...  summary={r[3]!r}  created_at={r[4]}")