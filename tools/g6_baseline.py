"""How often G6 fires on clean text written by people, and the rate thresholds it implies.

Run by hand, never by pytest or CI: it reads Europe PMC over the network. Four steps, each
writing to `tools/data/g6-corpus.yaml`, which keeps each paper's identifiers, the digests
of what was read and what was measured of it, and never its text:

    python tools/g6_baseline.py draw                # the candidates, from the stated query
    python tools/g6_baseline.py fetch --cache DIR   # each one's JATS, kept outside the repository
    python tools/g6_baseline.py measure --cache DIR # through pandoc and G6, one paper at a time
    python tools/g6_baseline.py report [--apply]    # thresholds, the held-out check, the record

The papers are open-access research articles under CC BY, published from 2010 to October
2022, before chat models were common, as Europe PMC indexes them. Each is read as G6 reads a
manuscript: its JATS through pandoc's JATS reader into Markdown, never text taken from a PDF,
from its first heading to its reference list, and judged by `gates.writing.judge_texts`.
Each paper is measured on its own; the corpus is never pooled.

What the run must show is fixed here, before it: `BUDGET`, `PERCENTILE`, the sizes below
which nothing is reported, and the held-out papers, drawn with the rest and never used to
set a threshold. Each `per_1000` is set at the stated percentile of the papers that set
thresholds; the held-out papers are then judged by them, and the budget says whether G6
passes clean prose.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
import re
import shutil
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from collections import Counter
from collections.abc import Callable
from datetime import date, timedelta
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from manuscript_guard.findings import FAIL, WARN  # noqa: E402
from manuscript_guard.gates.writing import DATA, judge_texts, rates  # noqa: E402
from manuscript_guard.text.sections import count_words  # noqa: E402

CORPUS = ROOT / "tools" / "data" / "g6-corpus.yaml"
SEARCH = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
FULL_TEXT = "https://www.ebi.ac.uk/europepmc/webservices/rest/{pmcid}/fullTextXML"
#: Open-access research articles in English with their full text; CC BY is checked again in
#: each article's own licence, since a phrase search on the licence may take in its variants.
QUERY = (
    'OPEN_ACCESS:y AND LICENSE:"cc by" AND HAS_FT:y AND LANG:eng '
    'AND PUB_TYPE:"research-article"'
)
WINDOW = (date(2010, 1, 1), date(2022, 10, 31))
SEED = 54
CANDIDATES = 400
HELD_OUT = 100
PERCENTILE = 99
#: Below either, nothing is reported.
MINIMUM = {"tune": 250, "held-out": 80}
#: Fewer words of body than this is too short to hold a rate.
MIN_WORDS = 1000
#: What clean prose must get from G6, fixed before the run: no failure on any held-out
#: paper, and at most `warnings` warnings on at least `share` of them.
BUDGET = {"failures": 0, "warnings": 2, "share": 0.95}
#: The heading a reference list opens under; the body is cut there.
_REFERENCES = re.compile(
    r"(?im)^#{1,6}\s+(?:references?|reference\s+list|bibliography|literature\s+cited|works\s+cited)"
    r"\b[^\n]*$"
)
_HEADING = re.compile(r"(?m)^#{1,6}\s")
_ARTICLE_TYPE = re.compile(r'<article\b[^>]*?\barticle-type="([^"]+)"')
_LICENCE = re.compile(r"creativecommons\.org/licenses/([a-z-]+)/", re.IGNORECASE)
#: A licence stated in words, as older articles do with no link: "distributed under the terms
#: of the Creative Commons Attribution License", which is CC BY unless a further term follows.
_LICENCE_TEXT = re.compile(r"<license\b.*?</license>", re.IGNORECASE | re.DOTALL)
#: Its version, "International" and "(CC BY)" may stand before "License" (round 1 of #339).
_ATTRIBUTION = re.compile(
    r"Creative\s+Commons\s+Attribution\b(?:[^.<]|\.(?=\d)){0,60}?Licen[cs]e"
    r"|\bAttribution\s*\(CC[\s-]?BY\b[^)]*\)\s*Licen[cs]e",
    re.IGNORECASE,
)
_FURTHER_TERM = re.compile(r"Non-?Commercial|No-?Deriv|Share-?Alike|\bNC\b|\bND\b|\bSA\b")


def licences_of(xml: str) -> set[str]:
    """The Creative Commons licences an article states: by their links, and by their name
    where it gives no link (the first measurement excluded 69 such articles as stating
    none)."""
    found = {link.lower() for link in _LICENCE.findall(xml)}
    if not found:
        for stated in _LICENCE_TEXT.findall(xml):
            if _ATTRIBUTION.search(stated) and not _FURTHER_TERM.search(stated):
                found.add("by")
    return found

Fetch = Callable[[str], bytes]


def fetch_url(url: str) -> bytes:
    """The bytes at `url`; the one function that opens a connection."""
    request = urllib.request.Request(url, headers={"User-Agent": "manuscript-guard g6_baseline"})
    with urllib.request.urlopen(request, timeout=60) as reply:
        return reply.read()


# --------------------------------------------------------------------------------- draw


def _search(query: str, fetch: Fetch, cursor: str = "*") -> dict:
    url = SEARCH + "?" + urllib.parse.urlencode(
        {"query": query, "format": "json", "pageSize": 1000, "resultType": "lite",
         "cursorMark": cursor}
    )  # fmt: skip
    return json.loads(fetch(url))


def _between(first: date, last: date) -> str:
    return f"FIRST_PDATE:[{first.isoformat()} TO {last.isoformat()}]"


def _shares(counts: dict[int, int], total: int) -> dict[int, int]:
    """`total` papers shared among the years in proportion to how many each has, by the
    largest remainder."""
    whole = sum(counts.values())
    exact = {year: total * n / whole for year, n in counts.items()}
    given = {year: math.floor(share) for year, share in exact.items()}
    left = total - sum(given.values())
    for year in sorted(exact, key=lambda y: (given[y] - exact[y], y))[:left]:
        given[year] += 1
    return given


def draw(fetch: Fetch = fetch_url, today: date | None = None) -> dict:
    """The candidates: each year's share of `CANDIDATES` in proportion to its articles, and
    within a year one article at random on each of as many random days, with `HELD_OUT` of
    them set aside at random. An article is not drawn with the same chance as every other:
    one on a day with many is less likely than one on a quiet day, and one past the first
    1000 Europe PMC lists for its day is never drawn (round 1 of #339)."""
    rng = random.Random(SEED)
    first, last = WINDOW
    years = range(first.year, last.year + 1)
    counts = {}
    for year in years:
        start, end = max(first, date(year, 1, 1)), min(last, date(year, 12, 31))
        counts[year] = _search(f"{QUERY} AND {_between(start, end)}", fetch)["hitCount"]
    shares = _shares(counts, CANDIDATES)
    taken: set[str] = set()
    candidates = []
    for year in years:
        start, end = max(first, date(year, 1, 1)), min(last, date(year, 12, 31))
        span = (end - start).days + 1
        wanted, tried = shares[year], 0
        while wanted and tried < 50 * shares[year]:
            tried += 1
            day = start + timedelta(days=rng.randrange(span))
            listed = _search(f"{QUERY} AND {_between(day, day)}", fetch)["resultList"]["result"]
            found = [r for r in listed if r.get("pmcid") and r["pmcid"] not in taken]
            if not found:
                continue
            chosen = rng.choice(sorted(found, key=lambda r: r["pmcid"]))
            taken.add(chosen["pmcid"])
            candidates.append({"pmcid": chosen["pmcid"], "doi": chosen.get("doi"),
                               "published": chosen.get("firstPublicationDate")})  # fmt: skip
            wanted -= 1
    held = set(rng.sample(range(len(candidates)), HELD_OUT))
    for at, candidate in enumerate(candidates):
        candidate["set"] = "held-out" if at in held else "tune"
    return {
        "schema": "manuscript-guard/g6-corpus/1",
        "query": QUERY, "window": [first.isoformat(), last.isoformat()], "seed": SEED,
        "drawn_on": (today or date.today()).isoformat(), "articles_by_year": counts,
        "percentile": PERCENTILE, "budget": BUDGET, "minimum": MINIMUM,
        "min_words": MIN_WORDS, "candidates": candidates,
    }  # fmt: skip


# -------------------------------------------------------------------------------- fetch


def fetch_all(corpus: dict, cache: Path, fetch: Fetch = fetch_url, pause: float = 0.2) -> dict:
    """Each candidate's JATS from Europe PMC into `cache`, its digest recorded; a candidate
    whose full text cannot be had is unreadable."""
    cache.mkdir(parents=True, exist_ok=True)
    for candidate in corpus["candidates"]:
        path = cache / f"{candidate['pmcid']}.xml"
        if not path.exists():
            try:
                path.write_bytes(fetch(FULL_TEXT.format(pmcid=candidate["pmcid"])))
            except OSError as exc:
                candidate.update(status="unreadable", why=f"full text not fetched: {exc}")
                continue
            time.sleep(pause)
        candidate["xml_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
        candidate.pop("status", None)
    return corpus


# ------------------------------------------------------------------------------ measure


def body_of(markdown: str) -> str | None:
    """The paper as G6 would read its manuscript: from its first heading to its reference
    list; None where it has no heading."""
    first = _HEADING.search(markdown)
    if first is None:
        return None
    body = markdown[first.start():]
    cut = _REFERENCES.search(body)
    return body[: cut.start()] if cut else body


#: The filter that leaves a paper's tables out of what is measured: a manuscript's tables are
#: emitted and bound, and G6 does not count them, while a paper's bold marks values in its
#: tables (round 1 of #339).
NO_TABLES = ROOT / "tools" / "data" / "g6-no-tables.lua"


def to_markdown(path: Path, pandoc: str) -> str | None:
    """`path`'s JATS as pandoc's JATS reader writes it in Markdown, its tables left out;
    None where it cannot, in two minutes. Without `smart`, which writes an em dash as "---"
    and an en dash as "--", where G6 counts the dashes themselves (round 1 of #339: the
    first measurement saw an em dash in 18 of 384 papers)."""
    try:
        run = subprocess.run(
            [pandoc, "-f", "jats", "-t", "markdown-smart", "--wrap=none",
             "--lua-filter", str(NO_TABLES), str(path)],
            capture_output=True, timeout=120,
        )  # fmt: skip
    except subprocess.TimeoutExpired:
        return None
    if run.returncode != 0:
        return None
    return run.stdout.decode("utf-8", errors="strict")


def measure_one(candidate: dict, xml: bytes, markdown: str | None) -> dict:
    """What is measured of one paper, or why it is not used: excluded (not a research
    article, or not CC BY), garbled (pandoc could not read it, or no heading), too short."""
    head = xml[:20000].decode("utf-8", errors="replace")
    kind = _ARTICLE_TYPE.search(head)
    if kind is None or kind.group(1) != "research-article":
        return {"status": "excluded", "why": f"article type {kind.group(1) if kind else None}"}
    licences = licences_of(xml.decode("utf-8", errors="replace"))
    if licences != {"by"}:
        return {"status": "excluded", "why": f"licence {sorted(licences) or 'not stated'}"}
    body = body_of(markdown) if markdown is not None else None
    if body is None:
        why = "pandoc read no heading" if markdown else "pandoc failed"
        return {"status": "garbled", "why": why}
    words = count_words(body)
    if words < MIN_WORDS:
        return {"status": "too-short", "words": words}
    texts = [(Path(f"{candidate['pmcid']}.md"), body)]
    report, _totals = judge_texts(texts)
    fired = Counter(f.message.split(":", 1)[0] for f in report.findings
                    if f.code == "ai-phrasing")  # fmt: skip
    return {
        "status": "used",
        "text_sha256": hashlib.sha256(body.encode("utf-8")).hexdigest(),
        "words": words,
        "rates": {rule: round(rate, 4) for rule, rate in rates(texts).items()},
        "failures": sum(f.severity == FAIL for f in report.findings),
        "phrase_findings": sum(f.code == "ai-phrasing" for f in report.findings),
        "vague_findings": sum(f.code == "vague-attribution" for f in report.findings),
        "other_warnings": sum(f.severity == WARN and f.code not in
                              ("ai-phrasing", "vague-attribution", "ai-cadence")
                              for f in report.findings),  # fmt: skip
        "fired": dict(sorted(fired.items())),
    }


def measure_all(corpus: dict, cache: Path, pandoc: str) -> dict:
    for candidate in corpus["candidates"]:
        if candidate.get("status") == "unreadable":
            continue
        path = cache / f"{candidate['pmcid']}.xml"
        xml = path.read_bytes()
        if hashlib.sha256(xml).hexdigest() != candidate.get("xml_sha256"):
            raise SystemExit(f"{path}: not the file fetched; fetch again")
        for key in ("status", "why", "words", "text_sha256", "rates", "failures",
                    "phrase_findings", "vague_findings", "other_warnings", "fired"):  # fmt: skip
            candidate.pop(key, None)
        candidate.update(measure_one(candidate, xml, to_markdown(path, pandoc)))
    return corpus


# ------------------------------------------------------------------------------- report

STATUSES = ("used", "unreadable", "too-short", "garbled", "excluded")


def percentile(values: list[float], at: int) -> float:
    """The nearest-rank `at`th percentile of `values`."""
    ordered = sorted(values)
    return ordered[max(math.ceil(at / 100 * len(ordered)), 1) - 1]


def thresholds(corpus: dict) -> dict[str, float]:
    """Each rate rule's threshold: the stated percentile of the tuning papers' rates,
    rounded up to a tenth, so that no more of them than stated lie above it."""
    tune = [c for c in corpus["candidates"] if c.get("status") == "used" and c["set"] == "tune"]
    rules = sorted({rule for c in tune for rule in c["rates"]})
    return {rule: math.ceil(10 * percentile([c["rates"][rule] for c in tune],
                                            corpus["percentile"]) - 1e-9) / 10
            for rule in rules}  # fmt: skip


def warnings_of(candidate: dict, limits: dict[str, float]) -> int:
    """How many warnings G6 gives a paper at `limits`: a rate above its threshold, and the
    phrases, vague attributions and other warnings it reported."""
    above = sum(candidate["rates"][rule] > limit for rule, limit in limits.items())
    return above + candidate["phrase_findings"] + candidate["vague_findings"] + \
        candidate["other_warnings"]  # fmt: skip


def accounting(corpus: dict) -> dict[str, dict[str, int]]:
    counted = {part: Counter(c.get("status", "not measured") for c in corpus["candidates"]
                             if c["set"] == part) for part in ("tune", "held-out")}  # fmt: skip
    return {part: {status: counts.get(status, 0) for status in (*STATUSES, "not measured")}
            for part, counts in counted.items()}  # fmt: skip


def corpus_digest(corpus: dict) -> str:
    listed = sorted((c["pmcid"], c["set"], c.get("xml_sha256") or "") for c in corpus["candidates"])
    return hashlib.sha256(json.dumps(listed).encode("utf-8")).hexdigest()


def judge(corpus: dict) -> dict:
    """Everything the report says, from the corpus file alone."""
    counts = accounting(corpus)
    total = sum(sum(part.values()) for part in counts.values())
    if total != len(corpus["candidates"]) or any(part["not measured"] for part in counts.values()):
        raise SystemExit("the corpus does not add up: measure every candidate first")
    short = [part for part, least in corpus["minimum"].items() if counts[part]["used"] < least]
    if short:
        raise SystemExit(f"too few papers used to report: {short} under {corpus['minimum']}")
    limits = thresholds(corpus)
    held = [c for c in corpus["candidates"] if c.get("status") == "used" and c["set"] == "held-out"]
    budget = corpus["budget"]
    within = sum(warnings_of(c, limits) <= budget["warnings"] for c in held) / len(held)
    failing = sum(c["failures"] > budget["failures"] for c in held)
    used = [c for c in corpus["candidates"] if c.get("status") == "used"]
    fired = Counter(rule for c in used for rule in c["fired"])
    return {
        "accounting": counts, "thresholds": limits, "corpus_sha256": corpus_digest(corpus),
        "held_out": {"papers": len(held), "within_budget": within, "failing": failing,
                     "above_by_rule": {rule: sum(c["rates"][rule] > limit for c in held)
                                       for rule, limit in limits.items()}},
        "budget_met": failing == 0 and within >= budget["share"],
        "phrases_fire_on": {rule: n / len(used) for rule, n in fired.most_common()},
        "vague_on": sum(c["vague_findings"] > 0 for c in used) / len(used),
    }  # fmt: skip


def apply(limits: dict[str, float], judged: dict, corpus: dict, data: Path = DATA) -> str:
    """`data` with each rate rule's `per_1000` set to its measured threshold, and where it
    came from written above it."""
    text = data.read_text(encoding="utf-8")
    papers = judged["accounting"]["tune"]["used"]
    said = (
        f"    # The {corpus['percentile']}th percentile of {papers} papers by people\n"
        f"    # (tools/g6_baseline.py, corpus {judged['corpus_sha256'][:16]}, drawn "
        f"{corpus['drawn_on']}).\n"
    )
    for rule, limit in limits.items():
        block = re.compile(
            rf"(?m)^(  - id: {re.escape(rule)}\n)((?:    .*\n)*?)"
            r"(?:    # The \d+th percentile.*\n    # \(tools/g6_baseline\.py.*\n)?"
            r"    per_1000: [\d.]+\n"
        )
        replaced = f"{said}    per_1000: {limit}\n"
        text, found = block.subn(lambda m, new=replaced: m.group(1) + m.group(2) + new, text)
        if found != 1:
            raise SystemExit(f"{rule}: no single per_1000 in {data.name}")
    data.write_text(text, encoding="utf-8", newline="\n")
    return text


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="step", required=True)
    sub.add_parser("draw")
    sub.add_parser("fetch").add_argument("--cache", type=Path, required=True)
    measure = sub.add_parser("measure")
    measure.add_argument("--cache", type=Path, required=True)
    measure.add_argument("--pandoc", help="pandoc's path, where it is not on PATH")
    sub.add_parser("report").add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)
    corpus = draw() if args.step == "draw" else yaml.safe_load(CORPUS.read_text(encoding="utf-8"))
    if args.step == "fetch":
        corpus = fetch_all(corpus, args.cache)
    elif args.step == "measure":
        pandoc = args.pandoc or shutil.which("pandoc")
        if pandoc is None:
            raise SystemExit("pandoc is not on PATH: give it with --pandoc")
        corpus = measure_all(corpus, args.cache, pandoc)
    elif args.step == "report":
        judged = judge(corpus)
        print(yaml.safe_dump(judged, sort_keys=False, allow_unicode=True))
        if args.apply:
            apply(judged["thresholds"], judged, corpus)
            print(f"wrote the thresholds into {DATA}")
        return 0
    CORPUS.parent.mkdir(parents=True, exist_ok=True)
    CORPUS.write_text(yaml.safe_dump(corpus, sort_keys=False, allow_unicode=True),
                      encoding="utf-8", newline="\n")  # fmt: skip
    print(f"{args.step}: {Counter(c.get('status', '-') for c in corpus['candidates'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
