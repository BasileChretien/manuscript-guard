"""What `docs/editorial-office.md` tells a journal: `audit` opens no connection unless
`--lookup` is given, and never loads the part of the package that calls a model
(`manuscript_guard.panel`, through which only `review --run` sends a draft to one).

Each audit runs in an interpreter of its own, where every way to open a connection refuses
and is written down, so that what an earlier test imported is not counted. The lookups are
the control: they must be seen, or the guard sees nothing.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from urllib.parse import unquote_plus, urlsplit

import pytest

#: Run `manuscript-guard <args>` with every connection refused and recorded, then print, on
#: the last line, what was tried, the address of each request `urllib` was asked to send,
#: and which modules of `manuscript_guard.panel` were loaded.
GUARD = r"""
import json, socket, sys, urllib.request

tried = []
urls = []

def refuse(*args, **kwargs):
    tried.append(repr(args)[:120])
    raise OSError("this test refuses every connection")

socket.getaddrinfo = refuse
socket.create_connection = refuse
socket.socket.connect = refuse
socket.socket.connect_ex = refuse

opened = urllib.request.OpenerDirector.open

def recorded(self, address, *args, **kwargs):
    urls.append(address if isinstance(address, str) else address.full_url)
    return opened(self, address, *args, **kwargs)

urllib.request.OpenerDirector.open = recorded

from manuscript_guard import cli

try:
    code = cli.main(sys.argv[1:])
except SystemExit as stop:
    code = stop.code
panel = sorted(name for name in sys.modules if name.split(".")[:2] == ["manuscript_guard", "panel"])
print()
print(json.dumps({"tried": tried, "urls": urls, "panel": panel, "code": code}))
"""

PAPER = """\
# A cohort of 120 patients

## Abstract

Of the 120 patients, 30 (25.0%) had the outcome.

## Methods

We followed 120 patients for a year.

## Results

Of the 120 patients, 30 (25.0%) had the outcome (Smith 2020; Jones 2019).

## References

1. Smith A. A study of the outcome. J Test. 2020;1:1-2. doi:10.5555/12345678
2. Jones B, Lee C. Weekly outcome counts in a regional cohort of adults. Epidemiol Test.
   2019;4:10-20.
"""

#: The hosts the lookups may ask, which the audit page's policy names too (tests/test_web.py).
REGISTRIES = {"api.crossref.org", "api.openalex.org", "api.datacite.org", "doi.org",
              "eutils.ncbi.nlm.nih.gov"}  # fmt: skip


def _audit(tmp_path: Path, *args: str) -> dict:
    paper = tmp_path / "paper.md"
    paper.write_text(PAPER, encoding="utf-8")
    run = subprocess.run(
        [sys.executable, "-c", GUARD, "audit", str(paper), *args],
        capture_output=True, text=True, encoding="utf-8", timeout=180, cwd=tmp_path,
    )
    lines = run.stdout.strip().splitlines()
    assert lines, run.stderr
    return json.loads(lines[-1])


@pytest.mark.parametrize("flags", [
    [],
    ["--editor"],
    ["--json"],
    ["--against", "results.json"],
    ["--editor", "--report-draft", "report.md"],
], ids=["plain", "editor", "json", "against", "report-draft"])
def test_an_audit_opens_no_connection_and_loads_nothing_that_sends_to_a_model(
    tmp_path: Path, flags: list[str]
) -> None:
    (tmp_path / "results.json").write_text('{"patients": 120, "with_outcome": 30}', "utf-8")
    seen = _audit(tmp_path, *flags)
    assert seen["tried"] == []
    assert seen["panel"] == []


def test_the_guard_sees_the_connections_the_lookups_try(tmp_path: Path) -> None:
    """The control: with `--lookup` the audit asks the registries about the DOI, so the
    guard must record it. A guard that missed it would pass every case above for nothing."""
    seen = _audit(tmp_path, "--lookup")
    assert seen["tried"], "the lookups opened no connection the guard could see"
    assert seen["panel"] == []


def test_the_lookups_send_identifiers_and_the_title_of_an_entry_with_none(
    tmp_path: Path,
) -> None:
    """What docs/editorial-office.md, docs/refereeing.md and the audit page say `--lookup`
    sends: each DOI and PubMed ID, and for an article with neither, the words of its title,
    its first author's family name and its year, to Crossref. Never a sentence of the
    paper's own. (Round 1 of #822: the pages said that no title or name was ever sent.)"""
    seen = _audit(tmp_path, "--lookup")
    asked = [unquote_plus(url) for url in seen["urls"]]
    assert asked, "the lookups asked nothing"
    assert {urlsplit(url).hostname for url in asked} <= REGISTRIES, asked
    assert any("10.5555/12345678" in url for url in asked), asked
    searched = [url for url in asked if "query.bibliographic=" in url]
    assert searched, asked
    for url in searched:
        assert "Weekly outcome counts in a regional cohort of adults" in url, url
        assert "Jones" in url and "2019" in url, url
    own = ("had the outcome", "followed 120 patients", "A cohort of 120 patients")
    assert [url for url in asked for words in own if words in url] == []
