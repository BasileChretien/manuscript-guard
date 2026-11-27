# Hosting the audit page for your journals

A publisher or a society can serve [the audit page](audit-page.md) on its own site, with its
journals' rules built in and its own name, logo and colours, and link to it from each
journal's "Submit" page. An author then checks a manuscript against the journal's own limits,
sections and statements before submitting it. The page is the project's page, built from a
release: the paper is still read in the author's browser and is never uploaded, to your site
or anywhere else.

Nothing has to change on your side but a folder of static files. There is no server program,
no database and no account; the page needs a web server that serves files, as for any page
of your site.

## What you need

- The manuscript-guard repository at the release you build (`git checkout v<version>`): its
  `web/` folder holds the page and its build.
- Python 3.10 or later with that release installed (`pip install manuscript-guard==<version>`),
  which reads your journals' profiles as the page will, and Node.js 22.
- That release's wheel: `pip download manuscript-guard==<version> --no-deps --dest dist`.
- One [journal profile](journal-profiles.md) for each journal, the file `audit --journal`
  reads. The `journal-profile` skill, or `manuscript-guard journal` and the annotated
  template, start one from the journal's instructions for authors.

## The host folder

```text
our-journals/
  host.yaml
  logo.svg
  journals/
    examples.yaml
    blind-letters.yaml
```

Each journal is a file `journals/<slug>.yaml`, the slug in lower-case letters, digits and
hyphens, and not `other`, which the page's list keeps for "Another journal": it is what a
link names the journal by. A hidden file, `Thumbs.db`, `desktop.ini` and a folder in
`journals/` are passed over; any other file there stops the build. `host.yaml` says who you are:

```yaml
schema: manuscript-guard/host/1
name: "Society of Invented Examples"
logo: logo.svg
accent:
  light: "#7a1f3d"
  dark: "#e7a0b8"
contact:
  text: "Questions about our journals' requirements"
  link: "mailto:editorial@example.invalid"
```

| Key | What the page does with it |
|---|---|
| `name` | Your name, at most 80 characters, in the page's title and at its top, beside the logo. |
| `logo` | A file in the folder, `.svg`, `.png` or `.webp`, at most 512 KB, shown beside the name. Optional. |
| `accent` | Your colour for links, buttons and ticks, `#rrggbb`, one for a light screen and one for a dark one. Each must have a contrast of 4.5:1 or more with the page's paper, its cards and a button's text, or nothing is built. Optional: without it the page keeps its own teal. |
| `contact` | One line at the page's foot, your name, the `text` and one `link`, `mailto:` or `https://`. Optional. |

Only `schema` and `name` are required, and no key but these is taken. The page shows each as text, never as
markup.

## Building it

From the repository's root, with `web/` set up once (`cd web && npm ci`):

```bash
python web/build.py --wheel dist/manuscript_guard-<version>-py3-none-any.whl \
    --host our-journals --out check
```

`check/` is then the page, ready to copy to your site. The build reads every file of the host
folder before it builds anything, and refuses it, naming the file and why, where anything is
wrong: a profile the journal schema does not take, two journals of the same name, a key
`host.yaml` does not have, a logo that is not the picture its extension says, an accent your
text would not be read against, a link that is neither an e-mail address nor `https://`. It
also refuses to build with another release of manuscript-guard installed than the wheel's,
whose schema the page would hold the profiles to. `--out` is emptied first, so it may not
be the host folder, hold it, or be in it.

To check your build as CI checks the project's, build the same wheel's page without
`--host` as well, and the worked example, then run `web/test/check.py` with `--hosted check`
beside the options it always takes
([how the page is built and checked](audit-page.md#how-it-is-built-and-checked)). Your
page's code is then held to that page's, and each of your journals, in Node, Chrome and
Firefox, to what `manuscript-guard audit paper.docx --journal journals/<slug>.yaml` says of
the worked example.

## Serving it

Copy the folder where you want the page, `https://www.example.org/check/` say. The server
must send `.wasm` as `application/wasm` and `.mjs` and `.js` as `text/javascript`; most do.
The page is about 81 MB of files, nearly all of it Python, pandoc and poppler compiled for
the browser, and a first visit fetches about 28 MB when the server compresses what it sends, as
GitHub Pages does; after that the browser has it in its cache.

The page's rules are in the page itself, as on GitHub Pages: no header is needed. A
Content-Security-Policy your server adds can only narrow them, never widen them.

Link to it from each journal's "Submit" page with the journal's slug:

```text
https://www.example.org/check/?journal=examples
```

The page then opens with that journal chosen. It reads `journal` from its address and
nothing else, and never writes to its address; a slug it does not have is said, and no
journal is chosen. The slug reaches your server's logs, as any address does. Nothing of the
paper is ever in an address.

## What an author sees

"Which journal are you submitting to?", above the paper's box, lists your journals by name,
with "None" and "Another journal" beside them. The journal chosen holds the paper to its
profile, `audit --journal` with that file: its limits, the sections and statements it
requires, what a .docx holds besides its text, and in a blind review each place an author is
named. Its rules can be read on the page as the check reads them. Where the profile says the
review is double- or triple-blind, the boxes for the authors' names, ORCID iDs, e-mail
addresses and affiliations appear under the list. "Another journal" opens the form an author
fills from any journal's instructions, as on the project's own page. Nothing is remembered
between visits.

## What you can change, and what stays

You set the name, the logo, the accent and the contact line, and offer your journals. The
rest is the project's page, and stays:

- "Run by manuscript-guard <version>", at the top, with a link to what that release changed.
- "It all runs on this computer. Your paper is never uploaded.", and the ways to see it:
  *Test the rules*, `files.sha256`, and *What this page loaded and sent*.
- The Questions, the referee's options and the rest of the page.
- The licences at its foot, with pandoc's GPL-2.0-or-later and a link to pandoc's source at
  the version the page serves, and poppler's GPL-2.0-only or GPL-3.0-only, with links to
  poppler's source and to how it was built, and the notices of the libraries in it.
  pandoc.wasm and poppler's programs are GPL software, and a site that serves them
  distributes them: the page's links to their source and the licence files are how that is
  kept.

Your files go in as data. The page's code, `index.html`, `app.js`, `worker.js` and
`style.css` among it, is byte for byte the code of the page built from the same release
without a host, and CI holds that. So anyone can compare your page's `files.sha256` with the
one a build of the same release without `--host` writes: every line is the same but
`manifest.json` and your own files under `journals/` and `host/`.

## How an author can see that nothing is uploaded

The same three ways as on the project's page ([audit-page.md](audit-page.md#how-to-see-that-nothing-is-uploaded)),
of which the first is the plainest: once the page says *Ready*, turn off the network, and the
audit runs all the same. Your journals' profiles are among what it loaded.

On your site the page's own host is your server. Its rules let it send requests there, which
it needs to load its files; once loaded it sends nothing there, and the network test shows
it. A host could change the page's code after building it, and no rule of the page would
stop that. The comparison of `files.sha256` above shows it, and the network test still
holds.

## Keeping it current

A journal's instructions change without notice, and a profile records the day it was read:
the report says when a profile is over a year old. Build the page again when a journal's
instructions change, and with each release of manuscript-guard you take up. A page is the
release it was built from, until you build it again.
