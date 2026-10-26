import json
from pathlib import Path

root = Path(__file__).resolve().parents[1] / "data"
products = json.loads((root / "products" / "products.json").read_text(encoding="utf-8"))
imgs = list((root / "images" / "products").rglob("*.*"))
glbs = list((root / "models" / "products").glob("*.glb"))
print("products", len(products))
print("categories", sorted({p.get("category_id") for p in products}))
print("with_price", sum(1 for p in products if p.get("price") is not None))
print("local_images_entries", sum(len(p.get("local_images") or []) for p in products))
print("image_files", len([i for i in imgs if i.is_file()]))
print("glb_files", len(glbs))
print("names:")
for p in products:
    print("-", p.get("category_id"), p.get("name"), p.get("price"), p.get("currency"))
