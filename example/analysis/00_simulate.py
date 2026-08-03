"""Create the synthetic spontaneous-reporting dataset the example analyses.

Seeded, so the file is byte-identical on every machine and the freshness gate's input
hashes mean something. This stands in for the step where a real project extracts from
VigiBase, FAERS or a national database.
"""

from __future__ import annotations

import csv
import random
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "reports.csv"

DRUGS = ["example-drug", "comparator-a", "comparator-b", "comparator-c"]
EVENTS = ["hepatic injury", "nausea", "rash", "headache", "neutropenia"]
SEXES = ["F", "M"]
AGE_GROUPS = ["18-44", "45-64", "65-74", "75+"]

# Probability of the event of interest, by drug. example-drug is given a genuine excess so
# the analysis has something to find.
P_HEPATIC = {"example-drug": 0.19, "comparator-a": 0.05, "comparator-b": 0.06, "comparator-c": 0.04}


def main() -> None:
    rng = random.Random(20260803)
    OUT.parent.mkdir(parents=True, exist_ok=True)

    rows = []
    for report_id in range(1, 4001):
        drug = rng.choices(DRUGS, weights=[1, 3, 3, 3])[0]
        if rng.random() < P_HEPATIC[drug]:
            event = "hepatic injury"
        else:
            event = rng.choice([e for e in EVENTS if e != "hepatic injury"])
        rows.append(
            {
                "report_id": f"R{report_id:05d}",
                "year": rng.randint(2015, 2024),
                "drug": drug,
                "event": event,
                "serious": "Y" if rng.random() < 0.38 else "N",
                "sex": rng.choice(SEXES),
                "age_group": rng.choice(AGE_GROUPS),
            }
        )

    with OUT.open("w", encoding="utf-8", newline="\n") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    print(f"wrote {len(rows)} rows to {OUT}")


if __name__ == "__main__":
    main()
