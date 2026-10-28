# Depositing the code and the results

`manuscript-guard package` writes `build/package/<name>/` and a `.zip` of it: the analysis
scripts, the results and their digests, the figure scripts and figures, the plan, the
literature ledger, the lockfiles and the licence, with a README on running it again,
`CITATION.cff`, `BOUND.md` (each result the paper prints, and where) and `INPUTS.md` (every
input the analysis read, and how to obtain the ones that are not there). An input goes in
only when the analysis declared it synthetic or `paper.yaml` lists it in `package.share`; one
declared restricted never does. The tool uploads nothing: depositing is yours.

```bash
manuscript-guard package --dry-run      # what would go in and what would be left out
manuscript-guard package                # the folder and the .zip
manuscript-guard package --ro-crate     # with the files below
```

`BOUND.md` reads a Markdown manuscript and a LaTeX one alike; of a LaTeX one, the `.tex`
files the LaTeX reader follows from each document's entry. The reader stops at the first
part it refuses, and each binding printed after it, in that file or in a file read after
it, is listed with "after a part the reader refused; heading not known" in place of the
section. A `.tex` file it no longer reaches, or that nothing inputs, is not listed. The
package warns of both (`package-bound-not-read`), and names each such file that holds a
binding.

## The files the options add

Each is made from the project's records, holds no date the records do not give and no
address, and is the same bytes from one run to the next and from one folder to another.

| Option | Adds |
|---|---|
| `--citation` | `.zenodo.json`, the metadata a Zenodo record of the package is made from: the authors as "Family, Given" with their ORCID iDs and affiliations, the keywords, the licence, and as related works the DOIs of the data sources `design/data_sources.yaml` chose. Its description is a fixed sentence about the package. It does not carry `package.doi`, which Zenodo would read as a DOI another publisher gave the files. Refused while `authors.yaml` names no author, or one with no name, since Zenodo requires a record's creators. |
| `--ro-crate` | `ro-crate-metadata.json`, the package described as an [RO-Crate 1.1](https://w3id.org/ro/crate/1.1) and a Process Run Crate; `RELATIONS.md`, what the crate does not state and why; `MODELS.md`, each model of the results the package holds as `manuscript-guard models` prints it, and how many models it leaves out with the results it withholds. It implies `--citation`. |
| `--root-citation` | `CITATION.cff` and `.zenodo.json` at the project's root as well, each only where none is there, which is what GitHub and Zenodo's GitHub integration read. One already there, or made while the package was written, is never written over; the fields where it differs from the package's are named, and a write the system refuses is said. It implies `--citation`. |

The package holds the citation files whatever is asked for at the root.

## What the crate states, and what it leaves out

The crate names every file of the package with its SHA-256 and size, the authors by their
ORCID iDs, each run of a script that wrote results, each drawing of a figure, and each input
the package withholds, by the digest the run recorded and with `package.request` as how to
obtain it. Every run and every drawing names its script, as a Process Run Crate requires:
the script in the package, or, where the package does not hold it, an entity with the path
and the digest its record gives. Whether the script is the one its record names is checked
against that digest, and where it is not, `RELATIONS.md` says so. Any other relationship is
stated only where the files show it holds now:

- each input a run read, where the file in the package, or on your computer for one the
  package withholds, has the digest the run recorded;
- the results a run wrote, where the results file has the digest of its `.sha256` file;
- each file a figure's script drew, where it has the digest its `*.render.json` recorded.

Every other relationship is in `RELATIONS.md`: a script edited after its run, an input
changed since, a figure drawn again by hand, and what no record says, such as which results
a figure was drawn from.

`datePublished` is `package.date` where `paper.yaml` gives it, and otherwise the day the
latest results were written. The tool reads no clock, so where neither is there `--ro-crate`
is refused: RO-Crate 1.1 requires the date. A `package.date` that is no day of the
calendar, `2026-02-30`, is refused too.

## A custodian's sign-off

Where the data custodian restricts sending, the package is written only once they have
signed off its files and their digests. The crate and the citation files are files of the
package, so a package with them is signed off apart from one without:
`PACKAGE/custodian/deposit-citation` and `PACKAGE/custodian/deposit-ro-crate`, with
`-with-manuscript` before the suffix for the package that carries the manuscript.
