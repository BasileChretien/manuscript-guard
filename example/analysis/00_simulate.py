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
#: The generator's own list of event terms, written beside the data with its release on the
#: first line, as a coding dictionary carries its version: the analysis declares the list
#: from this file, so the release the supplement prints is the list's own.
TERMS = ROOT / "data" / "event_terms.txt"
TERMS_RELEASE = "1"

DRUGS = ["example-drug", "comparator-a", "comparator-b", "comparator-c"]
EVENTS = ["hepatic injury", "nausea", "rash", "headache", "neutropenia"]
SEXES = ["F", "M"]
AGE_GROUPS = ["18-44", "45-64", "65-74", "75+"]

# Probability of the event of interest, by drug. example-drug is given a genuine excess so
# the analysis has something to find.
P_HEPATIC = {"example-drug": 0.19, "comparator-a": 0.05, "comparator-b": 0.06, "comparator-c": 0.04}

#: The simulated control's own data (the plan's Known answers): reports in which hepatic
#: injury is planted for example-drug at twice the odds of the other drugs, so that the
#: analysis is shown to find a ratio it was given. Seeded apart from the reports, which stay
#: as they were, and written beside them.
CONTROL = ROOT / "data" / "control_simulated.csv"
CONTROL_SEED = 20261109
CONTROL_ODDS_RATIO = 2
CONTROL_P_OTHERS = 0.05


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

    TERMS.write_text("\n".join([TERMS_RELEASE, *EVENTS]) + "\n", encoding="utf-8", newline="\n")
    with OUT.open("w", encoding="utf-8", newline="\n") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    print(f"wrote {len(rows)} rows to {OUT}")
    control = simulate_control()
    with CONTROL.open("w", encoding="utf-8", newline="\n") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(control[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(control)
    print(f"wrote {len(control)} rows to {CONTROL}")


def simulate_control() -> list[dict]:
    """The simulated control's reports: the drugs drawn as in the reports, hepatic injury
    planted for example-drug at CONTROL_ODDS_RATIO times the odds of the others."""
    rng = random.Random(CONTROL_SEED)
    odds = CONTROL_ODDS_RATIO * CONTROL_P_OTHERS / (1 - CONTROL_P_OTHERS)
    planted = {drug: CONTROL_P_OTHERS for drug in DRUGS} | {"example-drug": odds / (1 + odds)}
    rows = []
    for report_id in range(1, 4001):
        drug = rng.choices(DRUGS, weights=[1, 3, 3, 3])[0]
        if rng.random() < planted[drug]:
            event = "hepatic injury"
        else:
            event = rng.choice([e for e in EVENTS if e != "hepatic injury"])
        rows.append({"report_id": f"C{report_id:05d}", "drug": drug, "event": event})
    return rows


if __name__ == "__main__":
    main()
