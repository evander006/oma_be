# OMA visual product search — full embedded catalogue

The Android app includes **134,266 real SKUs** from the 2026-10-28 OMA
export. Its SQLite asset includes SKU, name, category path, brand, price
snapshot and photo URLs, but **does not include image vectors**.

The old server `/api/v1/visual-search` searches a small demonstration
catalogue using vision-generated words and basic colour features. The
new implementation **prefers** a finished image-embedding index from the
Android export, while keeping the previous endpoint intact as a fallback.

## Build the index (on a workstation/GPU)

```bash
cd oma_be
python -m venv .venv
. .venv/bin/activate
pip install -r backend/requirements-visual-index.txt

python backend/scripts/build_full_visual_index.py \
  ../oma_front/android_companion/app/src/main/assets/embedded_catalog.db.bin \
  --output backend/data/visual_index --batch-size 12
```

Requirements: download access to the public product photos and the
`google/siglip2-base-patch16-224` weights, sufficient disk, and ideally
an NVIDIA GPU. CPU-only indexing is technically supported but slow.
The downloader limits each product image to 8 MB and tries up to three
URLs. Failures are skipped. After an interruption run the same command;
valid embeddings are retained. This is an offline job, **not** work
performed during a user's API request.

Files created:

- `vectors.npy`: memory-mapped, normalized float16 visual embeddings.
- `metadata.sqlite`: immutable SKU → original catalogue data mapping,
  keyed by vector row. Failed downloads have no row.
- `manifest.json`: model, source SHA-256, row counts and completion flag.

The index is enabled only when the *whole export was scanned* and at
least 80% of catalogue rows have a successfully encoded photograph
(configurable via `--minimum-coverage`). Inspect the count and failed
image coverage before relying on it; coverage is not automatically 100%.

A smoke-test with `--max-items 100` deliberately leaves the manifest
incomplete and does **not** activate partial search in production.

## Deploy

Copy the three generated files from the GPU machine to a persistent
directory on the backend host. Set

```text
OMA_VISUAL_INDEX_DIR=/path/to/persistent/visual_index
OMA_VISUAL_MIN_COSINE=0.15
```

Install the same optional ML requirements on the image-search API host.
The process loads the model only on its first indexed request.
**Measure RAM and response time on the real hosting tier before enabling
the index.** A small CPU-only Render instance may be too constrained for
SigLIP2 inference; use a separate inference service or a larger host if
necessary. The old search remains the fallback if the index, model or
optional dependencies are missing. Production credentials and uploads
must not be committed.

## How matching works

1. Android sends a resized photo to `POST /api/v1/visual-search`.
2. The server normalizes its SigLIP2 image embedding.
3. An **exact cosine scan** over memory-mapped vectors finds 240 nearest
   images, using at most 4096 float32 rows per block. This avoids a
   separate FAISS runtime and large in-memory full-float32 index.
4. Recognized object terms contribute only a **10% tie-breaker**. Visual
   appearance dominates the ranking.
5. Unique catalog SKUs are returned with image URL, brand, price snapshot,
   raw similarity, and `is_exact_match: false`.
6. Android accepts results only for SKUs present in its embedded catalogue
   and displays verified local product cards.

A complete index may return **zero matches**. The API must not then
replace the answer with unrelated demo products. Raw cosine similarity
is not a probability of exact SKU match; the Android UI intentionally
does not show fabricated confidence percentages.

## Quality gate before a public demo

Use a separately photographed, manually labelled test set (at least
100 query images across several departments, including no-match photos
and multiple viewing angles). Record Top-1 / Recall@5, wrong-category
rate, no-match false positives, p50/p95 latency and coverage of SKU
images. Calibrate `OMA_VISUAL_MIN_COSINE` from those results, not from
the training catalogue images. We have **not** measured production
accuracy or built the 134k embedding dataset in GitHub CI.

## Tests

```bash
pip install -r requirements.txt
PYTHONPATH=backend python -m pytest -q \
  backend/tests/test_visual_search.py \
  backend/tests/test_full_catalog_visual.py
```

No PyTorch or live image URLs are necessary for the deterministic unit
tests. Search and indexing must remain separate from the existing OMA
design, shopping cart and PDF features.
