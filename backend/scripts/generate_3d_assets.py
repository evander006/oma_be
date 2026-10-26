#!/usr/bin/env python3
"""Generate procedural GLB approximations for catalog products."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.core.logging import setup_logging
from app.db.base import Base
from app.db.session import SessionLocal, engine
from app.services.model3d_service import generate_models_for_products


def main() -> int:
    setup_logging()
    parser = argparse.ArgumentParser()
    parser.add_argument("--product-id", action="append", default=None)
    args = parser.parse_args()
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        result = generate_models_for_products(db, args.product_id)
        print(result)
        return 0 if result["validated"] == result["products"] else 1
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
