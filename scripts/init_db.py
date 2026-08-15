"""
One-time (and safely re-runnable) database setup.

Applies app/db/schema.sql and app/db/memory_schema.sql against
whatever POSTGRES_DSN is configured in your .env — no DSN typed by
hand, so there's no placeholder-substitution mistake to make. Every
statement in both files uses CREATE TABLE IF NOT EXISTS / CREATE INDEX
IF NOT EXISTS, so running this multiple times is harmless.

Run with:
    python scripts/init_db.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import psycopg

# Make `app` importable when this script is run directly (python
# scripts/init_db.py) rather than as an installed package.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.config import get_settings  # noqa: E402

SCHEMA_FILES = ["app/db/schema.sql", "app/db/memory_schema.sql"]


def main() -> None:
    settings = get_settings()
    project_root = Path(__file__).resolve().parent.parent

    print(f"Connecting to: {settings.postgres_dsn}")

    try:
        conn = psycopg.connect(settings.postgres_dsn, autocommit=True)
    except psycopg.Error as exc:
        print(f"\n❌ Could not connect to Postgres: {exc}")
        print("Check POSTGRES_DSN in your .env and that Postgres is actually running.")
        sys.exit(1)

    with conn:
        for relative_path in SCHEMA_FILES:
            sql_path = project_root / relative_path
            if not sql_path.exists():
                print(f"❌ Missing file: {sql_path}")
                sys.exit(1)

            print(f"Applying {relative_path} ...")
            sql = sql_path.read_text()
            conn.execute(sql)
            print(f"  ✅ done")

    print("\nAll schema files applied successfully.")


if __name__ == "__main__":
    main()