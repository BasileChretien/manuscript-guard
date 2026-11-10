# The audit page

<https://basilechretien.github.io/manuscript-guard/audit/> runs `manuscript-guard audit` inside a
web browser, for a reader who will not open a terminal: a clinician checking a colleague's
draft, an editor, a referee. The paper is read in the browser and is not uploaded. There is
no server behind the page, only static files on GitHub Pages, so there is nothing to upload
it to.

The page is built from each release, so it runs the same version as `pip install
manuscript-guard`, with the same checks. CI holds its reports to the command line's, word for
word (below).

## What it checks

A `.docx` or Markdown paper, with the analysis outputs to compare its numbers with if the
reader has them (`.json`, `.csv`, `.tsv`, `.txt`, `.yaml`). That is everything
[`audit`](commands.md#checking--audit) reads in a paper of that kind:

- the numbers against the outputs, and what a match is worth there;
- the arithmetic, the Abstract against the Results, and the small cells a total gives away;
- the words, by G6 and G14, through pandoc's WebAssembly build of the version CI tests with;
- the reference list (G7), and with the box ticked, whether a cited work was retracted or is
  in no registry.

The page draws the report: what each check found, in a table; the findings on the words, a
fold for each kind with every place inside it and the kind's hint; and the other sections
with something to show. Below, in a fold, is the text the command line prints, word for
word, which "Save the report" saves. The box "List every place of every finding" gives the
text every place with its context and hint, and the page every section and every place's
context (`audit --details`). For a .docx, "Save the paper with the findings as Word
comments" saves a copy of it with each finding as a comment at its place, written from the
same audit, as `audit --commented` writes it; it is made in the browser like the rest.
"English of the paper" is `--english`, and "Words to leave alone", split at spaces and
commas, is `--known`: names, initials and the field's terms G14 then neither asks to be
defined, reports the spelling of, nor reads as names from code.

It does not read PDFs, which need `pdftotext`, a program a browser cannot start. Nor does it
read LaTeX projects of several files, figures, or reproducibility packages: the command line
reads those.

## How to see that nothing is uploaded

Three ways, from the simplest:

1. **Turn off the network.** Once the page says *Ready*, everything it needs is loaded.
   Unplug the cable or turn off Wi-Fi, then choose the paper: the audit runs all the same.
   Only the reference lookups need the network, and they say they could not reach the
   registries.
2. **Read its rules, or have the browser test them.** The first rule in the page's source is
   its [Content-Security-Policy](https://developer.mozilla.org/docs/Web/HTTP/Guides/CSP), which
   the browser enforces. It lets the page send requests only to the address it was loaded
   from and to the five registries the lookups ask (Crossref, OpenAlex, DataCite, doi.org,
   PubMed), and to start no worker from a file, load nothing into a frame, and send no form.
   The page's *Test the rules* button tries seven requests the rules forbid, from the page and
   from the checker, and shows each one refused.
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

They are off until the box is ticked. Ticked, they send the DOIs and PubMed IDs the paper's
reference list cites, and nothing else, as `audit --lookup` does. A page cannot do three
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
Worker; pandoc.wasm, from the pandoc release CI pins, stands in for pandoc. The package has two
places for this and no more: `from_word.runner`, which runs pandoc another way where it is
set, and `lookup.http.default_transport`, which sends one XMLHttpRequest under Pyodide. Both
are in `manuscript_guard.web`, with their tests in `tests/test_web.py`.

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
`web/pins.json`), the shim that runs it, bundled, the wheel, and every licence. pandoc is
GPL-2.0-or-later, and the page links to its source at the version served.

`web/test/check.py` runs the command line's `audit` on the worked example (the `.docx`
against its results, the `.docx` alone, `main.md` alone), then the same command as the page
runs it in Node, and requires the same report and the same `--json`. Then it opens the site in
Chrome and in Firefox, served with no policy header as GitHub Pages serves it. The landing
page must load its style and every picture it names and ask no other host. The audit page
must start, print the same reports, send nothing, and refuse every request *Test the rules*
tries. CI's `web` job runs all of this, and `tests/test_web.py` holds the page's pandoc
to CI's and its policy to the hosts `--lookup` asks.

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
