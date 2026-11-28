# The audit page

<https://basilechretien.github.io/manuscript-guard/audit/> runs `manuscript-guard audit` inside a
web browser, for a reader who will not open a terminal: a clinician checking a colleague's
draft, an editor, a referee. The paper is read in the browser and is not uploaded. There is
no server behind the page, only static files on GitHub Pages, so there is nothing to upload
it to.

The page is built from each release, so it runs the same version as `pip install
manuscript-guard`, with the same checks, and says which at its top, with a link to what the
release changed. CI holds its reports to the command line's, word for word (below). While
it loads, a bar gives the share of what it fetches that has come, as a percentage (the build
writes the total to `manifest.json`), and the page says which of its five steps
it is on; a step still under way after 90 seconds is said to be slow, with what to do, and
the page keeps waiting. The paper can be chosen or dropped on its box, and the page says the
name of the one taken; "Or try it with an example paper" checks a short invented paper that
ships with the page, so that a first visit sees a report. While the audit runs, the page
lists its steps (reading the paper, the numbers, the writing, each reference looked up, the
report, the PDF, the copy with comments), ticks each one done, names the one under way, and
says how long is left: how long each step usually takes, at the pace this computer has kept so
far (`auditing.progress`). When it ends, the report is brought into view. The page's look is
the landing page's, warm and plain (the author, 2026-11-12: the page was "a bit scary and not
attractive at all"), and what to know about it is under *Questions* at its foot.

## What it checks

A `.docx`, Markdown or PDF paper, or a LaTeX project as a `.zip` or a `.tar.gz`, with the
analysis outputs to compare its numbers with if the reader has them (`.json`, `.csv`, `.tsv`,
`.txt`, `.yaml`). That is everything [`audit`](commands.md#checking--audit) reads in a paper
of that kind:

- the numbers against the outputs, and what a match is worth there;
- the arithmetic, the Abstract against the Results, and the small cells a total gives away;
- the words, by G6 and G14, through pandoc's WebAssembly build of the version CI tests with;
- the reference list (G7), and with the box ticked, whether a cited work was retracted or is
  in no registry;
- the tables and figures (G2), counted by their legends, each cited and numbered in the order
  of its first citation ([audit.md](audit.md)).

The page shows the report as the PDF `audit --pdf` writes, from the same audit, inside the
page, in the browser's own viewer: its summary in colour, every section and every place of
every finding, with its pages, search and zoom (the author, 2026-11-12: "directly display the
interactive pdf inside the page", not in a tab of its own, and no text report beside it).
Above it a sentence says how the checks came out, and "Download the PDF" saves it. A phone,
which shows a PDF in a page of its own, gets "Open the report" instead. For a .docx,
"Download your paper with the findings as Word comments" saves a copy of it with each finding
as a comment at its place, written from the same audit, as `audit --commented` writes it; it
is made in the browser like the rest. The text the command line prints is still made, and CI
holds it to the command line's word for word; the page shows it only where the PDF could not be
made, as the report, with "Download the report as text".
"English of the paper" is `--english`, and "Words to leave alone", split at spaces and
commas, is `--known`: names, initials and the field's terms G14 then neither asks to be
defined, reports the spelling of, nor reads as names from code. "The paper has no Abstract"
is `--no-abstract`, "The paper reports no results" is `--no-results`, and "The heading of
its results" is `--results`, one heading as the page takes it: the answers to the report's
questions for the author ([audit.md](audit.md)).

For a .docx, a box beside the paper's, "Also make a copy with the corrections as tracked
changes", is the copy `audit --tracked` writes: each correction G14 is sure of (spelling to
the chosen English, the spacing of P values, signs, intervals and percentages, an
abbreviation used only once written out) a tracked change to accept or reject in Word, and
every other finding a comment. The corrections are worked out only where the box is ticked
(the author, 2026-11-12: "only when asked"), in the same audit as the report, which they
leave as it is; the copy's comments are worded for the page, as the commented copy's are,
and "Download your paper with its corrections as tracked changes" saves it.

"For a referee or an editor" holds five options of `audit`: "The study's design" is
`--design` ([refereeing.md](refereeing.md)); "Rows of means of whole numbers", "Rows of
numbers each 0 or 1" and "Rows that cannot be negative" are `--whole-numbers`, `--binary`
and `--non-negative`, a label a line, a line that starts with "-" left out as a word to leave
alone is; and "The data custodian's smallest count" is `--minimum-cell-count`, a whole number
from 1 ([audit.md](audit.md)). Of the other options refereeing.md gives a referee, the page
has `--against`, `--english` and `--lookup`, under "More options", and `--journal` and
`--authors`, under "For a journal"; the rest, `--strict` and `--cited` among them, are the
command line's only.

"For a journal" is `--journal` ([refereeing.md](refereeing.md), "An editor"), for the reader
who has the journal's instructions for authors and no profile of it: its name, the address of
the instructions, its limits on the abstract's and the main text's words, the figures, the
tables, the references and the keywords, the sections it requires, the headings of a
structured abstract, the statements it requires (funding, competing interests, ethics
approval, consent, data availability, author contributions, trial registration, the use of
AI) and how its review is blinded. The page writes them as the profile the command line
reads (`manuscript_guard.journal_form`), dated the day it is filled, and passes it as
`journal.yaml`; a limit left empty is not in it, and is not checked. Each statement ticked
has a box for the heading the journal asks for it under, which offers the usual one
("Funding", "Competing interests"), and two it takes are joined by "or" ("Competing interests
or Conflicts of interest"). The paper is held to that heading: a heading whose whole title
it is, numbered, marked or not, the marked words a paragraph opens with ("**Funding:**",
"*Funding.*"), or the words a paragraph opens with in plain type before a colon ("Funding:
none"), in any case. A statement under another heading is reported missing, with the
heading the journal asks for, as the journal's own check would report it (DESIGN.md, Known
gaps). "Or a journal profile
you keep" passes the reader's own profile in place of the form. For a double- or triple-blind
review, or a profile of the reader's own, the authors' boxes are shown: each author's given
and family names, ORCID iD and e-mail address, and the affiliations one a line, written as
`authors.yaml` for `--authors`, or "Or an authors.yaml you keep" in their place. The report
then has its Journal section, the Document section of what a .docx holds besides its text,
and, for a blind review, each place an author is named. Nothing of the form is kept between
visits.

Once the journal's rules are typed, *Copy a link with these rules* makes a link to the page
that carries them, compressed after `#rules=` (Basile, 2026-11-26): an editorial office
types its journal's rules once and sends the link to its editors, and each opens the page
with the rules in the form. The link carries the journal's rules alone, never the authors'
names and nothing of the paper. A browser sends no part of an address after `#` to the
server it asks for the page, so the rules reach whoever opens the link, and not the page's
host. Opened, the page holds the link's rules to the form's boxes and, in the checker, to
the profile's schema, as it holds a profile the reader chooses, and only then fills the
form, keeping the date the rules were read on until a box of them is changed; a link it did
not make, or one cut short, fills nothing and says why above the form. A link pasted into
the page already open is read the same way. On a page a journal's host built, the rules a
link carries take the place of the journal chosen, and the page says so. The button makes
a link only of rules a page opened at it takes (the profile's schema, the form's boxes and a
link's length, packed and unpacked), and says why where it does not, so that no link is sent that every
editor would find refused. Where the browser does not let
the page copy, the link is shown to copy by hand. The page reads its address and never writes
it, and keeps nothing: the link is the reader's to keep and to send.

A LaTeX project comes as the archive Overleaf downloads (`.zip`) or arXiv gives a paper's
source in (`.tar.gz` or `.tgz`, and arXiv's one gzipped `.tex`). The page unpacks it in the
browser into a folder named after it, "project" for `project.zip`, and gives the audit that
folder, as the command line is given the folder a reader unpacks the archive into: `audit
project`, each `.tex` that starts a document a paper. It is unpacked with the checks a
package's `.zip` is held to (`--package`, [refereeing.md](refereeing.md)): nothing is written
where one member could land outside the folder, two names are one in another case, a name
is both a file and a folder, or the archive holds more than 50,000 members or 1 GiB unpacked;
nor where a member of a tar is a link or neither a file nor a folder.

A publisher or a society can serve the page on its own site with its journals built in
([hosting the audit page](hosting-the-audit-page.md)). The page then asks first "Which journal
are you submitting to?", and holds the paper to the profile of the one chosen as `audit
--journal journals/<slug>.yaml` does, with the authors' boxes under the list where its review
is blind; a link may choose one, `?journal=<slug>`. It wears the host's name, logo, colours
and contact line, says "Run by manuscript-guard" and the release, and keeps the rest of this
page as it is: its code is byte for byte this page's.

A PDF is read as the command line reads one ([refereeing.md](refereeing.md)), by the same
code, with poppler's `pdftotext` and `pdfinfo` 26.11.0 built for WebAssembly: its pages and
lines are its places, the line numbers it prints are read, its lines are rebuilt into
paragraphs for G6 and G14, and in a blind review its Author field is read. That build is the
npm package `@ai-ecoverse/wasm-poppler` 26.11.0-1, whatever `pdftotext` the reader has; the
command line uses the one installed, poppler's of another release or Xpdf's, so its report on
the same PDF can differ from the page's, and each report names the `pdftotext` that read it
(DESIGN.md, Known gaps). The page does not read figures or reproducibility packages: the
command line reads those.

## Comparing a revision

"Compare a revision", the page's second choice at the top of its form, is
[`compare`](commands.md) for a referee or an editor reading a revision (the author,
2026-11-28: a second choice on the same page, every option of compare's, its report as
text). It takes the version read first and the revised one, each a `.docx`, Markdown or a
PDF, and where the reader has them the authors' response letter (`--response`) and the
reader's own comments on the first version (`--comments`), each a `.docx`, Markdown or text.
It sets the two versions side by side and audits each, as [refereeing.md](refereeing.md)
says: the sections, the tables cell by cell, the figures' captions, the numbers, citations
and bindings, the sentences that claim more, less or the opposite, the revision's findings
each marked new or standing, the letter's quotations looked for in both versions, and each
comment matched by what it quotes or names. Nothing in it says whether a comment was
answered.

Its report is the text the command line prints, shown in the page, with "Download the report
as text": `compare` writes no PDF. "Also write the start of my report" is `--report-draft`,
the findings and their places as Markdown with no opinion in it, and "Download the start of
your report" saves it. Each version is read from a folder of its own, `v1/` and `v2/`, so that
two versions a journal's system gives one name are both read, and the report names them so:
`v1/paper.docx`. A LaTeX version is the command line's: the page compares no project.
"Or try it with an example revision" compares the example paper with an earlier version of
it, and a letter to reviewers who do not exist, written for the page (`web/example-before.md`,
`web/example-letter.md`).

## How to see that nothing is uploaded

Three ways, from the simplest:

1. **Turn off the network.** Once the page says *Ready*, everything it needs is loaded.
   Unplug the cable or turn off Wi-Fi, then choose the paper: the audit runs all the same.
   Only the lookups need the network, and they say they could not reach the
   registries.
2. **Read its rules, or have the browser test them.** The first rule in the page's source is
   its [Content-Security-Policy](https://developer.mozilla.org/docs/Web/HTTP/Guides/CSP), which
   the browser enforces. It lets the page send requests only to the address it was loaded
   from and to the seven registries the lookups ask (Crossref, OpenAlex, DataCite, doi.org,
   PubMed for the reference list, ClinicalTrials.gov and ISRCTN for the trial's registration),
   to show no frame but a `blob:` address of the browser's own, which the page uses
   only for the PDF it made itself, to start no worker from a file, and to send no form. The page's *Test the rules*
   button tries eight requests the rules forbid, from the page and from the checker, a frame
   from another site among them, and shows each one refused.
3. **Compare the files.** The page lists every file it loads with its SHA-256 in
   `files.sha256`, and *What this page loaded and sent* lists every request the browser
   recorded: while loading, none to any other host; while auditing, none, or the lookups
   alone when the box is ticked.

What the rules cannot stop, so that nobody trusts them beyond it:

- **Leaving the page.** A Content-Security-Policy has no rule for following a link or for a
  script that sets the page's address, and an address can carry text. The page's code does
  neither, which anyone can read in `app.js` and `worker.js`, but no rule enforces it.
  Turning off the network does.
- **The page's own host.** The rules let it send to the address it came from, which it needs
  to load its files: GitHub's servers. The page sends nothing there once loaded, and the
  network test covers this too.
- **The browser itself.** An extension the reader installed can read any page.

## The reference lookups

They are off until the box is ticked. Ticked, they send what `audit --lookup` sends: the DOIs
and PubMed IDs the paper's reference list cites; for an article, book or chapter that gives
neither, the words of its title, its first author's family name and its year, to Crossref;
and each ClinicalTrials.gov or ISRCTN number the paper names outside its reference list,
to that registry ([audit.md](audit.md)). No sentence of the paper is sent. A page
cannot do three
things the command line does: it sends no User-Agent (a browser forbids it), the browser
follows a redirect itself rather than refusing it (to a host the rules allow, or not at all),
and it cannot read Crossref's `Retry-After`, which Crossref does not expose to a page. It has
no API key, and paces itself as the command line does without one.

## Without a browser

One line, with [uv](https://docs.astral.sh/uv/) installed, and nothing else: uv fetches a
Python if there is none.

```bash
uvx manuscript-guard audit paper.docx
```

With outputs, `uvx manuscript-guard audit paper.docx --against results/`. Without
[pandoc](https://pandoc.org/installing.html) installed, the report says G6 and G14 were not
run on a `.docx`.

## How it is built and checked

The page's files are in [`web/`](../web/). Pyodide runs the manuscript-guard wheel in a Web
Worker; pandoc.wasm, from the pandoc release CI pins, stands in for pandoc, and poppler's
WebAssembly build for `pdftotext` and `pdfinfo`. The package has three places for this and no
more: `from_word.runner`, which runs pandoc another way where it is set;
`lookup.http.default_transport`, which sends one XMLHttpRequest under Pyodide; and
`web.install_programs`, which puts `pdftotext` and `pdfinfo` on Pyodide's PATH and has its
`subprocess.run` run them in WebAssembly (`web/poppler.mjs`), so that the code reading a PDF
is the command line's, given the same program the same way. All three are in
`manuscript_guard.web`, with their tests in `tests/test_web.py`.

```bash
cd web && npm ci && cd ..
pip wheel . --no-deps --wheel-dir dist
python web/build.py --wheel dist/manuscript_guard-<version>-py3-none-any.whl --out _site
python web/test/check.py --site _site --docx <built example .docx> \
    --results <its results .json> --markdown <its manuscript/main.md>
```

The site's root is the project's landing page, `web/landing/`, and the audit page is in its
folder `audit/`. The landing page runs no script and its policy lets it load only its own
pictures, style and video. Its pictures are copied from `docs/img/` as it is built, so the
drawings have one home. `python web/build.py --landing --out _site` builds it alone, with no
wheel and nothing downloaded, to look at.

`web/build.py` puts every file the page loads into `_site/audit/`, from one origin, so that the
policy names no other host: Pyodide from npm (held by `package-lock.json`), the packages
`audit` imports (each held to the SHA-256 Pyodide's lock file gives), pandoc.wasm (held to
`web/pins.json`), the shim that runs it, bundled, poppler's programs (from npm, held by
`package-lock.json` to the package's SHA-512), the wheel, and every licence. pandoc is
GPL-2.0-or-later, and the page links to its source at the version served. poppler is
GPL-2.0-only or GPL-3.0-only: the page serves the package's licence and the notices of the
libraries it is built with, and links to poppler 26.11.0's source and to the recipe that
built the package, at the commit npm's provenance names (ATTRIBUTION.md).

`web/test/check.py` runs the command line's `audit` on the worked example (the `.docx`
against its results, the `.docx` alone, `main.md` alone, with a referee's options, in
American English with the copy with tracked changes asked for, held to a journal's rules
from its form with a double-blind review, the LaTeX project of `tests/data/latex` as a
`.zip` and as a `.tar.gz`, which the command line is given as the folder they hold, and a PDF
of the `.docx`'s text, set by `tests/proof_pdf.py` in two columns with its lines numbered and
an author in its Info dictionary, against its results and held to that journal's rules),
then the same command as the page runs it in Node, each archive unpacked there first by
`web.unpack_paper` as the page unpacks it (`parity.mjs --unpack`), and requires the same
report and the same `--json`. So it does for three comparisons: the example revision with its
letter, a reader's comments and the start of the report, whose text must be the same too
(`parity.mjs --read`); a PDF beside the `.docx`; and two versions of one name, the letter a
`.docx`, each version in the folder the page writes it in. There the command line reads the PDF with the page's own
`pdftotext` and `pdfinfo`, the build the site serves run in Node (`web/test/program.mjs`),
put first on its PATH as shell scripts, so that the two are compared given the same program;
on Windows, which starts no shell script, the command line uses the `pdftotext` on PATH. In
each browser, the page's copy with
tracked changes must track as many corrections as `--tracked` does, and the files the page
makes of the journal's form must be the ones the command line was given. Then it opens the site in
Chrome and in Firefox, served with no policy header as GitHub Pages serves it. The landing
page must load its style and every picture it names and ask no other host. The audit page
must start, print the same reports, send nothing, and refuse every request *Test the rules*
tries. CI's `web` job runs all of this, and `tests/test_web.py` holds the page's pandoc
to CI's and its policy to the hosts `--lookup` asks.

`python web/build.py --wheel <the wheel> --host <folder> --out check` builds the page a
journal's host serves, alone, with no landing page ([hosting the audit
page](hosting-the-audit-page.md)), and `check.py --hosted check` holds it the same way: its
code files must be byte for byte those of `_site/audit/`, the same wheel's page, and for
each journal it offers the `.docx` held to it, chosen from the list, with the authors' boxes
filled for a blind review, must give the report `audit --journal journals/<slug>.yaml` gives.
In each browser it is served at another address than the site's, and must show the host's
name, logo, accent and contact line, keep its release, licences and proof, show each
journal's rules as it serves them, and choose the journal `?journal=<slug>` names, or say it
offers none of that slug. CI builds it with the invented journals of `web/test/host`, outside
the site, and deploys only the site.

`.github/workflows/pages.yml` builds the page from each release, checks it the same way, and
deploys it. It starts when a run of the release workflow finishes, and builds only where that
run tagged a release. Two things are the maintainer's, once: in the repository's settings,
*Pages*, set the source to *GitHub Actions*; then start the workflow by hand with the first
release tag that has a `web/` folder.

Two traps that shaped it:

- **A worker started from a file escapes the page's policy.** GitHub Pages sends no policy
  header, so the policy is in the page itself, and a worker started from a file is under no
  policy at all (tested in Chrome and Firefox). A worker started from a `blob:` URL takes the
  page's. So the checker is started that way, and the rules allow no other kind.
- **Firefox refused the shim's own imports in that worker.** The shim is bundled into one
  module.
