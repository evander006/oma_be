#!/usr/bin/env python3
"""Evaluate the full OMA image index on independent, human-labeled photographs.

JSONL format:
{"image":"photos/query1.jpg","expected_skus":["1.123456"]}
{"image":"photos/no_match.jpg","expected_skus":[]}

Do not use the same product photos that were indexed as validation photos:
that measures memorization rather than real camera performance.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import statistics
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.services.full_catalog_visual import search_full_catalog  # noqa: E402


def summarize(results: list[dict]) -> dict:
    if not results:
        raise ValueError("No evaluation results")
    positive = [r for r in results if r["expected_skus"]]
    negative = [r for r in results if not r["expected_skus"]]
    if positive:
        top1 = sum(bool(r["returned"] and r["returned"][0] in r["expected_skus"]) for r in positive)
        top5 = sum(bool(set(r["returned"][:5]) & set(r["expected_skus"])) for r in positive)
        wrong_category = sum(bool(r.get("wrong_category", False)) for r in positive)
    else:
        top1 = top5 = wrong_category = 0
    false_positives = sum(bool(r["returned"]) for r in negative)
    milliseconds = sorted(float(r["duration_ms"]) for r in results)

    def percentile(p: float) -> float:
        i = min(len(milliseconds) - 1, max(0, int((len(milliseconds) - 1) * p + 0.9999)))
        return round(milliseconds[i], 1)

    return {
        "queries": len(results),
        "positive_queries": len(positive),
        "negative_queries": len(negative),
        "top1_accuracy": round(top1 / len(positive), 4) if positive else None,
        "recall_at_5": round(top5 / len(positive), 4) if positive else None,
        "no_match_false_positive_rate": round(false_positives / len(negative), 4) if negative else None,
        "p50_ms": percentile(0.50),
        "p95_ms": percentile(0.95),
    }


def evaluate(dataset: Path, data_dir: Path) -> dict:
    results = []
    with dataset.open(encoding="utf-8") as reader:
        for number, line in enumerate(reader, 1):
            if not line.strip():
                continue
            obj = json.loads(line)
            photo = (dataset.parent / obj["image"]).resolve()
            expected = obj.get("expected_skus", [])
            if isinstance(expected, str):
                expected = [expected]
            if not isinstance(expected, list):
                raise ValueError(f"Record {number}: expected_skus must be an array")
            if not photo.is_file():
                raise ValueError(f"Record {number}: photo not found: {photo}")
            started = time.perf_counter()
            outcome = search_full_catalog(photo.read_bytes(), [], data_dir)
            elapsed = (time.perf_counter() - started) * 1000
            if outcome is None:
                raise RuntimeError("The full embedding index is not available: no benchmark possible")
            returned = [row["sku"] for row in outcome["matches"]]
            results.append({
                "image": obj["image"], "expected_skus": expected,
                "returned": returned, "duration_ms": elapsed,
            })
            print(f"query={number} hits={len(returned)} latency_ms={elapsed:.1f}", flush=True)
    return summarize(results)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", required=True, type=Path)
    parser.add_argument("--index-dir", required=True, type=Path)
    parser.add_argument("--output", required=False, type=Path)
    args = parser.parse_args()
    import os
    os.environ["OMA_VISUAL_INDEX_DIR"] = str(args.index_dir.resolve())
    report = evaluate(args.dataset.resolve(), args.index_dir.resolve())
    serialized = json.dumps(report, ensure_ascii=False, indent=2)
    print(serialized)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(serialized, encoding="utf-8")


if __name__ == "__main__":
    main()
