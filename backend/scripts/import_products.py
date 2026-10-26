#!/usr/bin/env python3
"""Parse OMA.by products and/or import JSON into the database."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.core.config import get_settings
from app.core.logging import setup_logging
from app.db.base import Base
from app.db.session import SessionLocal, engine
from app.integrations.oma.parser import OmaParser
from app.services.catalog_service import upsert_products_from_json


def main() -> int:
    setup_logging()
    parser = argparse.ArgumentParser(description="Import OMA.by products")
    parser.add_argument("--max-products", type=int, default=20)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--skip-fetch", action="store_true", help="Only import existing JSON")
    parser.add_argument("--json", type=Path, default=None)
    args = parser.parse_args()

    settings = get_settings()
    Base.metadata.create_all(bind=engine)

    if not args.skip_fetch:
        with OmaParser(settings) as oma:
            report = oma.collect(max_products=args.max_products, dry_run=args.dry_run)
            report_path = oma.save_report(report)
            print(f"Import report: {report_path}")
            print(
                f"discovered={report.discovered} parsed={report.parsed} "
                f"validated={report.validated} images={report.images_downloaded} "
                f"failed={report.failed} products={len(report.products)}"
            )
            if report.errors:
                print("Errors (first 10):")
                for err in report.errors[:10]:
                    print(" -", err)
            if args.dry_run:
                return 0 if len(report.products) >= args.max_products else 1

    db = SessionLocal()
    try:
        stats = upsert_products_from_json(db, args.json)
        print("DB upsert:", stats)
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
