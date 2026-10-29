"""The quality report uses labelled camera photos, not catalog-image self matches."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from evaluate_full_visual import summarize


def test_metrics_count_true_matches_and_negative_false_positives():
    report = summarize([
        {"expected_skus": ["A"], "returned": ["A", "C"], "duration_ms": 10},
        {"expected_skus": ["B"], "returned": ["X", "B"], "duration_ms": 20},
        {"expected_skus": ["C"], "returned": ["X"], "duration_ms": 40},
        {"expected_skus": [], "returned": ["X"], "duration_ms": 80},
        {"expected_skus": [], "returned": [], "duration_ms": 100},
    ])
    assert report["positive_queries"] == 3
    assert report["negative_queries"] == 2
    assert report["top1_accuracy"] == 0.3333
    assert report["recall_at_5"] == 0.6667
    assert report["no_match_false_positive_rate"] == 0.5
    assert report["p50_ms"] == 40
    assert report["p95_ms"] == 100
