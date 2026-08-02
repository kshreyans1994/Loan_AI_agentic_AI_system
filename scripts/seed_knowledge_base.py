"""
Seed the pgvector knowledge base with sample loan policies and FAQs.

Run after applying app/db/schema.sql:
    python scripts/seed_knowledge_base.py
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.rag.retriever import get_retriever  # noqa: E402

SEED_PATH = Path(__file__).resolve().parent.parent / "data" / "seed" / "knowledge_base.json"


def main() -> None:
    retriever = get_retriever()
    entries = json.loads(SEED_PATH.read_text())

    for entry in entries:
        retriever.upsert_document(
            doc_id=entry["id"],
            content=entry["content"],
            source=entry["source"],
            metadata=entry.get("metadata", {}),
        )
        print(f"Upserted: {entry['id']}")

    print(f"Done. Seeded {len(entries)} knowledge base entries.")


if __name__ == "__main__":
    main()
