# How often a warning is wrong

manuscript-guard was run over real papers that nobody wrote for it, and the warnings it gave were judged true or false against each paper's text. This page gives, for each kind of warning, its code, the share judged false: how far an editor, a referee or an author can take a warning of that kind on trust. It counts warnings and failures only. A note or a question accuses nothing, and the notices that say how a paper was read say nothing about the paper.

Measured with manuscript-guard 0.2.503 (commit `8f4629a2f`), in the corpus's run `main-8f4629a2f`, on 98 papers, and counted on 2026-11-25. The verdicts read are 2,547 from the first judging and 1,182 from the later batches; left out: 19 verdicts on papers found after judging not to be manuscripts; 12 problems a judge noticed that no warning raised; 7 warnings a judge could not settle from the text. The page is drawn by `tools/false_alarms.py` from [its counts](false-alarms.yaml), which hold no paper's text, and is drawn again whenever a new run of main becomes the base of the corpus gate ([Measuring the gates on real papers](corpus.md)).

## In all

By command, `audit` first: it is the one an editor or a referee runs on a paper they did not write. `check` reads a paper brought into a project, and `compare` two versions of it.

| command | papers | warnings | in papers with a verdict | judged | false | share false | 95% interval |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `audit` | all, 95 | 1,047 | 1,022 | 981 | 178 | 18% | 14% to 23% |
|  | Word, 42 |  | 458 | 441 | 50 | 12% | 8.0% to 17% |
|  | PDF, 33 |  | 316 | 314 | 96 | 31% | 21% to 41% |
|  | LaTeX, 20 |  | 248 | 226 | 32 | 13% | 7.5% to 20% |
| `check` | all, 59 | 4,026 | 3,765 | 673 | 97 | 2.7% | 1.2% to 9.5% |
|  | Word, 39 |  | 376 | 369 | 61 | 16% | 12% to 23% |
|  | LaTeX, 20 |  | 3,389 | 304 | 36 | 1.2% | 0.5% to 5.3% |
| `compare` | all, 6 | 58 | 54 | 40 | 13 | 24% | 8.3% to 52% |
|  | LaTeX, 6 |  | 54 | 40 | 13 | 24% | 8.3% to 52% |

*Papers* are those with a judged warning from the command; *warnings*, all the command gave about the papers; *in papers with a verdict*, those of a code in a paper where a warning of that code was judged, which the share is of. The share weighs each paper's judged warnings of a code by all its warnings of that code, so a code that gives many warnings weighs much. `check`'s leave out the warnings every new project gives before anyone writes in it, an empty analysis plan say, which are about the project and not the paper. Of `check`'s 3,765 warnings in papers with a verdict, 3,196 are `G7/reference-uncited`, so its share is mostly that code's.

## By code

A code's share is given where 10 or more of its warnings were judged, from 3 papers or more. What each code says is in [What is checked](gates.md) and [Auditing a paper](audit.md).

| code | given by | warnings | judged | false | share false | 95% interval | papers |
| --- | --- | ---: | ---: | ---: | ---: | ---: | --- |
| `G3/figure-colours-confused` | check | 88 | 88 | 15 | 17% | 3.8% to 43% | 7 (LaTeX 7) |
| `G6/ai-cadence` | audit, check | 57 | 28 | 3 | 11% | 0% to 27% | 19 (Word 16, LaTeX 3) |
| `G6/ai-phrasing` | audit, check, compare | 130 | 130 | 26 | 20% | 8.8% to 34% | 41 (Word 17, PDF 16, LaTeX 8) |
| `G6/vague-attribution` | audit | 21 | 14 | 9 | 64% | 27% to 94% | 9 (Word 3, PDF 3, LaTeX 3) |
| `G7/entries-not-told-apart` | audit | 18 | 18 | 1 | 5.6% | 0% to 26% | 18 (PDF 13, LaTeX 5) |
| `G7/novelty-unsearched` | check | 32 | 31 | 5 | 16% | 2.7% to 35% | 17 (Word 14, LaTeX 3) |
| `G7/reference-uncited` | check | 3,216 | 112 | 13 | 0.6% | 0.1% to 4.4% | 19 (Word 7, LaTeX 12) |
| `G14/abbreviation-redefined` | audit, check, compare | 491 | 483 | 71 | 15% | 7.6% to 25% | 61 (Word 23, PDF 24, LaTeX 14) |
| `G14/abbreviation-unused` | audit, check, compare | 513 | 278 | 40 | 13% | 8.1% to 20% | 70 (Word 28, PDF 27, LaTeX 15) |
| `G14/abbreviation-used-before-defined` | audit, check, compare | 183 | 166 | 55 | 33% | 22% to 47% | 33 (Word 22, LaTeX 11) |
| `G14/code-name-in-prose` | check | 43 | 43 | 4 | 9.3% | 0% to 36% | 9 (Word 6, LaTeX 3) |
| `G14/notation-p-symbol` | audit, check | 20 | 20 | 2 | 10% | 0% to 30% | 10 (Word 10) |
| `G14/notation-sign-spacing` | audit, check | 43 | 37 | 2 | 5.3% | 0% to 18% | 19 (Word 14, PDF 4, LaTeX 1) |
| `G14/notation-unit` | audit, compare | 25 | 18 | 6 | 33% | 12% to 58% | 17 (Word 5, PDF 9, LaTeX 3) |
| `G14/spelling-mixed` | audit | 17 | 10 | 1 | 10% | 0% to 40% | 10 (Word 7, PDF 3) |
| `G14/spelling-variant` | audit, check, compare | 154 | 147 | 14 | 9.2% | 3.9% to 15% | 40 (Word 20, PDF 12, LaTeX 8) |
| `audit/does-not-fit` | audit | 13 | 13 | 0 | 0% | 0% to 23% | 7 (Word 4, PDF 3) |

## Codes with too few judged warnings

Fewer than 10 judged, or from fewer than 3 papers: too few to say what share is false.

| code | given by | warnings | judged | true | false | papers |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| `G2/code-block-unread` | check | 1 | 1 | 1 | 0 | 1 |
| `G5/guideline-claimed-not-declared` | check | 5 | 5 | 4 | 1 | 5 |
| `G6/model-artefact` | audit | 2 | 2 | 0 | 2 | 2 |
| `G6/revision-residue` | audit | 5 | 3 | 1 | 2 | 2 |
| `G7/citation-beyond-list` | audit | 1 | 1 | 0 | 1 | 1 |
| `G7/entry-never-cited` | audit | 8 | 8 | 6 | 2 | 3 |
| `G8/p-decision-error` | check | 1 | 1 | 1 | 0 | 1 |
| `G8/p-inconsistent` | check | 5 | 5 | 5 | 0 | 4 |
| `G12/registration-undeclared` | check | 1 | 1 | 1 | 0 | 1 |
| `G14/notation-percent` | audit | 15 | 8 | 8 | 0 | 8 |
| `G14/notation-space-missing` | audit | 2 | 2 | 1 | 1 | 2 |
| `BUILD/tex-not-input` | check | 7 | 7 | 5 | 2 | 2 |
| `audit/sum-off` | audit | 1 | 1 | 1 | 0 | 1 |
| `compare/claim-moved` | compare | 2 | 2 | 0 | 2 | 1 |
| `compare/claim-stronger` | compare | 7 | 7 | 1 | 6 | 2 |
| `compare/claim-weaker` | compare | 4 | 4 | 2 | 2 | 2 |

Every code that gave a warning has a judged one.

## Papers held out from the tuning

The rules were changed, pull request by pull request, against the verdicts above, so on those papers they look better than they are. Another 48 papers are held out: they are measured at the end of a stage of the work only, never shown to whoever changes a rule, and joined to the tuning papers after three such measures. Their shares are given by command and format, not by code, which would show where to look.

Measure 1, with manuscript-guard 0.2.502 (commit `77abd45db`), in the run `main-77abd45db`:

| command | papers | warnings judged | false | share false | 95% interval |
| --- | --- | ---: | ---: | ---: | ---: |
| `audit` | all, 40 | 343 | 157 | 46% | 37% to 54% |
|  | Word, 10 | 95 | 38 | 40% | 27% to 50% |
|  | PDF, 12 | 144 | 88 | 61% | 48% to 76% |
|  | LaTeX, 9 | 73 | 26 | 36% | 16% to 47% |
|  | Markdown, 9 | 31 | 5 | 16% | 0% to 34% |
| `check` | all, 17 | 237 | 28 | 12% | 4.2% to 30% |
|  | Word, 9 | 51 | 22 | 42% | 20% to 59% |
|  | LaTeX, 8 | 186 | 6 | 3.2% | 1.2% to 9.2% |

## The papers

The tuning papers are openly licensed preprints and articles, most of them in English, found on PubMed Central 24, arXiv 20, PsyArXiv 13, SocArXiv 11, Zenodo 11, EdArXiv 9, OSF Preprints 6, SportRxiv 3, MetaArXiv 1. They stay out of this repository, since few of their licences allow passing them on. The held-out papers are given by format alone: a field or a source beside it could name the paper.

| format | tuning | held out |
| --- | ---: | ---: |
| Word | 45 | 12 |
| PDF | 33 | 12 |
| LaTeX | 20 | 12 |
| Markdown | 0 | 12 |

| field of the tuning papers | papers |
| --- | ---: |
| medicine | 15 |
| psychology | 15 |
| sociology | 12 |
| education | 10 |
| biology | 5 |
| astrophysics of galaxies | 4 |
| machine learning | 4 |
| econometrics | 4 |
| multidisciplinary | 4 |
| populations and evolution | 4 |
| applied statistics | 4 |
| pharmacoepidemiology | 3 |
| public health | 3 |
| sport science | 3 |
| ecology | 2 |
| chemistry | 1 |
| computer science | 1 |
| research on research | 1 |
| nursing | 1 |
| nutrition | 1 |
| pharmacology | 1 |

## What these shares do not measure

- **Warnings never given.** Only what the tool said was judged. A problem in a paper that no rule flagged is counted nowhere, so this page says nothing of how much the tool misses. The judges noted 12 such problems in passing, but they were not asked to look for them, and that number is no measure of what is missed.
- **Papers unlike these.** The papers above are mostly preprints, from the fields listed, and most are in English. A journal's typeset PDF, a field with notation of its own or another language may fare worse. The held-out PDFs are articles as journals typeset them: compare their share with the tuning PDFs'.
- **The same papers tuned on.** A share above is of the papers the rules were corrected against, and flatters them; the held-out shares show by how much.
- **Who judged.** Model judges, each given the paper's text and one written brief of what each code claims: in the first judging one judge for each field, and in the later batches two judges blind to each other, the findings they split on decided by the toolkit's author, who also read 20 of their agreements once. No editor judged them.
- **True but minor.** A warning judged true is one whose statement about the text holds. It may still not be worth an author's time.
- **A sample of each paper.** The first judging took at most ten warnings of each code in each report, spread through its list, and a paper's judged warnings stand for its others of the code. A code's warnings in a paper with none judged count among its warnings and not in its share.
- **The interval.** It is the wider of two: the papers drawn again 2,000 times with replacement, which allows for false alarms that cluster in a few papers, and Wilson's score interval at the share and the number judged, which still has a width where no judged warning was false. Both treat the papers as drawn at random from papers like them, which they were not.

## Drawing it again

```bash
python tools/corpus.py counts <run>      # docs/false-alarms.yaml, from the corpus
python tools/false_alarms.py             # this page and the README's line
```

The held-out section is counted again only at a measure of the held-out set, with `--heldout <folder> <run> --milestone <n>`; otherwise `counts` keeps it as it stands.
