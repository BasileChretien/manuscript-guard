"""What ClinicalTrials.gov, OSF and ISRCTN say of one registration, in the record's terms.

Each is asked through its documented, keyless API, and only an answer in the shape that API
documents is `found` or `absent`; anything else is `unresolvable`, with the reason, and the
gate then says nothing is known of the registration rather than that it holds. The shapes
were read from each service's documentation and from live answers on 2026-10-21 (DESIGN.md,
"A registration is looked up once, and the paper is held to it"):

* ClinicalTrials.gov, API v2, `/studies/{nctId}` with `fields=protocolSection` and
  `markupFormat=legacy`, whose descriptions are plain text where the default is Markdown
  with its characters escaped. It answers for any NCT followed by up to eight digits,
  padding a short one (`NCT123` is NCT00000123), so the study it answers for is held to
  the one asked. A 404 with a plain-text body is a study it does not know; a 301 an alias.
* OSF, API v2, `/registrations/{id}/`: JSON:API, `date_registered`, the answers keyed by
  the template's question ids, which `/schemas/registrations/{id}/schema_blocks/` names;
  `original_response` and `latest_response`, which differ where the registration was
  updated, and `/schema_responses/{id}/` for what each said.
* ISRCTN, its query API, `/api/query/format/default?q=`, in XML: `allTrials@totalCount`,
  each `fullTrial/trial` with its `isrctn@dateAssigned`, `primaryOutcome` and
  `secondaryOutcome`, `recruitmentStart` and `primaryStudyDesign`. Its single-trial path
  answers an unknown number with HTTP 500 and a page, so it is not used.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

from manuscript_guard.lookup.http import Request
from manuscript_guard.lookup.sources import (
    ABSENT,
    FOUND,
    SHAPE,
    Ask,
    _ask,
    _json,
    _status_only,
    _text,
    unresolvable,
)
from manuscript_guard.safexml import UnsafeDocument, parse_xml

_DAY = re.compile(r"\d{4}-\d{2}-\d{2}")
_PARTIAL = re.compile(r"\d{4}(?:-\d{2}(?:-\d{2})?)?")
#: An OSF question whose answer is an outcome, by its label in the template.
_OUTCOME_LABEL = re.compile(r"(?i)\boutcome|\bendpoint|\bdependent variable")
#: OSF's schema blocks for one template come on one page this long.
_OSF_PAGE = "1000"


@dataclass(frozen=True)
class Services:
    """Where each registry is asked. The tests point every one at a loopback server."""

    clinicaltrials: str = "https://clinicaltrials.gov/api/v2/studies/"
    osf: str = "https://api.osf.io/v2/"
    isrctn: str = "https://www.isrctn.com/api/query/format/default"
    eu_pas: str = "https://catalogues.ema.europa.eu"


def _day(value: Any) -> str | None:
    """The day of an ISO date or date-time, "2020-04-27T13:32:42Z" being 2020-04-27."""
    if isinstance(value, str) and _DAY.match(value.strip()):
        return value.strip()[:10]
    return None


def _partial(value: Any) -> str | None:
    """A date as far as it goes: "2020-04-29", "2020-04" or "2020"."""
    if isinstance(value, str) and _PARTIAL.fullmatch(value.strip()):
        return value.strip()
    return None


def _kept(record: dict[str, Any]) -> dict[str, Any]:
    """The record without the fields the answer did not have, but for its sections, which
    a record that was found always holds, none included (round 1 of #390: a study with no
    outcome listed was written without them, and the schema refused the record)."""
    return {k: v for k, v in record.items() if k == "sections" or v not in (None, [], "", {})}


# ---------------------------------------------------------------------- ClinicalTrials.gov


def _outcomes(listed: Any, role: str, label: str) -> list[dict[str, Any]] | None:
    """One section for each outcome of a list, its measure, description and time frame in
    it; None where an entry has no measure."""
    out = []
    for number, item in enumerate(listed if isinstance(listed, list) else [], 1):
        measure = _text(item.get("measure")) if isinstance(item, dict) else None
        if measure is None:
            return None
        parts = [measure, _text(item.get("description")), _text(item.get("timeFrame"))]
        text = "\n".join(p for p in parts if p)
        out.append({"label": f"{label} {number}", "role": role, "text": text})
    return out


_DESIGN = {
    "INTERVENTIONAL": "interventional",
    "OBSERVATIONAL": "observational",
}


def _design_text(module: dict[str, Any]) -> str | None:
    info = module.get("designInfo") if isinstance(module.get("designInfo"), dict) else {}
    said = [
        f"{name}: {value}"
        for name, value in (
            ("allocation", info.get("allocation")),
            ("intervention model", info.get("interventionModel")),
            ("observational model", info.get("observationalModel")),
            ("time perspective", info.get("timePerspective")),
            ("primary purpose", info.get("primaryPurpose")),
        )
        if isinstance(value, str) and value.strip()
    ]
    phases = module.get("phases")
    if isinstance(phases, list) and phases:
        said.append("phases: " + ", ".join(str(p) for p in phases))
    return "; ".join(said) or None


def clinicaltrials(nct: str, ask: Ask, base: str) -> dict[str, Any]:
    """ClinicalTrials.gov's record of one study."""
    params = {"fields": "protocolSection", "format": "json", "markupFormat": "legacy"}
    answer = _ask(ask, Request(base + nct, params=params))
    if isinstance(answer, dict):
        return answer
    if answer.status == 404 and b"not found" in answer.body:
        return {"status": ABSENT, "why": f"ClinicalTrials.gov knows no study {nct}"}
    if answer.status == 301:
        moved = re.search(r"NCT\d{8}", answer.headers.get("Location", ""))
        to = f" for {moved.group(0)}" if moved else ""
        return unresolvable(
            f"ClinicalTrials.gov gives {nct} as an alias{to}: cite the study's own number"
        )
    said = _status_only(answer)
    if said:
        return said
    data = _json(answer)
    protocol = data.get("protocolSection") if isinstance(data, dict) else None
    if not isinstance(protocol, dict):
        return unresolvable(SHAPE)
    modules = {
        name: protocol.get(name) if isinstance(protocol.get(name), dict) else {}
        for name in (
            "identificationModule", "statusModule", "designModule", "outcomesModule",
            "conditionsModule", "armsInterventionsModule", "eligibilityModule",
        )
    }  # fmt: skip
    if modules["identificationModule"].get("nctId") != nct:
        return unresolvable(f"ClinicalTrials.gov answered for another study than {nct}")
    status = modules["statusModule"]
    registered = _day(status.get("studyFirstSubmitDate"))
    if registered is None:
        return unresolvable(SHAPE)
    start = status.get("startDateStruct") if isinstance(status.get("startDateStruct"), dict) else {}
    outcomes = modules["outcomesModule"]
    sections: list[dict[str, Any]] = []
    for key, role, label in (
        ("primaryOutcomes", "primary", "Primary outcome"),
        ("secondaryOutcomes", "secondary", "Secondary outcome"),
        ("otherOutcomes", "other", "Other pre-specified outcome"),
    ):
        listed = _outcomes(outcomes.get(key), role, label)
        if listed is None:
            return unresolvable(SHAPE)
        sections += listed
    conditions = modules["conditionsModule"].get("conditions")
    if isinstance(conditions, list) and conditions:
        sections.append({"label": "Conditions", "text": "; ".join(map(str, conditions))})
    interventions = modules["armsInterventionsModule"].get("interventions")
    for item in interventions if isinstance(interventions, list) else []:
        name = _text(item.get("name")) if isinstance(item, dict) else None
        if name:
            kind = _text(item.get("type"))
            words = [f"{kind}: {name}" if kind else name, _text(item.get("description"))]
            sections.append({"label": "Intervention", "text": "\n".join(w for w in words if w)})
    for key, label in (("eligibilityCriteria", "Eligibility criteria"),
                       ("studyPopulation", "Study population")):  # fmt: skip
        text = _text(modules["eligibilityModule"].get(key))
        if text:
            sections.append({"label": label, "text": text})
    design = modules["designModule"]
    dates = _kept(
        {
            "registered": registered,
            "study_start": _partial(start.get("date")) if start.get("type") == "ACTUAL" else None,
            "updated": _day(status.get("lastUpdateSubmitDate")),
        }
    )
    title = _text(modules["identificationModule"].get("officialTitle")) or _text(
        modules["identificationModule"].get("briefTitle")
    )
    return _kept(
        {
            "status": FOUND,
            "title": title,
            "dates": dates,
            "study_type": _DESIGN.get(design.get("studyType")),
            "design": _design_text(design),
            "sections": sections,
        }
    )


# -------------------------------------------------------------------------------------- OSF


def _osf_text(value: Any) -> str | None:
    """An answer as words: a text, a choice, several choices, or the files attached."""
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, str):
        return _text(value)
    if isinstance(value, list):
        words = []
        for item in value:
            if isinstance(item, dict):
                item = item.get("file_name") or item.get("name")
            text = _osf_text(item)
            if text:
                words.append(text)
        return "; ".join(words) or None
    return None


def _osf_labels(blocks: list[Any]) -> dict[str, str] | None:
    """Each question id of a template, and the words of the question it answers."""
    labels: dict[str, str] = {}
    current = None
    for block in blocks:
        attributes = block.get("attributes") if isinstance(block, dict) else None
        if not isinstance(attributes, dict):
            return None
        kind = attributes.get("block_type")
        shown = _text(attributes.get("display_text"))
        if kind == "question-label":
            current = shown
        key = attributes.get("registration_response_key")
        if isinstance(key, str) and key:
            labels[key] = current or shown or key
    return labels


def _osf_sections(responses: dict[str, Any], labels: dict[str, str]) -> list[dict[str, Any]]:
    ordered = [k for k in labels if k in responses] + [k for k in responses if k not in labels]
    sections = []
    for key in ordered:
        text = _osf_text(responses[key])
        if text:
            label = labels.get(key, key)
            section = {"label": label, "text": text}
            if _OUTCOME_LABEL.search(label):
                section["role"] = "outcomes"
            sections.append(section)
    return sections


def _related(item: dict[str, Any], name: str) -> str | None:
    relation = (item.get("relationships") or {}).get(name)
    data = relation.get("data") if isinstance(relation, dict) else None
    return data.get("id") if isinstance(data, dict) and isinstance(data.get("id"), str) else None


_JSON_API = {"Accept": "application/vnd.api+json"}


def _osf_get(ask: Ask, url: str, params: dict[str, str] | None = None) -> dict[str, Any]:
    """One JSON:API document, or the record's answer where none came: `absent` for a 404 or
    a 410, which OSF answers for what it deleted."""
    answer = _ask(ask, Request(url, params=params or {}, headers=_JSON_API))
    if isinstance(answer, dict):
        return answer
    if answer.status in (404, 410):
        gone = "it was deleted" if answer.status == 410 else "it holds none"
        return {"status": ABSENT, "why": f"OSF says {gone} (HTTP {answer.status})"}
    if answer.status in (401, 403):
        return unresolvable(f"OSF does not show it (HTTP {answer.status}): private or embargoed")
    said = _status_only(answer)
    if said:
        return said
    data = _json(answer)
    if isinstance(data, dict) and isinstance(data.get("data"), (dict, list)):
        return data
    return unresolvable(SHAPE)


def _attributes(document: dict[str, Any]) -> dict[str, Any]:
    data = document.get("data")
    attributes = data.get("attributes") if isinstance(data, dict) else None
    return attributes if isinstance(attributes, dict) else {}


def _not_found(document: dict[str, Any]) -> dict[str, Any]:
    """A document that should be there and is not: the registration's shape is broken."""
    return unresolvable(SHAPE) if document["status"] == ABSENT else document


def osf(identifier: str, ask: Ask, base: str) -> dict[str, Any]:
    """OSF's record of one registration, `osf.io/<guid>`, with what it said first where it
    was updated since."""
    guid = identifier.rsplit("/", 1)[-1]
    document = _osf_get(ask, f"{base}registrations/{guid}/")
    if "status" in document:
        return document
    item = document["data"]
    attributes = _attributes(document)
    registered = _day(attributes.get("date_registered"))
    responses = attributes.get("registration_responses")
    template = _related(item, "registration_schema") if isinstance(item, dict) else None
    if item.get("type") != "registrations" or registered is None or template is None or (
            not isinstance(responses, dict)):  # fmt: skip
        return unresolvable(SHAPE)
    blocks = _osf_get(ask, f"{base}schemas/registrations/{template}/schema_blocks/",
                      {"page[size]": _OSF_PAGE})  # fmt: skip
    if "status" in blocks:
        return _not_found(blocks)
    listed = blocks["data"] if isinstance(blocks["data"], list) else None
    total = ((blocks.get("links") or {}).get("meta") or {}).get("total")
    labels = _osf_labels(listed) if listed is not None else None
    if labels is None or (isinstance(total, int) and total > len(listed)):
        return unresolvable(SHAPE)
    record: dict[str, Any] = {
        "status": FOUND,
        "title": _text(attributes.get("title")),
        "dates": {"registered": registered},
        "design": _text(attributes.get("registration_supplement")),
        "withdrawn": True if attributes.get("withdrawn") is True else None,
        "sections": _osf_sections(responses, labels),
    }
    first, latest = _related(item, "original_response"), _related(item, "latest_response")
    if first and latest and first != latest:
        earlier = _osf_get(ask, f"{base}schema_responses/{first}/")
        later = _osf_get(ask, f"{base}schema_responses/{latest}/")
        for one in (earlier, later):
            if "status" in one:
                return _not_found(one)
        said_first, said_later = _attributes(earlier), _attributes(later)
        if not isinstance(said_first.get("revision_responses"), dict):
            return unresolvable(SHAPE)
        record["first_version"] = _kept(
            {
                "updated": _day(said_later.get("date_submitted")),
                "reason": _text(said_later.get("revision_justification")),
                "sections": _osf_sections(said_first["revision_responses"], labels),
            }
        )
        record["dates"]["updated"] = _day(said_later.get("date_submitted"))
    record["dates"] = _kept(record["dates"])
    return _kept(record)


# ----------------------------------------------------------------------------------- ISRCTN

_NS = "{http://www.67bricks.com/isrctn}"


def _node_text(node: Any) -> str | None:
    return _text("".join(node.itertext())) if node is not None else None


def isrctn(identifier: str, ask: Ask, base: str) -> dict[str, Any]:
    """ISRCTN's record of one trial, found by its number among what the query answers."""
    request = Request(base, params={"q": identifier, "limit": "10"},
                      headers={"Accept": "application/xml"})  # fmt: skip
    answer = _ask(ask, request)
    if isinstance(answer, dict):
        return answer
    said = _status_only(answer)
    if said:
        return said
    try:
        root = parse_xml(answer.body, what="ISRCTN's answer")
    except UnsafeDocument:
        return unresolvable(SHAPE)
    count = root.get("totalCount")
    if root.tag != f"{_NS}allTrials" or count is None or not count.isdigit():
        return unresolvable(SHAPE)
    number = identifier.removeprefix("ISRCTN")
    trials = root.findall(f"{_NS}fullTrial")
    for full in trials:
        trial = full.find(f"{_NS}trial")
        assigned = trial.find(f"{_NS}isrctn") if trial is not None else None
        if assigned is None or (assigned.text or "").strip() != number:
            continue
        registered = _day(assigned.get("dateAssigned"))
        if registered is None:
            return unresolvable(SHAPE)
        return _isrctn_record(trial, registered)
    if int(count) > len(trials):
        # The trial may be among those the answer did not hold: nothing is known of it.
        return unresolvable(f"ISRCTN found {count} trials for {identifier}, more than it gave")
    return {"status": ABSENT, "why": f"ISRCTN holds no trial {identifier}"}


def _isrctn_record(trial: Any, registered: str) -> dict[str, Any]:
    def first(name: str) -> str | None:
        return _node_text(trial.find(f".//{_NS}{name}"))

    sections = []
    for name, role, label in (
        ("primaryOutcome", "primary", "Primary outcome measure"),
        ("secondaryOutcome", "secondary", "Secondary outcome measures"),
    ):
        for node in trial.iter(f"{_NS}{name}"):
            text = _node_text(node)
            if text:
                sections.append({"label": label, "role": role, "text": text})
    for name, label in (
        ("studyHypothesis", "Study hypothesis"),
        ("inclusion", "Participant inclusion criteria"),
        ("exclusion", "Participant exclusion criteria"),
        # `description` is a condition's as well as an intervention's.
        (f"interventions/{_NS}intervention/{_NS}description", "Intervention"),
    ):
        text = first(name)
        if text:
            sections.append({"label": label, "text": text})
    kind = (first("primaryStudyDesign") or "").casefold()
    study_type = {"interventional": "interventional", "observational": "observational"}
    designs = (first("secondaryStudyDesign"), first("studyDesign"))
    design = "; ".join(dict.fromkeys(d for d in designs if d))
    updated = _day(trial.get("lastUpdated"))
    return _kept(
        {
            "status": FOUND,
            "title": first("scientificTitle") or first("title"),
            "dates": _kept(
                {
                    "registered": registered,
                    "study_start": _day(first("recruitmentStart")),
                    "updated": updated,
                }
            ),
            "study_type": study_type.get(kind),
            "design": design or None,
            "sections": sections,
        }
    )


def host_of(base: str) -> str:
    return urlsplit(base).hostname or ""


__all__ = ["Services", "clinicaltrials", "host_of", "isrctn", "osf"]
