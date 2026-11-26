# For an editorial office

This page is for a journal's editorial office deciding whether its editors and reviewers may
check a submitted manuscript with manuscript-guard. It says what the tool does with a
manuscript, how to see that for yourself, what it costs and where it falls short. What an
editor then does with it is in [For editors and reviewers](refereeing.md).

## In short

- **No AI model.** The checks are fixed rules written as code. The same paper gives the same
  report every time, and no part of the check asks a model anything.
- **The manuscript stays on the editor's computer.** There is no account, no server and no
  upload. The check runs in the editor's browser or in a terminal on the editor's computer.
- **Only the reference list and the trial's registration can be looked up, and only when
  the editor asks.** Ticking *Check the reference list for retracted and unregistered works,
  and the trial's registration* on the page, or adding `--lookup` on the command line, asks
  the public registries (Crossref, OpenAlex, DataCite, doi.org and PubMed) whether each cited
  work exists and whether it was retracted. They are sent each DOI and PubMed ID the list
  gives, and, for an article, book or chapter that gives neither, the words of its title, its
  first author's family name and its year, which go to Crossref. Each trial registration
  number the paper names is sent to its registry, ClinicalTrials.gov or ISRCTN, to show what
  the trial registered. No sentence of the paper is sent.
- **Free and open source.** manuscript-guard is under the MIT licence. Nothing in it is
  paid, and it needs no subscription or key.

## Two ways to run it

**The audit page**, <https://basilechretien.github.io/manuscript-guard/audit/>, for an
editor who will not open a terminal. It reads a Word (.docx) or Markdown paper. The page and
every file it loads are plain files that GitHub Pages serves; the paper is read inside the
browser, and nothing behind the page could receive it.

**The command line**, `uvx manuscript-guard audit paper.pdf`, for an editor or an office
that will. It also reads PDF (with poppler's `pdftotext` installed) and LaTeX, holds the
paper to the journal's rules (`--journal`), sorts what it found in an editor's four parts
(`--editor`) and sets a revision beside the version before it with the response letter
(`compare`). Installing it downloads the package from PyPI; running it sends nothing.

## How to see that nothing is sent

On the audit page, three ways, from the simplest:

1. **Turn the network off.** Once the page says *Ready*, unplug the cable or turn off Wi-Fi,
   then choose the paper: the check runs all the same. Only the lookups need the
   network, and they say they could not reach the registries.
2. **Press *Test the rules*,** under *Is my paper uploaded?* at the foot of the page. The
   page's own rules, which the browser enforces, allow requests only to the page's address
   and to the seven registries. The button tries eight requests those rules forbid and shows
   each one refused.
3. **Read the list.** *What did this page load and send?* lists every request the browser
   recorded, and `files.sha256` lists every file the page loads with its SHA-256. The source
   is on GitHub.

On the command line, run it with the network off: the report is the same as with it, but
for the lookups. The project's tests hold this.
[`tests/test_audit_sends_nothing.py`](../tests/test_audit_sends_nothing.py) runs the audit
with every connection refused and fails if one is tried without `--lookup`, or if the part
of the package that calls a model is loaded at all. Only `review --run` calls one: an
author's command for having their own draft read by models they choose.

What the page's rules cannot stop, so that nobody trusts them beyond it:

- A browser extension the editor installed can read any page.
- No browser rule forbids a page to follow a link, and an address can carry text. The
  page's code does neither, which anyone can read, and turning the network off covers it.
- The page is loaded from GitHub's servers. Once loaded, it sends them nothing, and the
  network test covers this too.

[The audit page](audit-page.md) has the rest of how the page works.

## Policies on AI tools

Many journals forbid putting a manuscript under review into an AI tool that does not keep it
confidential. manuscript-guard asks no model, but a journal's policy may forbid any tool,
even one that runs on the editor's own computer. That is the journal's decision. Two points
bear on it:

- The report quotes the manuscript, so it is as confidential as the paper: an editor should
  not paste it into a chatbot.
- Together, what the lookups send points to the paper, and the trial's registration
  number most of all. An office that wants nothing at all to leave can ask its editors to
  leave the lookups off.

An office that allows it might say so in one sentence, for example: *Editors and reviewers
may check a manuscript with manuscript-guard's audit on their own computer, with the
reference lookups off unless the journal allows them.*

## What it checks, and how often it is wrong

It reads the paper's numbers, its words and its reference list, and, given the journal's
profile, the journal's rules. It does not judge the science. The editor's report never calls
a paper clean: a paper with no findings may still be wrong in ways the check cannot see.

Its findings are measured on real papers, where a person judged each one true or false
([how the measuring works](corpus.md)). The editor's report gives the result beside each
kind of finding, as *Right in N of M judged on published papers*, wherever ten or more were
judged, and says *Not yet measured on published papers* elsewhere. A kind that is often
wrong is marked as a note rather than a warning.

## Versions, licences and help

- It is alpha: the checks still change from week to week. Each release is on PyPI, and the
  audit page is built from each release and says at its top which version it runs, with a
  link to what that release changed.
- manuscript-guard is MIT. The audit page also runs pandoc (GPL-2.0-or-later, with a link to
  its source), Pyodide (MPL-2.0) and `browser_wasi_shim` (MIT or Apache-2.0); the page's
  footer links to each licence.
- Questions and faults go to the project's
  [issues](https://github.com/BasileChretien/manuscript-guard/issues). A security problem
  goes privately, as [SECURITY.md](../SECURITY.md) says.
