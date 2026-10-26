"""Keep only image files referenced in products.json."""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
products = json.loads((ROOT / "data" / "products" / "products.json").read_text(encoding="utf-8"))
keep: set[Path] = set()
for p in products:
    for rel in p.get("local_images") or []:
        keep.add((ROOT / "data" / Path(rel)).resolve())

removed = 0
img_root = ROOT / "data" / "images" / "products"
for path in img_root.rglob("*"):
    if path.is_file() and path.resolve() not in keep:
        path.unlink()
        removed += 1
print("kept", len(keep), "removed", removed)
