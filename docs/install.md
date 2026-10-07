# Installing and upgrading

The short version is in the [README](../README.md#install). This page has the rest:
upgrading, what each optional tool is needed for, and the R emitter.

Not on PyPI yet, so install from the repository:

```bash
git clone https://github.com/BasileChretien/manuscript-guard
pip install ./manuscript-guard
```

Or without cloning:

```bash
pip install git+https://github.com/BasileChretien/manuscript-guard
```

`pipx install ./manuscript-guard` works too, and is the better choice if you want the
command available everywhere without touching a project's environment.

Check it:

```bash
manuscript-guard --version
manuscript-guard stages
```

The package and the plugin carry one version number, raised after every change to either, so
`manuscript-guard --version` names the release you have. To take a newer one:

```bash
pip install --upgrade git+https://github.com/BasileChretien/manuscript-guard
```

With pipx, `pipx upgrade` refuses a copy installed from git (it checks a package index, not
the repository), so reinstall instead:

```bash
pipx install --force git+https://github.com/BasileChretien/manuscript-guard
```

If pip says the requirement is already satisfied although the repository is ahead, the version
did not rise with that commit, and only a reinstall takes it:
`pip install --force-reinstall git+https://github.com/BasileChretien/manuscript-guard`.

The plugin's skills describe the commands of the release they came with, so keep the two
together (see [the plugin](agent-tools.md#the-claude-code-plugin)). When the plugin is newer
than the installed command line tool, its session-start hook says so, once, with the upgrade
command, and blocks nothing. That warning comes from the tool itself, so a copy older than
0.2.260 cannot give it: upgrade such a copy once, by hand.

To work on the toolkit itself, install it editable with the test dependencies:

```bash
pip install -e ".[dev]"
pytest -q
```

## What else you need, and when

Only Python 3.10+ and two small libraries are required. Everything below is needed for one
particular thing, and the tool tells you which when you reach it.

| | Needed for | Without it |
|---|---|---|
| **pandoc** | `build`, `submit`, and what `check` says of TeX in the text | You cannot produce a .docx. Every gate still runs but that one finding: `check` passes, and says in a note that the build judges TeX in the text |
| **Zotero + Better BibTeX** | live citation fields, `sync-bib` | Builds fall back to the committed `references.bib`; citation-key pinning goes unchecked |
| **poppler** (`pdftotext`) or **pypdf** | reading PDF sources and PDF figures | Those sources are reported as unverifiable rather than passed |
| **R** (+ `jsonlite`, `digest`) | emitting results from R | Only if your analysis is in R; the Python emitter needs nothing extra |
| **matplotlib** | the worked example's figure | Only for the example |
| **A model provider's API key, or Ollama** | `review --run` | The panel is read by people or an agent, and each reading filed with `review --record` |

Nothing is fetched during installation. Reporting checklists are downloaded on request by
`manuscript-guard fetch`, never as an install side effect — see
[ATTRIBUTION.md](../ATTRIBUTION.md) for why. One file in the package is derived from
somebody else's work: the list of spellings G14 reads comes from VarCon and carries its
notices, and the same file says how.

## The R emitter (only if your analysis is in R)

An analysis in R publishes its results through a small package that lives in this repository,
`r/manuscriptguard`. It is not on CRAN:

```r
install.packages("remotes")    # if you do not have it
remotes::install_github("BasileChretien/manuscript-guard", subdir = "r/manuscriptguard")
```

`install_github` also installs `jsonlite` and `digest`. From a clone,
`R CMD INSTALL r/manuscriptguard` does the same once those two are installed. Then, run from
the project root:

```r
library(manuscriptguard)
em <- mg_emitter("analysis/02_model.R", inputs = "data/cohort.csv")
em$value("model.n", 412L)
em$interval("model.or", 2.5, 1.8, 3.4, digits = 2)
em$write()
```

The fragment lands in `results/`, and `manuscript-guard check` reads it like one from Python.

[Back to the README](../README.md)
