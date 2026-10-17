"""G4: the journal shortlist is whole, and the journal chosen is one the registries know.

`journals/shortlist.yaml` is held to its schema, and the journals its ranking and decision
name are among those it considered. For the target journal, what `lookup --journals` heard
is read offline: a journal not currently indexed for MEDLINE, and an open-access journal
DOAJ does not list, are each a warning. A predatory journal is never in either, and a sound
one can be outside them: the author can say why in the shortlist, and the warning is then a
note that quotes them. All of it is a warning at most (decided 2026-10-15).
"""

from __future__ import annotations

import dataclasses
from typing import Any

from manuscript_guard.contracts._schema import ContractError, read_structured, validate
from manuscript_guard.contracts.project import Project
from manuscript_guard.findings import INFO, WARN, Finding, Report
from manuscript_guard.shortlist import read_record, shortlist_path

GATE = "G4"
FOUND, ABSENT = "found", "absent"
LOOK_UP = "run `manuscript-guard lookup --journals` to ask the NLM Catalog and DOAJ"


def _name(text: str) -> str:
    return " ".join(text.split()).casefold()


def check_shortlist(project: Project) -> Report:
    path = shortlist_path(project)
    if not path.is_file():
        return Report()
    try:
        document = read_structured(path)
    except ContractError as exc:
        return Report((Finding(GATE, "shortlist-schema", str(exc), severity=WARN, path=path),))
    checked = validate(document, "shortlist", path, gate=GATE, code="shortlist-schema")
    if not checked.ok:
        return Report(tuple(dataclasses.replace(f, severity=WARN) for f in checked.findings))
    report = _named_and_considered(document, path)
    candidate = _target(project, document)
    if candidate is not None:
        report = report.merge(_legitimacy(project, candidate, path))
    return report


def _named_and_considered(document: dict, path) -> Report:
    """A journal ranked or chosen that is not among the candidates: the record of why it was
    chosen is then not in the file."""
    considered = {_name(c["journal"]) for c in document["candidates"]}
    named = [r["journal"] for r in document.get("ranking") or []]
    if document.get("decision"):
        named.append(document["decision"]["journal"])
    findings = tuple(
        Finding(
            GATE,
            "shortlist-unknown-journal",
            f"the shortlist ranks or chooses {journal!r}, which is not among its candidates",
            severity=WARN,
            path=path,
            hint="add it to `candidates:` with the evidence for it, or correct the name",
        )
        for journal in dict.fromkeys(named)
        if _name(journal) not in considered
    )
    return Report(findings)


def _target(project: Project, document: dict) -> dict | None:
    """The candidate that is the target journal: the one whose `profile` paper.yaml names,
    or the one named as the profile names its journal; with no target journal, the one the
    decision chose."""
    from manuscript_guard.gates.journal import _profile

    candidates = document["candidates"]
    slug = project.target_journal
    if slug:
        for candidate in candidates:
            if candidate.get("profile") == slug:
                return candidate
        profile = _profile(project)
        name = _name(str(profile.get("name") or "")) if profile else ""
        return next((c for c in candidates if name and _name(c["journal"]) == name), None)
    chosen = (document.get("decision") or {}).get("journal")
    return next((c for c in candidates if chosen and _name(c["journal"]) == _name(chosen)), None)


def _legitimacy(project: Project, candidate: dict, path) -> Report:
    journal = candidate["journal"]
    issns = candidate.get("issn") or []
    if not issns:
        return _note(
            "journal-not-looked-up",
            f"the shortlist gives no ISSN for {journal}, so whether it is indexed for MEDLINE "
            "or listed in DOAJ is not known",
            f"add the journal's ISSNs to its entry, then {LOOK_UP}",
            path,
        )
    records = {issn: read_record(project, issn) for issn in issns}
    report = Report()
    missing = [i for i, r in records.items() if r is None]
    if missing:
        report = report.merge(
            _note(
                "journal-not-looked-up",
                f"no record of what the registries said of ISSN {', '.join(missing)} "
                f"({journal}), or one edited since",
                LOOK_UP,
                path,
            )
        )
    answers = {i: r["sources"] for i, r in records.items() if r is not None}
    late = [i for i, a in answers.items() if any(s["status"] not in (FOUND, ABSENT)
                                                 for s in a.values())]  # fmt: skip
    if late:
        report = report.merge(
            _note(
                "journal-not-looked-up",
                f"a registry did not answer for ISSN {', '.join(late)} ({journal}) when asked",
                LOOK_UP + " again",
                path,
            )
        )
    report = report.merge(
        _registry(
            "journal-not-in-medline",
            journal,
            [a.get("nlm_catalog") for a in answers.values()],
            indexed=lambda a: any(r["currently_indexed"] for r in a["records"]),
            missing=bool(missing),
            said="is not currently indexed for MEDLINE, as the NLM Catalog says",
            reason=candidate.get("outside_medline"),
            field="outside_medline",
            path=path,
        )
    )
    if candidate.get("open_access") is True:
        report = report.merge(
            _registry(
                "journal-not-in-doaj",
                journal,
                [a.get("doaj") for a in answers.values()],
                indexed=lambda a: True,
                missing=bool(missing),
                said="is open access and not listed in DOAJ",
                reason=candidate.get("outside_doaj"),
                field="outside_doaj",
                path=path,
            )
        )
    return report


def _registry(code, journal, answers: list[Any], *, indexed, missing, said, reason, field,
              path) -> Report:  # fmt: skip
    """One registry's answers for the journal's ISSNs: known to it on any ISSN, and nothing
    is said; unknown on every ISSN it answered for, with none left unasked or unanswered,
    and it is a warning, or a note where the author recorded why."""
    if any(a and a["status"] == FOUND and indexed(a) for a in answers):
        return Report()
    if missing or not answers or any(a is None or a["status"] not in (FOUND, ABSENT)
                                     for a in answers):  # fmt: skip
        return Report()
    message = f"{journal}, the journal chosen, {said}"
    if reason:
        return _note(code, f"{message}; the author recorded why: {reason}", "", path)
    return Report(
        (
            Finding(
                GATE,
                code,
                message,
                severity=WARN,
                path=path,
                hint="a predatory journal is never in it, and a sound one can be outside it: "
                "read the journal's standing before submitting, then choose another or say "
                f"why in the candidate's `{field}:`",
            ),
        )
    )


def _note(code: str, message: str, hint: str, path) -> Report:
    return Report((Finding(GATE, code, message, severity=INFO, path=path, hint=hint or None),))


__all__ = ["check_shortlist"]
