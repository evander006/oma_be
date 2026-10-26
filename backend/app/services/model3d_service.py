"""Procedural GLB generation (approximation, not photogrammetry)."""
from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import numpy as np
from pygltflib import (
    ARRAY_BUFFER,
    ELEMENT_ARRAY_BUFFER,
    FLOAT,
    GLTF2,
    UNSIGNED_SHORT,
    Accessor,
    Asset,
    Buffer,
    BufferView,
    Material,
    Mesh,
    Node,
    PbrMetallicRoughness,
    Primitive,
    Scene,
)
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.logging import get_logger
from app.db.models import Product

logger = get_logger(__name__)


def _box_mesh(sx: float, sy: float, sz: float, ox: float = 0, oy: float = 0, oz: float = 0):
    """Axis-aligned box centered at origin then offset; y-up."""
    hx, hy, hz = sx / 2, sy / 2, sz / 2
    corners = np.array(
        [
            [-hx, -hy, -hz],
            [hx, -hy, -hz],
            [hx, hy, -hz],
            [-hx, hy, -hz],
            [-hx, -hy, hz],
            [hx, -hy, hz],
            [hx, hy, hz],
            [-hx, hy, hz],
        ],
        dtype=np.float32,
    )
    corners[:, 0] += ox
    corners[:, 1] += oy
    corners[:, 2] += oz
    faces = np.array(
        [
            [0, 1, 2],
            [0, 2, 3],
            [4, 6, 5],
            [4, 7, 6],
            [0, 4, 5],
            [0, 5, 1],
            [1, 5, 6],
            [1, 6, 2],
            [2, 6, 7],
            [2, 7, 3],
            [3, 7, 4],
            [3, 4, 0],
        ],
        dtype=np.uint16,
    )
    return corners, faces


def _merge(meshes: list[tuple[np.ndarray, np.ndarray]]) -> tuple[np.ndarray, np.ndarray]:
    verts = []
    faces = []
    offset = 0
    for v, f in meshes:
        verts.append(v)
        faces.append(f + offset)
        offset += len(v)
    return np.vstack(verts), np.vstack(faces)


def _geometry_for_category(category_id: str | None, dims: tuple[float, float, float]):
    w, h, d = dims
    parts: list[tuple[np.ndarray, np.ndarray]] = []
    cat = (category_id or "").lower()
    if "light" in cat or "lamp" in cat or "osvesh" in cat:
        # lamp: base + stem + shade
        parts.append(_box_mesh(w * 0.45, h * 0.08, d * 0.45, 0, h * 0.04, 0))
        parts.append(_box_mesh(w * 0.08, h * 0.55, d * 0.08, 0, h * 0.35, 0))
        parts.append(_box_mesh(w * 0.7, h * 0.25, d * 0.7, 0, h * 0.78, 0))
    elif "faucet" in cat or "smesit" in cat or "plumbing-faucet" in cat:
        parts.append(_box_mesh(w * 0.35, h * 0.15, d * 0.35, 0, h * 0.08, 0))
        parts.append(_box_mesh(w * 0.12, h * 0.55, d * 0.12, 0, h * 0.4, 0))
        parts.append(_box_mesh(w * 0.55, h * 0.12, d * 0.12, w * 0.2, h * 0.7, 0))
    elif "sink" in cat or "moyk" in cat or "rakovin" in cat or "kitchen" in cat:
        parts.append(_box_mesh(w, h * 0.25, d, 0, h * 0.12, 0))
        parts.append(_box_mesh(w * 0.7, h * 0.2, d * 0.55, 0, h * 0.05, 0))
    elif "bath" in cat or "vann" in cat:
        parts.append(_box_mesh(w, h * 0.45, d, 0, h * 0.22, 0))
        parts.append(_box_mesh(w * 0.85, h * 0.2, d * 0.75, 0, h * 0.35, 0))
    elif "mirror" in cat or "zerkal" in cat:
        parts.append(_box_mesh(w, h, max(d, 0.02), 0, h / 2, 0))
    elif "shelf" in cat or "polk" in cat:
        parts.append(_box_mesh(w, max(h * 0.08, 0.02), d, 0, h * 0.5, 0))
        parts.append(_box_mesh(w * 0.05, h, d * 0.05, -w * 0.45, h * 0.5, -d * 0.4))
        parts.append(_box_mesh(w * 0.05, h, d * 0.05, w * 0.45, h * 0.5, -d * 0.4))
    elif "furniture" in cat or "mebel" in cat:
        # simple table
        parts.append(_box_mesh(w, h * 0.08, d, 0, h * 0.92, 0))
        for ox, oz in [(-w * 0.4, -d * 0.4), (w * 0.4, -d * 0.4), (-w * 0.4, d * 0.4), (w * 0.4, d * 0.4)]:
            parts.append(_box_mesh(w * 0.08, h * 0.9, d * 0.08, ox, h * 0.45, oz))
    else:
        parts.append(_box_mesh(w, h, d, 0, h / 2, 0))
    return _merge(parts)


def _write_glb(vertices: np.ndarray, indices: np.ndarray, path: Path, color=(0.75, 0.75, 0.78, 1.0)) -> None:
    vertices = vertices.astype(np.float32)
    indices = indices.astype(np.uint16)
    v_bytes = vertices.tobytes()
    i_bytes = indices.tobytes()
    # pad to 4-byte alignment
    pad_v = (4 - (len(v_bytes) % 4)) % 4
    v_bytes += b"\x00" * pad_v
    pad_i = (4 - (len(i_bytes) % 4)) % 4
    i_bytes += b"\x00" * pad_i
    blob = v_bytes + i_bytes

    mins = vertices.min(axis=0).tolist()
    maxs = vertices.max(axis=0).tolist()

    gltf = GLTF2(
        asset=Asset(version="2.0", generator="oma-dom-procedural"),
        scenes=[Scene(nodes=[0])],
        nodes=[Node(mesh=0)],
        meshes=[
            Mesh(
                primitives=[
                    Primitive(attributes={"POSITION": 0}, indices=1, material=0)
                ]
            )
        ],
        materials=[
            Material(
                name="neutral",
                pbrMetallicRoughness=PbrMetallicRoughness(
                    baseColorFactor=list(color),
                    metallicFactor=0.05,
                    roughnessFactor=0.7,
                ),
            )
        ],
        accessors=[
            Accessor(
                bufferView=0,
                componentType=FLOAT,
                count=len(vertices),
                type="VEC3",
                max=maxs,
                min=mins,
            ),
            Accessor(
                bufferView=1,
                componentType=UNSIGNED_SHORT,
                count=int(indices.size),
                type="SCALAR",
            ),
        ],
        bufferViews=[
            BufferView(buffer=0, byteOffset=0, byteLength=len(v_bytes), target=ARRAY_BUFFER),
            BufferView(
                buffer=0,
                byteOffset=len(v_bytes),
                byteLength=len(i_bytes),
                target=ELEMENT_ARRAY_BUFFER,
            ),
        ],
        buffers=[Buffer(byteLength=len(blob))],
    )
    gltf.set_binary_blob(blob)
    path.parent.mkdir(parents=True, exist_ok=True)
    gltf.save_binary(str(path))


def _dims_meters(product: Product) -> tuple[float, float, float, bool]:
    """Return (w,h,d) in meters and whether approximate."""
    approx = False
    def mm(val: Decimal | None, fallback: float) -> float:
        nonlocal approx
        if val is None:
            approx = True
            return fallback
        return float(val) / 1000.0

    cat = product.category_id or ""
    if "light" in cat:
        defaults = (0.25, 0.45, 0.25)
    elif "faucet" in cat or "smesit" in cat:
        defaults = (0.15, 0.25, 0.15)
    elif "bath" in cat:
        defaults = (1.7, 0.55, 0.75)
    elif "sink" in cat or "moyk" in cat or "rakovin" in cat:
        defaults = (0.6, 0.2, 0.5)
    elif "mirror" in cat:
        defaults = (0.6, 0.8, 0.03)
    elif "shelf" in cat:
        defaults = (0.8, 0.3, 0.25)
    else:
        defaults = (0.8, 0.75, 0.6)

    w = mm(product.width_mm or product.diameter_mm, defaults[0])
    h = mm(product.height_mm, defaults[1])
    d = mm(product.depth_mm or product.diameter_mm, defaults[2])
    return max(w, 0.05), max(h, 0.05), max(d, 0.02), approx


def validate_glb(path: Path) -> bool:
    if not path.is_file() or path.stat().st_size < 20:
        return False
    raw = path.read_bytes()
    if raw[:4] != b"glTF":
        return False
    try:
        gltf = GLTF2().load_binary(str(path))
        return gltf.asset is not None and bool(gltf.meshes)
    except Exception:  # noqa: BLE001
        return False


def generate_models_for_products(db: Session, product_ids: list[str] | None = None) -> dict:
    settings = get_settings()
    q = db.query(Product)
    if product_ids:
        q = q.filter(Product.id.in_(product_ids))
    products = q.all()
    generated = 0
    validated = 0
    failed: list[str] = []
    for product in products:
        w, h, d, approx = _dims_meters(product)
        verts, faces = _geometry_for_category(product.category_id, (w, h, d))
        out = settings.models_dir / f"{product.id}.glb"
        try:
            _write_glb(verts, faces, out)
            ok = validate_glb(out)
            product.has_3d_model = ok
            product.model_path = f"models/products/{product.id}.glb" if ok else None
            product.model_format = "glb"
            product.model_source = "procedural_python"
            product.model_status = "ready" if ok else "invalid"
            product.model_limitations = (
                "Procedurally generated approximation for visualization only; "
                "not an exact digital twin of the retail product. "
                + ("Some dimensions were approximate placeholders because source data lacked measurements." if approx else "Dimensions derived from source-provided measurements where available.")
            )
            product.model_width_m = Decimal(str(round(w, 4)))
            product.model_height_m = Decimal(str(round(h, 4)))
            product.model_depth_m = Decimal(str(round(d, 4)))
            product.model_units = "m"
            if ok:
                generated += 1
                validated += 1
            else:
                failed.append(product.id)
        except Exception as exc:  # noqa: BLE001
            logger.exception("GLB generation failed for %s", product.id)
            failed.append(f"{product.id}: {exc}")
            product.has_3d_model = False
            product.model_status = "failed"
    db.commit()
    return {
        "products": len(products),
        "generated": generated,
        "validated": validated,
        "failed": failed,
    }
