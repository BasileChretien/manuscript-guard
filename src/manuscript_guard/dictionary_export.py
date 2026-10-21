"""The data dictionary, written out for whoever builds the form.

Three renderings of `design/data_dictionary.yaml`, each a function of the file alone:

- REDCap's data dictionary, the CSV its Online Designer imports: the eighteen columns of its
  template, in its order, each field on its instrument (`form`), its codes as REDCap writes
  choices (`1, Male | 2, Female`), its range as the validation's minimum and maximum, its
  condition as branching logic, its definition as the field annotation. A derived variable
  is left out: the analysis computes it, and REDCap's calculated fields are a language of
  their own. A name REDCap cannot take is refused, not changed: a renamed field would no
  longer be the variable the plan and the data checks name.
- A plain CSV, one row per variable and one column per key of an entry, for a data manager
  with any other system.
- An outline of the form, in Markdown: each form in order, each question with its responses,
  the skips, and what is derived and not asked.

Nothing here decides anything. The dictionary is the record; these are copies of it in other
shapes, written again whenever it changes.
"""

from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass
from datetime import date, datetime, time

from manuscript_guard.contracts.dictionary import CODED, Code, Dictionary, Variable

#: The columns of REDCap's data dictionary, as its template names them, in its order.
REDCAP_COLUMNS = (
    "Variable / Field Name",
    "Form Name",
    "Section Header",
    "Field Type",
    "Field Label",
    "Choices, Calculations, OR Slider Labels",
    "Field Note",
    "Text Validation Type OR Show Slider Number",
    "Text Validation Min",
    "Text Validation Max",
    "Identifier?",
    "Branching Logic (Show field only if...)",
    "Required Field?",
    "Custom Alignment",
    "Question Number (surveys only)",
    "Matrix Group Name",
    "Matrix Ranking?",
    "Field Annotation",
)
#: What REDCap takes as a field's or an instrument's name.
REDCAP_NAME = re.compile(r"[a-z][a-z0-9_]*")
#: The instrument a variable with no form is put on.
DEFAULT_FORM = "data"
#: Each type that is not coded, as a REDCap text field's validation.
_VALIDATION = {
    "continuous": "number",
    "count": "integer",
    "date": "date_ymd",
    "datetime": "datetime_ymd",
    "time": "time",
    "text": "",
    "identifier": "",
}

#: How REDCap's validation writes a bound of each type that is a time.
_TIMES = {
    "date": (date.fromisoformat, "%Y-%m-%d"),
    "datetime": (datetime.fromisoformat, "%Y-%m-%d %H:%M"),
    "time": (time.fromisoformat, "%H:%M"),
}
#: What may not stand in a code or a label of REDCap's choices, `1, Male | 2, Female`, or
#: in a code between the quotation marks of its branching logic.
_NOT_IN_A_CODE = re.compile(r"[,|'\"\s]")
_NOT_IN_A_LABEL = re.compile(r"[|\n\r]")

#: The columns of the plain CSV.
CSV_COLUMNS = (
    "name", "label", "definition", "type", "question", "unit", "values", "missing", "min",
    "max", "required", "applies_if", "form", "timing", "recorded_by", "source", "dataset",
    "derived_from", "derivation", "instrument", "item", "standard", "reporting", "reason",
    "pattern", "within_study_period",
)  # fmt: skip


class ExportRefused(Exception):
    """The dictionary cannot be written in this shape as it stands; the message says why."""


@dataclass(frozen=True)
class Written:
    """What an export wrote, and what it left out and why."""

    text: str
    left_out: tuple[str, ...] = ()


def _codes(codes: tuple[Code, ...]) -> str:
    return " | ".join(f"{code.code}, {code.label}" for code in codes)


def _form(variable: Variable) -> str:
    return variable.form or DEFAULT_FORM


def _bound(variable: Variable, bound: object) -> str:
    """A range bound as REDCap's validation reads it: a date as YYYY-MM-DD, a datetime as
    YYYY-MM-DD HH:MM, a time as HH:MM, each read first as the loader read it; a number with
    every digit it has (round 1: `:g` kept six)."""
    if bound is None:
        return ""
    if variable.type in _TIMES:
        text = str(bound)
        read = _TIMES[variable.type][0](text[:-1] + "+00:00" if text.endswith("Z") else text)
        return read.strftime(_TIMES[variable.type][1])
    if isinstance(bound, float):
        return str(int(bound)) if bound.is_integer() else repr(bound)
    return str(bound)


def _branching(variable: Variable, dictionary: Dictionary) -> str:
    condition = variable.applies_if
    if condition is None:
        return ""
    return " or ".join(f"[{condition.variable}] = '{code}'" for code in condition.codes)


def _redcap_row(variable: Variable, dictionary: Dictionary) -> dict[str, str]:
    coded = variable.type in CODED
    note = [f"unit: {variable.unit}"] if variable.unit else []
    if variable.missing:
        note.append("missing: " + "; ".join(f"{c.code} {c.label}" for c in variable.missing))
    row = dict.fromkeys(REDCAP_COLUMNS, "")
    row.update({
        "Variable / Field Name": variable.name,
        "Form Name": _form(variable),
        "Field Type": "radio" if coded else "text",
        "Field Label": variable.question or variable.label,
        "Choices, Calculations, OR Slider Labels": _codes(variable.values + variable.missing)
        if coded else "",
        "Field Note": "; ".join(note),
        "Text Validation Type OR Show Slider Number": "" if coded else _VALIDATION[variable.type],
        "Text Validation Min": _bound(variable, variable.minimum),
        "Text Validation Max": _bound(variable, variable.maximum),
        "Branching Logic (Show field only if...)": _branching(variable, dictionary),
        "Required Field?": "y" if variable.required else "",
        "Field Annotation": variable.definition,
    })  # fmt: skip
    return row


def redcap(dictionary: Dictionary) -> Written:
    """REDCap's data dictionary for the variables the form collects.

    The record's identifier comes first, as REDCap takes the first field of the first
    instrument for it: the first `identifier` variable, moved to the front of its form, and
    its form to the front of the forms. Refused where there is none, where a name or a form
    is one REDCap cannot take, or where a coded variable has no codes yet."""
    collected = [v for v in dictionary.variables if not v.derived]
    identifiers = [v for v in collected if v.type == "identifier"]
    if not identifiers:
        raise ExportRefused("REDCap takes the first field as each record's identifier, and no "
                            "variable the form collects is of type identifier")  # fmt: skip
    wrong = [v.name for v in collected if not REDCAP_NAME.fullmatch(v.name)]
    wrong += [f"form {f}" for f in dict.fromkeys(_form(v) for v in collected)
              if not REDCAP_NAME.fullmatch(f)]  # fmt: skip
    if wrong:
        raise ExportRefused("REDCap takes lower-case letters, digits and underscores from a "
                            f"letter, and not {', '.join(wrong)}")  # fmt: skip
    undecided = [v.name for v in collected if v.type in CODED and not v.values]
    if undecided:
        raise ExportRefused(f"{', '.join(undecided)} has no codes yet, and REDCap needs the "
                            "choices of each coded field")  # fmt: skip
    _refuse_choices(collected)
    _refuse_conditions(collected)
    first = identifiers[0]
    forms = list(dict.fromkeys([_form(first)] + [f.id for f in dictionary.forms]
                               + [_form(v) for v in collected]))  # fmt: skip
    ordered = [first] + [
        v for form in forms for v in collected if _form(v) == form and v is not first
    ]
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=REDCAP_COLUMNS, lineterminator="\r\n")
    writer.writeheader()
    for variable in ordered:
        writer.writerow(_redcap_row(variable, dictionary))
    left_out = tuple(f"{v.name}: derived, computed by the analysis"
                     for v in dictionary.variables if v.derived)  # fmt: skip
    left_out += tuple(f"{v.name}: its pattern is not a REDCap validation"
                      for v in collected if v.pattern)  # fmt: skip
    return Written(out.getvalue(), left_out)


def _refuse_choices(collected: list[Variable]) -> None:
    """A code or a label that would not read back from REDCap's choices as it was written:
    `1, Weekly | monthly` is three choices to REDCap (round 1)."""
    for variable in (v for v in collected if v.type in CODED):
        for code in variable.values + variable.missing:
            if _NOT_IN_A_CODE.search(code.code) or _NOT_IN_A_LABEL.search(code.label):
                shown = code.code if _NOT_IN_A_CODE.search(code.code) else code.label
                raise ExportRefused(f"{variable.name}: REDCap reads its choices as `code, "
                                    f"label | code, label`, and {shown!r} would not read "
                                    "back as written")  # fmt: skip


def _refuse_conditions(collected: list[Variable]) -> None:
    """A condition on a variable the file leaves out, which its branching logic would name
    and REDCap would not find."""
    names = {v.name for v in collected}
    for variable in collected:
        if variable.applies_if is not None and variable.applies_if.variable not in names:
            raise ExportRefused(f"{variable.name} is asked under "
                                f"{variable.applies_if.variable}, which is derived and not "
                                "in REDCap's file")  # fmt: skip


def _row(variable: Variable) -> dict[str, str]:
    condition = variable.applies_if
    standard = variable.standard
    return {
        "name": variable.name,
        "label": variable.label,
        "definition": variable.definition,
        "type": variable.type,
        "question": variable.question or "",
        "unit": variable.unit or "",
        "values": _codes(variable.values),
        "missing": _codes(variable.missing),
        "min": "" if variable.minimum is None else str(variable.minimum),
        "max": "" if variable.maximum is None else str(variable.maximum),
        "required": "yes" if variable.required else "",
        "applies_if": f"{condition.variable} in {', '.join(condition.codes)}" if condition
        else "",
        "form": variable.form or "",
        "timing": variable.timing or "",
        "recorded_by": variable.recorded_by or "",
        "source": variable.source or "",
        "dataset": variable.dataset or "",
        "derived_from": ", ".join(variable.derived_from),
        "derivation": variable.derivation or "",
        "instrument": variable.instrument or "",
        "item": variable.item or "",
        "standard": " ".join(part for part in (standard.system, standard.version,
                             standard.level, standard.code, standard.term) if part)
        if standard else "",
        "reporting": "; ".join(f"{name} {', '.join(items)}"
                               for name, items in variable.reporting),
        "reason": variable.reason or "",
        "pattern": variable.pattern or "",
        "within_study_period": "yes" if variable.within_study_period else "",
    }  # fmt: skip


def plain_csv(dictionary: Dictionary) -> Written:
    """One row per variable, in the dictionary's order, and one column per key of an entry."""
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=CSV_COLUMNS, lineterminator="\r\n")
    writer.writeheader()
    for variable in dictionary.variables:
        writer.writerow(_row(variable))
    return Written(out.getvalue())


def _asked(variable: Variable, dictionary: Dictionary) -> list[str]:
    """The lines under one question of the outline."""
    lines = [f"   {variable.definition}"]
    if variable.instrument:
        instrument = next(i for i in dictionary.instruments if i.id == variable.instrument)
        item = f"Item {variable.item} of " if variable.item else "From "
        lines.append(f"   *{item}{instrument.name}: the wording and "
                     "the responses are the licensed instrument's.*")  # fmt: skip
    for code in variable.values:
        lines.append(f"   - [ ] {code.label} ({code.code})")
    for code in variable.missing:
        lines.append(f"   - [ ] {code.label} ({code.code}, missing)")
    if variable.type not in CODED:
        shown = variable.type + (f", {variable.unit}" if variable.unit else "")
        low, high = variable.minimum, variable.maximum
        span = (f", {low} to {high}" if low is not None and high is not None else
                f", from {low}" if low is not None else
                f", up to {high}" if high is not None else "")  # fmt: skip
        lines.append(f"   ____ ({shown}{span})")
    condition = variable.applies_if
    if condition is not None:
        other = dictionary.variable(condition.variable)
        said = [c.label for c in other.values + other.missing if c.code in condition.codes]
        lines.append(f"   *Asked only where {other.label} is "
                     f"{' or '.join(said or condition.codes)}.*")  # fmt: skip
    if variable.required:
        lines.append("   *Required.*")
    return lines


def outline(dictionary: Dictionary) -> Written:
    """The form as Markdown: each form in order with its questions, then what is derived."""
    collected = [v for v in dictionary.variables if not v.derived]
    lines = [f"# {dictionary.title or 'Data collection form'}", ""]
    forms = [(f.id, f.label, f.timing, f.recorded_by) for f in dictionary.forms]
    if any(v.form is None for v in collected):
        forms.append((None, "Other variables", None, None))
    number = 0
    for form_id, label, timing, recorded_by in forms:
        asked = [v for v in collected if v.form == form_id]
        if not asked:
            continue
        lines += [f"## {label}", ""]
        said = [part for part in (timing and f"When: {timing}.",
                                  recorded_by and f"Recorded by: {recorded_by}.") if part]
        lines += [" ".join(said), ""] if said else []
        for variable in asked:
            number += 1
            lines.append(f"{number}. **{variable.question or variable.label}** "
                         f"(`{variable.name}`)")  # fmt: skip
            lines += _asked(variable, dictionary) + [""]
    derived = [v for v in dictionary.variables if v.derived]
    if derived:
        lines += ["## Derived, not asked", ""]
        for variable in derived:
            inputs = ", ".join(f"`{name}`" for name in variable.derived_from)
            lines.append(f"- **{variable.label}** (`{variable.name}`): "
                         f"{variable.derivation or 'derivation not given'}; from {inputs}.")
        lines.append("")
    return Written("\n".join(lines).rstrip() + "\n")


__all__ = [
    "CSV_COLUMNS",
    "DEFAULT_FORM",
    "REDCAP_COLUMNS",
    "REDCAP_NAME",
    "ExportRefused",
    "Written",
    "outline",
    "plain_csv",
    "redcap",
]
