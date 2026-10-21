"""G12 and G4: the record of the datasets considered, and what the paper says of the one chosen.

`design/data_sources.yaml` is held to its schema, and each access claim to its source: a
quote to the page it was read from, stored as text beside the record, or a person's name and
the day they said it. A field of a candidate's access or terms with no claim behind it is
said, and so is a chosen source whose route is not known, since the point of the record is
that the choice is made with it known (G12, warnings).

What the record says of the chosen sources is held to the rest of the paper:

* a minimum cell count, or a ban on sending the data anywhere the custodian has not agreed
  to, that `paper.yaml`'s `custodian:` does not declare (`custodian-rule-undeclared`): G2's
  small-count check and `review --run`'s refusal read only `paper.yaml`, so a rule the
  record holds and paper.yaml lacks is a check that never runs. A warning while the paper is
  written, a failure from internal review, when `count-below-minimum` binds (Basile,
  2026-10-21);
* the plan's Population or Data source section naming none of a chosen source's names
  (`plan-source-unnamed`, G12, a warning);
* the Data availability statement saying a chosen source is had on request when anyone may
  download it, or publicly available when somebody decides who has it
  (`data-statement-route-differs`), or naming none of the chosen sources
  (`data-statement-source-unnamed`): G4, warnings.
"""

from __future__ import annotations

import dataclasses
import re
from typing import Any

from manuscript_guard.contracts._schema import ContractError, read_structured, read_text, validate
from manuscript_guard.contracts.project import Project
from manuscript_guard.data_sources import (
    ACCESS_FIELDS,
    PAGES,
    RECORD,
    TERMS_FIELDS,
    candidates_by_id,
    chosen,
    named,
    page_path,
    record_path,
    route,
    route_differs,
)
from manuscript_guard.findings import FAIL, INFO, WARN, Finding, Report
from manuscript_guard.gates.custodian import minimum_cell_count
from manuscript_guard.gates.journal_quotes import _on_page
from manuscript_guard.gates.literature import _MODEL_NAME
from manuscript_guard.policy import INTERNAL_REVIEW, stage_index

GATE = "G12"
STATEMENT_GATE = "G4"


def read_record(project: Project) -> tuple[dict[str, Any] | None, Report]:
    """The record, where there is one that holds to its schema, and what is wrong with it
    otherwise: None and no finding where there is no record."""
    path = record_path(project)
    if not path.is_file():
        return None, Report()
    try:
        document = read_structured(path)
    except ContractError as exc:
        return None, Report((_warn("data-sources-schema", str(exc), path),))
    checked = validate(document, "data-sources", path, gate=GATE, code="data-sources-schema")
    if not checked.ok:
        return None, Report(tuple(dataclasses.replace(f, severity=WARN) for f in checked.findings))
    return document, Report()


def check_data_sources(project: Project, stage: str) -> Report:
    """G12: the record whole and sourced, and paper.yaml and the plan held to its choice."""
    document, report = read_record(project)
    if document is None:
        return report
    path = record_path(project)
    report = report.merge(_ids(document, path))
    report = report.merge(_people(document, path))
    for candidate in document["candidates"]:
        report = report.merge(_unsourced(candidate, path))
        report = report.merge(_quotes(project, candidate, path))
    picked = chosen(document)
    if not document.get("decision"):
        return report.merge(
            Report(
                (
                    Finding(
                        GATE,
                        "data-source-undecided",
                        "no dataset is chosen in the record, so paper.yaml, the plan and the "
                        "Data availability statement are not held to it",
                        severity=INFO,
                        path=path,
                        hint="once the author has chosen, write `decision:` with who chose and "
                        "when",
                    ),
                )
            )
        )
    for source in picked:
        if route(source) is None:
            report = report.with_findings(
                _warn(
                    "data-source-route-unknown",
                    f"{source['name']} is chosen, and the record does not say how it is reached",
                    path,
                    "find its access page, and write `access: {route: ...}` with the claim and "
                    "quote that say it",
                )
            )
    report = report.merge(_custodian(project, picked, path, stage))
    return report.merge(_plan(project, picked))


def check_statement_sources(project: Project) -> Report:
    """G4: the Data availability statement names each chosen source, and says it is reached
    as the record says."""
    from manuscript_guard.gates.data_statement import cited_in, statement_text
    from manuscript_guard.gates.journal import _profile, main_text

    document, _report = read_record(project)
    picked = chosen(document) if document else []
    if not picked:
        return Report()
    policy = ((_profile(project) or {}).get("data_availability")) or {}
    heading = policy.get("heading") if isinstance(policy, dict) else None
    statement = statement_text(main_text(project), heading)
    if statement is None:
        return Report()  # the required statement's own check says it is missing
    printed = f"{statement}\n{cited_in(statement, project)}"
    path = project.path("manuscript") / "main.md"
    findings = [
        Finding(
            STATEMENT_GATE,
            "data-statement-source-unnamed",
            f"the Data availability statement does not name {source['name']}, which the "
            f"record of data sources says the data come from",
            severity=WARN,
            path=path,
            hint="name the source and its custodian, and how it is reached, by one of the "
            "names or identifiers its entry in design/data_sources.yaml gives",
        )
        for source in picked
        if not named(printed, source)
    ]
    by_id = {source["id"]: source for source in picked}
    for source_id, said in route_differs(statement, picked):
        source = by_id[source_id]
        findings.append(_route_finding(source, said, path, statement))
    return Report(tuple(findings))


#: What the statement said, as a finding says it, and what to do about it.
_SAID = {
    "on request": (
        "had on request",
        "say where anyone may download it, with its identifier; if the sentence is about "
        "something else, the analysis files or the code, say what it is about",
    ),
    "publicly": (
        "publicly available",
        "say who decides access and how it is asked for; if the sentence is about other data, "
        "a summary or the analysis files, say what it is about",
    ),
}


def _route_finding(source: dict[str, Any], said: str, path, statement: str) -> Finding:
    words, hint = _SAID[said]
    return Finding(
        STATEMENT_GATE,
        "data-statement-route-differs",
        f"the Data availability statement says the data are {words}, and {source['name']} is "
        f"reached by {route(source)}, as its record says",
        severity=WARN,
        path=path,
        context=" ".join(statement.split())[:160],
        hint=hint,
    )


def _ids(document: dict[str, Any], path) -> Report:
    """A candidate id given twice, and an id named where no candidate has it."""
    seen: dict[str, int] = {}
    for candidate in document["candidates"]:
        seen[candidate["id"]] = seen.get(candidate["id"], 0) + 1
    findings = [
        _warn(
            "data-source-id-repeated",
            f"{count} candidates have the id {source_id!r}; the decision, the ranking and the "
            "history name a source by its id",
            path,
            "give each candidate an id of its own",
        )
        for source_id, count in seen.items()
        if count > 1
    ]
    decision = document.get("decision") or {}
    named_ids = [entry["source"] for entry in document.get("ranking") or []]
    named_ids += list(decision.get("chosen") or [])
    named_ids += [entry["source"] for entry in decision.get("rejected") or []]
    named_ids += [entry["source"] for entry in document.get("history") or []]
    known = candidates_by_id(document)
    findings += [
        _warn(
            "data-source-unknown",
            f"the record names {source_id!r}, which is none of its candidates",
            path,
            "add the source to `candidates:` with what is known of it, or correct the id",
        )
        for source_id in dict.fromkeys(named_ids)
        if source_id not in known
    ]
    return Report(tuple(findings))


def _people(document: dict[str, Any], path) -> Report:
    """Who stated the question, who chose, who said a claim and who sent a message: a person,
    never a model. The list of names is a guard against the careless case, as G7's is."""
    said: list[tuple[str, str]] = [("question.stated_by", document["question"]["stated_by"])]
    decision = document.get("decision") or {}
    if decision:
        said.append(("decision.decided_by", decision["decided_by"]))
    for candidate in document["candidates"]:
        source = candidate["id"]
        said += [(f"{source}: a claim's stated_by", claim["stated_by"])
                 for claim in candidate.get("claims") or [] if "stated_by" in claim]  # fmt: skip
        said += [(f"{source}: a message's sent_by", sent["sent_by"])
                 for sent in candidate.get("messages") or [] if "sent_by" in sent]  # fmt: skip
    return Report(
        tuple(
            _warn(
                "data-source-not-a-person",
                f"{where} is {who!r}, which names a model or a program",
                path,
                "the author states the question, chooses the data and sends any message; an "
                "agent proposes and drafts. Write the person's name",
            )
            for where, who in said
            if _MODEL_NAME.search(who)
        )
    )


def _about(claim: dict[str, Any]) -> list[str]:
    about = claim["about"]
    return [about] if isinstance(about, str) else list(about)


def _unsourced(candidate: dict[str, Any], path) -> Report:
    """The fields of a candidate's access and terms that no claim names as its subject."""
    backed = {field for claim in candidate.get("claims") or [] for field in _about(claim)}
    access, terms = candidate.get("access") or {}, candidate.get("terms") or {}
    stated = [f for f in ACCESS_FIELDS if f in access] + [f for f in TERMS_FIELDS if f in terms]
    missing = [field for field in stated if field not in backed]
    if not missing:
        return Report()
    return Report(
        (
            _warn(
                "data-source-unsourced",
                f"{candidate['name']}: no claim backs {', '.join(missing)}",
                path,
                "add a claim about each, with the page's words, the page stored as text in "
                f"{PAGES.as_posix()}/, its URL and the date; or, said in a call or a letter, "
                "who said it and when",
            ),
        )
    )


def _quotes(project: Project, candidate: dict[str, Any], path) -> Report:
    """Each quote on the page it was read from, the page stored in the project."""
    findings: list[Finding] = []
    pages: dict[str, str | None] = {}
    for claim in candidate.get("claims") or []:
        page = claim.get("page")
        if page is None:
            continue
        if page not in pages:
            pages[page] = _page_text(project, page, candidate, path, findings)
        text = pages[page]
        if text is not None and not _on_page(text, claim["quote"]):
            shown = " ".join(claim["quote"].split())
            findings.append(
                _warn(
                    "data-source-quote-not-on-page",
                    f"{candidate['name']}: the quote for {', '.join(_about(claim))} is not on "
                    f'{page}: "{shown[:120]}"',
                    path,
                    "copy the words as the page writes them; if the page changed, store it again "
                    "and read the claim against it",
                )
            )
    return Report(tuple(findings))


def _page_text(project: Project, page: str, candidate, path, findings: list[Finding]) -> str | None:
    stored = page_path(project, page)
    try:
        return read_text(stored)
    except FileNotFoundError:
        reason = "is not stored"
    except (ContractError, OSError) as exc:
        reason = f"cannot be read ({exc})"
    findings.append(
        _warn(
            "data-source-page-not-stored",
            f"{candidate['name']}: the page {(PAGES / page).as_posix()} {reason}, so its "
            "quotes are not checked",
            path,
            "save the page you read, as text, under that name",
        )
    )
    return None


def _custodian(project: Project, picked: list[dict[str, Any]], path, stage: str) -> Report:
    """The custodian rules the record holds for the chosen sources, against paper.yaml's."""
    severity = FAIL if stage_index(stage) >= stage_index(INTERNAL_REVIEW) else WARN
    findings: list[Finding] = []
    minimums = [(s["terms"]["minimum_cell_count"], s) for s in picked
                if "minimum_cell_count" in (s.get("terms") or {})]  # fmt: skip
    declared = minimum_cell_count(project)
    if minimums:
        least, source = max(minimums, key=lambda item: item[0])
        if declared is None or declared < least:
            has = "declares none" if declared is None else f"declares {declared}"
            findings.append(
                Finding(
                    GATE,
                    "custodian-rule-undeclared",
                    f"{source['name']} allows no count below {least} to be published, as its "
                    f"record says, and paper.yaml's custodian {has}",
                    severity=severity,
                    path=project.root / "paper.yaml",
                    hint=f"write `custodian: {{minimum_cell_count: {least}}}` in paper.yaml, so "
                    "that G2 fails a smaller count the manuscript binds",
                )
            )
    restricting = [s for s in picked if (s.get("terms") or {}).get("restricts_sending") is True]
    custodian = (project.paper or {}).get("custodian")
    sending = isinstance(custodian, dict) and custodian.get("restricts_sending") is True
    if restricting and not sending:
        findings.append(
            Finding(
                GATE,
                "custodian-rule-undeclared",
                f"{restricting[0]['name']} forbids sending its data or results drawn from them "
                "where the custodian has not agreed, as its record says, and paper.yaml's "
                "custodian does not say so",
                severity=severity,
                path=project.root / "paper.yaml",
                hint="write `custodian: {restricts_sending: true}` in paper.yaml: `review --run` "
                "then sends to a provider only once the data custodian named in authors.yaml "
                "has authorised it",
            )
        )
    return Report(tuple(findings))


def _plan(project: Project, picked: list[dict[str, Any]]) -> Report:
    """The plan's Population or Data source section names each chosen source."""
    from manuscript_guard.gates.design import REQUIRED, _plan_sections, _read_plan, plan_path
    from manuscript_guard.text.sections import subsections

    plan = plan_path(project)
    if not plan.is_file() or not picked:
        return Report()
    text, _unreadable = _read_plan(plan)
    pattern = dict((name, rule) for name, rule, _purpose in REQUIRED)["population"]
    sections = _plan_sections(text)
    said = [
        "\n".join(part.body for part in subsections(sections, index))
        for index, section in enumerate(sections)
        if re.search(pattern, section.title)
    ]
    if not said:
        return Report()  # plan-section-missing says so
    return Report(
        tuple(
            Finding(
                GATE,
                "plan-source-unnamed",
                f"the plan's Population or Data source section does not name {source['name']}, "
                "which the record of data sources chose",
                severity=WARN,
                path=plan,
                hint="say in the plan which source, which version or extraction and which "
                "period the analysis uses, by one of the names its entry in "
                f"{RECORD.as_posix()} gives",
            )
            for source in picked
            if not any(named(body, source) for body in said)
        )
    )


def _warn(code: str, message: str, path, hint: str | None = None) -> Finding:
    return Finding(GATE, code, message, severity=WARN, path=path, hint=hint)


__all__ = ["check_data_sources", "check_statement_sources", "read_record"]
