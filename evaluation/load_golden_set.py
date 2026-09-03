"""
Loads config/golden_set.csv (document_id, true_event_type,
true_sentiment_score, labeled_by) into evaluation_labels.

NOTE: config/golden_set.csv checked in here has a handful of illustrative
rows to show the expected shape. You still need to do the real 30-50
document manual labeling pass described in Part E of the spec — this
loader does not fabricate labels for you.
"""
from __future__ import annotations

import csv
import os
from decimal import Decimal

from db.repositories import EvaluationRepository
from db.session import get_session

CSV_PATH = os.path.join(os.path.dirname(__file__), "..", "config", "golden_set.csv")


def load(csv_path: str = CSV_PATH) -> int:
    n = 0
    with get_session() as session:
        repo = EvaluationRepository(session)
        with open(csv_path, newline="") as f:
            for row in csv.DictReader(f):
                repo.add_label(
                    document_id=int(row["document_id"]),
                    true_event_type=row["true_event_type"],
                    true_sentiment_score=Decimal(row["true_sentiment_score"]),
                    labeled_by=row["labeled_by"],
                )
                n += 1
    return n


if __name__ == "__main__":
    print(f"Loaded {load()} golden-set labels.")
