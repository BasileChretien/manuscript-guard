"""Reporting odds ratio for hepatic injury with example-drug.

Every number the manuscript quotes is emitted here. Nothing is printed for a human to copy
across: the manuscript reads this file, so the two cannot disagree.
"""

from __future__ import annotations

import csv
import math
from pathlib import Path
from statistics import NormalDist

import pandas as pd
import statsmodels.api as sm
import statsmodels.formula.api as smf

from manuscript_guard.emit import Emitter

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data" / "reports.csv"

DRUG = "example-drug"
EVENT = "hepatic injury"


def _pct(em: Emitter, subset: list[dict], field: str, level: str):
    """An "n (%)" cell, composed by the emitter rather than by an f-string.

    An f-string here would produce exactly the same characters, and that is the point: by
    the time `table()` sees a string it cannot tell a computed cell from a typed one. Handing
    over the numbers is what makes the cell traceable.
    """
    n = sum(1 for r in subset if r[field] == level)
    return em.cell("{} ({})", n, (100 * n / len(subset), 1))


def main() -> None:
    with DATA.open(encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))

    em = Emitter(__file__, inputs=[DATA])

    # The choices the Methods state, declared where the code makes them and used from here.
    # The Methods bind them, so the alpha and the signal criterion they print are the ones
    # this run applied, and G2 fails either one typed instead.
    alpha = em.parameter("alpha", 0.05)
    min_cases = em.parameter("signal.min_cases", 3)

    # Each step the Methods describe is marked, and the paragraph describing it ends with
    # {{method.<name>}}. G9 keeps each step and its paragraph as a pair that a person read
    # together, and names the pair when either changes.
    with em.step("ror"):
        a = sum(1 for r in rows if r["drug"] == DRUG and r["event"] == EVENT)
        b = sum(1 for r in rows if r["drug"] == DRUG and r["event"] != EVENT)
        c = sum(1 for r in rows if r["drug"] != DRUG and r["event"] == EVENT)
        d = sum(1 for r in rows if r["drug"] != DRUG and r["event"] != EVENT)
        ror = (a / b) / (c / d)

    with em.step("ci"):
        # The normal quantile for that alpha, to two places as the textbook writes it: 1.96.
        z = round(NormalDist().inv_cdf(1 - alpha / 2), 2)
        se = math.sqrt(1 / a + 1 / b + 1 / c + 1 / d)
        low = math.exp(math.log(ror) - z * se)
        high = math.exp(math.log(ror) + z * se)
        low90 = math.exp(math.log(ror) - 1.645 * se)
        high90 = math.exp(math.log(ror) + 1.645 * se)

    years = sorted({int(r["year"]) for r in rows})
    serious = sum(
        1 for r in rows if r["drug"] == DRUG and r["event"] == EVENT and r["serious"] == "Y"
    )

    # The signal criterion of the Methods, applied. It was stated there and computed nowhere
    # until the threshold had to be declared: a parameter nobody reads is a G2 failure.
    # The verdict is a word the Results bind, so they say "not met" the day it is not. It is
    # the name of the category the result falls in, not a sentence, hence `label`.
    with em.step("signal"):
        met = a >= min_cases and low > 1
        em.value("signal.met", met, quoted=False)
        em.value("signal.verdict", "met" if met else "not met", label=True)
    em.software("python")
    em.software("statsmodels")

    # The ratio adjusted for age group and sex, by logistic regression. The model is
    # recorded as the fit describes itself, and each variable it reads is declared with the
    # kind it is meant to be: G15 holds the two to each other, and the paper's table of the
    # model is made from them rather than typed.
    with em.step("adjusted"):
        frame = pd.DataFrame(rows)
        frame["hepatic"] = (frame["event"] == EVENT).astype(int)
        frame["exposed"] = (frame["drug"] == DRUG).astype(int)
        em.variable("hepatic", "binary", label="hepatic injury", levels=[0, 1],
                    values=frame["hepatic"])
        em.variable("exposed", "binary", label="example-drug", levels=[0, 1],
                    values=frame["exposed"])
        em.variable("age_group", "categorical", label="age group",
                    levels=["18-44", "45-64", "65-74", "75+"], reference="18-44",
                    values=frame["age_group"])
        em.variable("sex", "binary", label="sex", levels=["F", "M"], reference="F",
                    values=frame["sex"])
        fit = smf.glm(
            "hepatic ~ exposed + C(age_group, Treatment('18-44')) + C(sex, Treatment('F'))",
            frame,
            family=sm.families.Binomial(),
        ).fit()
        em.model(
            "adjusted",
            fit,
            name="Adjusted model",
            description="The reporting odds ratio of the primary analysis, adjusted for the "
            "two patient characteristics the database records for every report.",
        )
        bounds = fit.conf_int(alpha=alpha).loc["exposed"]
        adjusted_low, adjusted_high = (math.exp(bound) for bound in bounds)
        em.interval(
            "ror_adjusted", math.exp(fit.params["exposed"]), adjusted_low, adjusted_high, digits=3
        )

    em.value("cohort.n_reports", len(rows))
    em.value("cohort.n_drug_reports", a + b)
    em.value("cohort.period_start", years[0], display=str(years[0]))
    em.value("cohort.period_end", years[-1], display=str(years[-1]))
    em.value("cohort.n_years", years[-1] - years[0] + 1)

    em.value("case.n_cases", a)
    em.value("case.n_serious", serious)
    em.value("case.pct_serious", 100 * serious / a, digits=1, unit="%")

    # One call, so the three keys are one declared interval rather than three unrelated
    # numbers. It checks that the bounds bracket the estimate, and records which end each
    # bound is - which is what lets G2 refuse an interval quoted backwards in prose.
    em.interval("ror", ror, low, high, digits=2)

    # A second interval on the same estimate is named by its level, and reuses ror.point
    # rather than publishing the estimate twice. Writes ror.ci90_low and ror.ci90_high;
    # each level is checked against the estimate and never against the other, because a
    # 90% interval nested inside a 95% one is correct rather than a contradiction.
    em.interval("ror", low=low90, high=high90, level="90%", digits=2)

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
            ["example-drug", a, b],
            ["All other drugs", c, d],
        ],
        caption="Contingency table underlying the reporting odds ratio.",
    )
    em.table(
        "baseline",
        columns=["Characteristic", "example-drug", "All other drugs"],
        align=["left", "right", "right"],
        rows=[
            ["Reports", len(drug), len(other)],
            ["Hepatic injury", a, c],
            *[
                [
                    f"Age {group}",
                    _pct(em, drug, "age_group", group),
                    _pct(em, other, "age_group", group),
                ]
                for group in ("18-44", "45-64", "65-74", "75+")
            ],
            ["Female", _pct(em, drug, "sex", "F"), _pct(em, other, "sex", "F")],
            ["Serious", _pct(em, drug, "serious", "Y"), _pct(em, other, "serious", "Y")],
        ],
        caption="Reports by drug group. Values are n (%) unless stated.",
    )

    # The code lists the analysis selected on, published as RECORD 6.1 requires and as
    # READUS-PV expects for a case definition. Handed over as lists rather than as a typed
    # string: the emitter joins them, so the printed table is its output and the same
    # definition is available to the code that filtered on it. These are the terms this
    # synthetic generator uses; a real study would list a Standardised MedDRA Query or an
    # explicit preferred-term list here, and that list *is* the case definition.
    em.code_list(
        "outcome_codes",
        [
            {
                "concept": "Hepatic injury",
                "system": "Event term (synthetic)",
                "codes": ["hepatic injury"],
            },
            {
                "concept": "Example drug",
                "system": "Drug name (synthetic)",
                "codes": ["example-drug"],
            },
        ],
        caption="Terms used to identify the exposure and the outcome.",
    )

    path = em.write()
    print(f"wrote {path}")


if __name__ == "__main__":
    main()

