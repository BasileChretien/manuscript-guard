"""Reporting odds ratio for hepatic injury with example-drug.

Every number the manuscript quotes is emitted here. Nothing is printed for a human to copy
across: the manuscript reads this file, so the two cannot disagree.
"""

from __future__ import annotations

import csv
import math
from pathlib import Path

from manuscript_guard.emit import Emitter

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data" / "reports.csv"

DRUG = "example-drug"
EVENT = "hepatic injury"


def _pct(subset: list[dict], field: str, level: str) -> str:
    n = sum(1 for r in subset if r[field] == level)
    return f"{n} ({100 * n / len(subset):.1f})"


def main() -> None:
    with DATA.open(encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))

    a = sum(1 for r in rows if r["drug"] == DRUG and r["event"] == EVENT)
    b = sum(1 for r in rows if r["drug"] == DRUG and r["event"] != EVENT)
    c = sum(1 for r in rows if r["drug"] != DRUG and r["event"] == EVENT)
    d = sum(1 for r in rows if r["drug"] != DRUG and r["event"] != EVENT)

    ror = (a / b) / (c / d)
    se = math.sqrt(1 / a + 1 / b + 1 / c + 1 / d)
    low = math.exp(math.log(ror) - 1.96 * se)
    high = math.exp(math.log(ror) + 1.96 * se)

    years = sorted({int(r["year"]) for r in rows})
    serious = sum(1 for r in rows if r["drug"] == DRUG and r["event"] == EVENT and r["serious"] == "Y")

    em = Emitter(__file__, inputs=[DATA])
    em.value("cohort.n_reports", len(rows))
    em.value("cohort.n_drug_reports", a + b)
    em.value("cohort.period_start", years[0], display=str(years[0]))
    em.value("cohort.period_end", years[-1], display=str(years[-1]))
    em.value("cohort.n_years", years[-1] - years[0] + 1)

    em.value("case.n_cases", a)
    em.value("case.n_serious", serious)
    em.value("case.pct_serious", 100 * serious / a, digits=1, unit="%")

    em.value("ror.point", ror, digits=2)
    em.value("ror.ci_low", low, digits=2)
    em.value("ror.ci_high", high, digits=2)

    em.value("table2x2.a", a, quoted=False)
    em.value("table2x2.b", b, quoted=False)
    em.value("table2x2.c", c, quoted=False)
    em.value("table2x2.d", d, quoted=False)

    # The table is emitted, not written into the manuscript. A hand-typed table is the
    # most reliable place for a stale number to survive: long, dull to re-read, never
    # diffed.
    drug = [r for r in rows if r["drug"] == DRUG]
    other = [r for r in rows if r["drug"] != DRUG]
    em.table(
        "two_by_two",
        columns=["", "Hepatic injury", "Other events"],
        align=["left", "right", "right"],
        rows=[
            ["example-drug", str(a), str(b)],
            ["All other drugs", str(c), str(d)],
        ],
        caption="Contingency table underlying the reporting odds ratio.",
    )
    em.table(
        "baseline",
        columns=["Characteristic", "example-drug", "All other drugs"],
        align=["left", "right", "right"],
        rows=[
            ["Reports", str(len(drug)), str(len(other))],
            ["Hepatic injury", str(a), str(c)],
            *[
                [f"Age {group}", _pct(drug, "age_group", group), _pct(other, "age_group", group)]
                for group in ("18-44", "45-64", "65-74", "75+")
            ],
            ["Female", _pct(drug, "sex", "F"), _pct(other, "sex", "F")],
            ["Serious", _pct(drug, "serious", "Y"), _pct(other, "serious", "Y")],
        ],
        caption="Reports by drug group. Values are n (%) unless stated.",
    )

    path = em.write()
    print(f"wrote {path}")


if __name__ == "__main__":
    main()

