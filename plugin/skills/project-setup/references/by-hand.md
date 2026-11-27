# Setting up by command, and what `init` writes

What `manuscript-guard setup apply` runs for the authors, and how an author who prefers the
commands does the same by hand. The conversation of SKILL.md asks every decision below and
writes each through `setup`; this page is for the author who asks for the commands, and for
what `init` does that the conversation does not ask about.

## Scaffold

```bash
manuscript-guard init my-paper --title "Working title"   # a new project
manuscript-guard init . --title "Working title"          # an existing analysis repository
manuscript-guard init my-paper --title "Working title" --latex   # the manuscript in LaTeX
manuscript-guard init my-paper --title "Working title" --english en-US   # American spelling
manuscript-guard init my-paper --from paper.docx         # a paper written in Word
```

`--from` writes the Word paper as `manuscript/main.md`: each table a pipe table where its
cells hold only paragraphs, the pictures in `manuscript/media/`, the title from Word's Title
style in `paper.yaml`, each name of its Author style in `authors.yaml`, unsplit, and what
stands before the first heading in a comment at the top, which no gate reads. A typed APA
reference list goes to `literature/references.bib`, entry by entry where each field reads
exactly, and each typed citation that names exactly one entry by its authors and year
becomes `[@key]`. Read what it prints with the authors: the tables it left as grid tables,
whether the comment holds an abstract or text that belongs to the paper, and the entries
and citations it left as typed, each with its line and why, which they cite by hand. A
numbered reference list is left as typed. `sync-bib` writes `references.bib` again from
Zotero, so import the file into Zotero first. A `.doc` is refused; save it as `.docx`.

Ask the authors whether they write the manuscript in Markdown or in LaTeX, and in British
(`en-GB`) or American (`en-US`) spelling, before running it. Without `--english`, `init`
declares none, and G14 holds the paper to the English its spellings show.
With `--latex` the manuscript is `manuscript/main.tex`, which declares its class and loads
`mgvalues`, with `mgvalues.sty` beside it, in place of `main.md`. A project is one or the
other: `init --latex` makes nothing where `manuscript/` holds Markdown, and `check` fails a
Markdown file in a LaTeX manuscript (`other-format-file`).

It never overwrites an existing file, so the second form adds manuscript-guard to a
repository that already holds an analysis, with `paper.yaml` at its root. That also means
an existing `.gitattributes`, `.gitignore` or `README.md` is left as it was. Where the
`.gitignore` lacks `build/` or `literature/sources/*` (the stored copies of cited works,
paywalled papers among them; not asked where `paper.yaml` says `sources_in_git: true`), or
the `.gitattributes` lacks `* text=auto eol=lf` or a line for `*.svg`, `init` prints the
lines to add: add them by hand, and the binary lines of the `.gitattributes` it writes for a
new project with them. An
existing `AGENTS.md` is left too, and where it does not mention manuscript-guard `init`
prints the rules to add to it. And `results/` belongs to
manuscript-guard: every `.json` directly
in it is read as a results fragment and fails the schema if it is not one, and `verify`
empties the whole directory in its scratch copy. If the analysis already keeps its own
output there, either move that output, or set `paths: {results: <dir>}` in `paper.yaml`
and give each emitter's `write()` its own `.json` file in that directory
(`em.write("<dir>/01_model.json")`, `em$write("<dir>/01_model.json")`). Without an argument
the emitters write `results/<script>.json` and never look at `paths.results`. It creates:

```
paper.yaml             stage, English variant, target journal, reporting guideline
authors.yaml           authors, affiliations, CRediT roles, funding, competing interests
design/plan.md         the analysis plan
analysis/              scripts that publish results through the emitter
results/               machine-written; never edited by hand
literature/            ledger.yaml, attested.yaml, references.bib, sources.yaml, sources/
manuscript/main.md     prose with {{results.x}}, {{lit.y}}, [@citekey]
                       (main.tex and mgvalues.sty under --latex, with \mg{results.x})
figures/  review/  build/
.gitattributes         * text=auto eol=lf, and *.svg binary among the files kept as bytes
AGENTS.md              the rules of the project, for any agent working in it
```

**Keep the `.gitattributes`.** Every digest is byte-exact, and a checkout that turns line
endings into CRLF makes clean results look hand-edited. An SVG figure is kept as bytes: svglite
on Windows writes CRLF, and normalised to LF the figure is no longer the one its render record
and its review hold.

**`literature/sources/` stays out of git.** The `.gitignore` leaves out the copies of the
cited works, paywalled papers among them, which a public repository would publish;
`literature/sources.yaml`, which `sync-sources` writes, records them and is committed. CI
then notes each quote it could not hold to its copy. Whether a private repository commits
them (`literature: {sources_in_git: true}` in `paper.yaml`) is the user's choice.

Then fill in, in this order:

1. **`authors.yaml`**: every author's `given` and `family` name and affiliations, taken
   from the author, never from what you know about anyone. The placeholder affiliation
   passes validation, so nothing will remind you to replace it. Ask each author for their
   own `funding` (each grant with its identifier, as "Agence Nationale de la Recherche
   (ANR-20-CE17-0001)"), `competing_interests` ("None declared." where there are none) and
   `credit` roles, and the ethics lead for the approval's reference
   (`roles: {ethics_lead: {author: <them>, approval: <reference>}}`). None of them is
   required, but once filled G4 holds the manuscript's Funding, Competing interests, Ethics
   and Author contributions text to them (a warning until submission, a failure there), so
   never fill one from what you know about anyone: an entry you guess is one the paper is
   then held to. An empty `competing_interests` beside a filled one is reported, since an
   empty field is not a declaration of none; a missing ORCID is left out without comment.
   Ask who the statistician
   is, and write them under `roles:` (`statistician: <family name or ORCID iD>`): a G15
   warning left standing is theirs to sign off, with `manuscript-guard sign --as <them>
   --finding <id>` as its hint says. Never run `sign` for them.
2. **`paper.yaml`**: the title, `english_variant` (`en-GB` or `en-US`; ask, do not
   assume: G14 holds the manuscript's spelling to it. `init --english en-US` writes it at
   the start. Left out, G14 holds the paper to the English its spellings show, the
   document is built as English with no region, and where the journal's profile names an
   English G4 notes `english-variant-undeclared`: ask the author which English, and
   declare it), and the reporting
   guideline under the key `reporting_guideline` (singular, a list). Any key the schema does
   not know is a failure at every stage. The title, the short title and the keywords are
   read as Markdown, and TeX in them is kept only between dollar signs: write
   `IFN-$\gamma$`, since `IFN-\gamma` would be printed `IFN-`, and `check` fails it.
   Ask whether the authors have published on this before. Each such paper goes in
   `literature/related.yaml` (the related-outputs skill), and with the authors' own copy
   stored as `literature/sources/<citekey>.pdf`, G7 reports the passages the manuscript
   repeats from it before the journal's similarity check does.
3. **`design/plan.md`**, before the analysis. The
   [analysis-plan](../../analysis-plan/SKILL.md) skill covers it.
