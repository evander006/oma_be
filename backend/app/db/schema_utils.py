"""Lightweight SQLite column patches for evolving create_all deployments."""
from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.engine import Engine


# Columns added after the initial products table — safe to ADD if missing.
_PRODUCT_COLUMN_PATCHES: list[tuple[str, str]] = [
    ("style_tags", "TEXT"),
    ("room_types", "TEXT"),
    ("installation_notes", "TEXT"),
    ("installation_compatible", "BOOLEAN"),
]


def ensure_sqlite_product_columns(engine: Engine) -> None:
    if not str(engine.url).startswith("sqlite"):
        return
    with engine.begin() as conn:
        rows = conn.execute(text("PRAGMA table_info(products)")).fetchall()
        if not rows:
            return
        existing = {r[1] for r in rows}
        for name, col_type in _PRODUCT_COLUMN_PATCHES:
            if name not in existing:
                conn.execute(text(f"ALTER TABLE products ADD COLUMN {name} {col_type}"))
