"""The SDs of a table's means, held to the means and their column's n (`stats/granularity.py`).

Two of `audit`'s readings of the rows an auditor names:

* **`--whole-numbers`**: a mean of whole numbers printed with its SD, "3.47 (1.20)", has its
  SD held to the mean and n by GRIMMER, wherever GRIM leaves the mean possible or cannot
  tell. A mean GRIM finds impossible is said once, as a mean: its SD is not held to it.
  The SD that cannot be is `sd-not-possible`, a warning `--strict` does not count, as an
  impossible mean is.
* **`--binary`**: a row of numbers each 0 or 1, printed as a mean or a proportion with its
  SD, "0.19 (0.35)", has the two held to each other and to n by DEBIT:
  `binary-not-possible`, the same kind of warning. A label under which no such cell was
  read is said, as `--whole-numbers` says its own.

A spread the row's label, the header over its column or the header's first cell names as no
SD, "mean (SE)", "median (IQR)", is not held to anything, and counted as passed over with
its reason; so is a --binary cell that is no proportion, "85 (52.1)", or under a label or a
header that names a percentage.
"""

from __future__ import annotations

from pathlib import Path

from manuscript_guard.stats.granularity import (
    Mean,
    binary_described,
    binary_possible,
    names,
    possible,
    sd_described,
    sd_possible,
    table_binary,
)
from manuscript_guard.text.tables import Table

#: The findings' codes.
SD_CODE = "sd-not-possible"
BINARY_CODE = "binary-not-possible"
UNFOUND_CODE = "binary-unfound"


#: Why a spread is held to nothing, where it is for no reason the table gives.
_N_UNDER_ONE = "its column's n is under 1"
_TOO_MANY_TOTALS = "more than 100,000 totals would be tried"
_TOO_MANY_ONES = "more than 100,000 counts of ones would be tried"


def held_sd(mean: Mean) -> bool | None:
    """Whether the SD printed with a mean of whole numbers can go with it and its n
    (GRIMMER); None where it is held to nothing (`sd_held`)."""
    return sd_held(mean)[0]


def sd_held(mean: Mean) -> tuple[bool | None, str | None]:
    """GRIMMER's verdict on the SD printed with a mean of whole numbers, and why it is held
    to nothing where it is: a label or a header names it as no SD, its n is under 1, or too
    many totals would be tried. No spread printed, or a mean GRIM rules out, which is said
    as a mean, is held to nothing for no reason to give."""
    if mean.spread is None or possible(mean.mean, mean.n) is False:
        return None, None
    if mean.not_an_sd is not None:
        return None, mean.not_an_sd
    if mean.n < 1:
        return None, _N_UNDER_ONE
    verdict = sd_possible(mean.mean, mean.spread, mean.n)
    return verdict, _TOO_MANY_TOTALS if verdict is None else None


def held_binary(mean: Mean) -> bool | None:
    """Whether a mean and the SD printed with it can be those of n numbers each 0 or 1
    (DEBIT); None where they are held to nothing (`binary_held`)."""
    return binary_held(mean)[0]


def binary_held(mean: Mean) -> tuple[bool | None, str | None]:
    """DEBIT's verdict on a mean and the SD printed with it, and why they are held to
    nothing where they are: a label or a header names the spread as no SD; the mean is no
    proportion, a count and its share "85 (52.1)", a percentage and its SD "19.0 (39.2)",
    or under a label or a header that names a percentage (round 1 of #665); its n is under
    1; or too many counts of ones would be tried."""
    if mean.spread is None:
        return None, None
    why = mean.not_an_sd or mean.not_a_proportion or (_N_UNDER_ONE if mean.n < 1 else None)
    if why is not None:
        return None, why
    verdict = binary_possible(mean.mean, mean.spread, mean.n)
    return verdict, _TOO_MANY_ONES if verdict is None else None


def whole_number_sd(report, path: Path, mean: Mean) -> None:
    """A mean of a row --whole-numbers named, which GRIM leaves possible or cannot tell:
    its SD, where it prints one, held to it and its n."""
    from manuscript_guard.audit import Disagreement

    verdict, why = sd_held(mean)
    if why is not None:
        report.sds_passed_over.append(why)
    if verdict is None:
        return
    report.sds_read += 1
    if verdict is False:
        said = sd_described(mean.mean, mean.spread, mean.n) + _uncertain(mean)
        report.sds_off.append(Disagreement(path, mean.line, said, mean.context))


def binary_means(report, path: Path, tables: list[Table]) -> None:
    """Each mean printed with its SD in a row --binary named, the two held to each other and
    to its column's n. A label under which one is read is taken off the labels that read
    nothing."""
    from manuscript_guard.audit import Disagreement

    for table in tables:
        for mean in table_binary(table, report.binary):
            report.binary_unfound = [
                label for label in report.binary_unfound if not names(label, mean.label)
            ]
            verdict, why = binary_held(mean)
            if why is not None:
                report.binary_passed_over.append(why)
            if verdict is None:
                continue
            report.binary_read += 1
            if verdict is False:
                said = binary_described(mean.mean, mean.spread, mean.n) + _uncertain(mean)
                report.binary_off.append(Disagreement(path, mean.line, said, mean.context))


def _uncertain(mean: Mean) -> str:
    return f" (uncertain: {mean.uncertain})" if mean.uncertain else ""


# ------------------------------------------------------------------------------ the report


def items(report) -> list:
    """What the report says of the SDs, item by item (`auditing.report.items`)."""
    from manuscript_guard.auditing.report import ARITHMETIC, Item
    from manuscript_guard.findings import INFO, WARN

    return [
        *(Item(ARITHMETIC, "audit", SD_CODE, d.message, WARN, False, d.source, d.line, d.context)
          for d in report.sds_off),
        *(Item(ARITHMETIC, "audit", BINARY_CODE, d.message, WARN, False, d.source, d.line,
               d.context) for d in report.binary_off),
        *(Item(ARITHMETIC, "audit", UNFOUND_CODE, f"--binary {label!r}: no mean with an SD "
               "was read in a row whose label holds it", INFO, False)
          for label in report.binary_unfound),
    ]  # fmt: skip


def lines(report, show) -> list[str]:
    """The text's lines on the SDs, under Arithmetic; none where nothing was named that
    prints one."""
    out: list[str] = []
    if report.sds_read or report.sds_off or report.sds_passed_over:
        out.append(
            f"SDs of means of whole numbers (GRIMMER): {report.sds_read} held to their mean "
            f"and n, {len(report.sds_off)} of which cannot go with them (not counted by --strict)."
        )
        out += _listed(report.sds_off, show)
        out += _passed_over(report.sds_passed_over)
    if report.binary:
        out += [""] if out else []
        out.append(
            f"Means and SDs of numbers each 0 or 1 (--binary, DEBIT): {report.binary_read} "
            f"read in the rows named, {len(report.binary_off)} of which cannot go together "
            "for their n (not counted by --strict)."
        )
        out += _listed(report.binary_off, show)
        out += [
            f"  --binary {label!r}: no mean with an SD was read in a row whose label holds it"
            for label in report.binary_unfound
        ]
        out += _passed_over(report.binary_passed_over)
    return out


def _passed_over(reasons: list[str]) -> list[str]:
    """How many spreads of the rows named were held to nothing, and why, each reason with
    how many it holds back."""
    if not reasons:
        return []
    counted = {why: reasons.count(why) for why in dict.fromkeys(reasons)}
    said = "; ".join(f"{why} ({count})" for why, count in counted.items())
    return [f"  {len(reasons)} spread{'' if len(reasons) == 1 else 's'} in these rows held to "
            f"nothing: {said}"]  # fmt: skip


def _listed(found: list, show) -> list[str]:
    by_paper: dict[Path, list] = {}
    for item in found:
        by_paper.setdefault(item.source, []).append(item)
    out = []
    for source, listed in by_paper.items():
        out.append(f"  {show(source)}")
        for item in listed:
            out.append(f"    {show.at(source, item.line)}: {item.message}")
            out.append(f"      {item.context}")
    return out
