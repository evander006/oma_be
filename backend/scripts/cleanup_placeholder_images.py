from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "data" / "images" / "products"
n = 0
for p in ROOT.rglob("*"):
    if p.is_file() and any(x in p.name.lower() for x in ("cardinb2b", "card_for_mobile")):
        p.unlink()
        n += 1
print("removed", n)
