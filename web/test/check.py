"""Hold a built audit page to the command line, and open the site's landing page.

    python web/test/check.py --site _site --docx build/manuscript.docx \\
        --results results/01_disproportionality.json --markdown manuscript/main.md \\
        [--hosted check]

For each case (the .docx against the results, the .docx alone, the Markdown alone, the
.docx against the results under names a reader may give them, outside ASCII and with
spaces, under names that start with "-", against two outputs whose names the page once
made one, with a referee's options set, with the copy with tracked changes asked for,
held to a journal's rules typed in the page's form, its review double-blind, a LaTeX
project as a .zip and as a .tar.gz, which the command line is given as the folder they hold,
and a PDF of the .docx's text against the results and held to that journal's rules), the
command line's `audit` is run here, then the same command is run as the page runs it,
in Node (`parity.mjs`): its report, what it says on stderr, its exit code and its `--json`
must be the command line's. So must each comparison (`compare`) "Compare a revision"
runs: the example revision the page offers with its letter, comments and the start of the
reader's report, whose text must be the command line's as well; a PDF beside the .docx; and
two different files of one name, the letter a .docx, with the start of the report, each
version in a folder of its own as the page writes it (worker.js `compared`). Where the copy
with tracked changes is asked for, the command line's `--tracked` says how many corrections
it tracks, and the page's copy must track as many. Where the journal's form is filled, the
command line is given the files `journal_form` makes of it, and the page must make the same,
dated the day it runs the case. Then the site is opened in each browser named
(`browser.mjs`): the landing page must load its style and pictures and ask no other host,
and the audit page must start under its own policy, give the same report, notes and exit
code for each case from the files as chosen, send nothing, and refuse every request "Test the
rules" tries.

With `--hosted`, a page web/build.py built for a journal's host (`--host`) is held the same
way. Its code files must be byte for byte the code of the page in `--site`, built from the
same wheel: what a host adds is data alone. For each journal it offers, the .docx held to that
journal, chosen from its list, and for one whose review is blind with the authors given in
its boxes, must give the command line's report given the profile the page serves as
`--journal journals/<slug>.yaml`. In each browser the hosted page is served at another
address than the site's, and must show the host's name, logo, accent and contact line, keep
the release it runs, its licences and the proof that nothing is uploaded, preselect the
journal a link names with `?journal=<slug>`, and say so where it offers none of that slug.

The command line here must be the one the wheel was built from, with the pandoc the page's
pandoc.wasm is (pins.json), which is what CI's `web` job and the Pages workflow install. It
reads a PDF with the pdftotext and pdfinfo the page runs, the build the site serves, run in
Node (`program.mjs`): each is put first on PATH for it as a shell script, and
MANUSCRIPT_GUARD_POPPLER, which would name another, is left out. Windows starts no shell
script, so there the command line reads a PDF with the pdftotext on PATH, and the PDF cases
are the same only where that is one that runs the page's build.

The PDF is the built .docx's text, as pandoc gives it in plain text, set in two columns with
a running head, its pages numbered, its lines numbered in the margin and an author in its
Info dictionary, by tests/proof_pdf.py, which no tool on the machine has to be: so that each
of the ways `audit` reads a PDF is run, the line numbers read, the lines rebuilt into
paragraphs (-bbox-layout) and its Author read (pdfinfo) where the review is blind.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tarfile
import tempfile
import zipfile
from datetime import date, timedelta
from pathlib import Path

TEST = Path(__file__).resolve().parent
#: The folder of the site the audit page is in (AUDIT in web/build.py).
AUDIT = "audit"


def node_found() -> str:
    """Node as PATH finds it, named whole, so that the scripts the command line runs from each
    case's own folder find it too; "node" where PATH has none. A path PATH gives relative (an
    entry relative to the folder this is run in, an empty one, one through `..`) is read as
    the system reads it from here: on Windows, `..` taken off by its text and a drive's own
    folder put in, as `abspath` does; elsewhere joined as it is, `..` read past a symbolic
    link."""
    found = shutil.which("node")
    if not found:
        return "node"
    if os.path.isabs(found):
        return found
    return os.path.abspath(found) if os.name == "nt" else os.path.join(os.getcwd(), found)


NODE = node_found()
#: A paper and an output named as a reader may name them. The page once wrote each file
#: under its name made ASCII, so two such names became one file (round 1 of #527).
PAPER, OUTPUT = "Mon article (v3).docx", "résultats 結果.json"
#: Names that start with "-", which the page gives the command as `./name`, and two outputs
#: that were one file under the names made ASCII (round 2 of #527).
DASHED_PAPER, DASHED_OUTPUT = "-paper.docx", "-results.json"
ALIKE = ("résultats.json", "rèsultats.json")
#: A referee's options, as the command line takes them and as the page's boxes are set for
#: them (their ids in index.html), in the order worker.js puts them in the command.
REFEREE = (["--design", "trial", "--whole-numbers", "Age", "--non-negative", "Reports",
            "--minimum-cell-count", "5"],
           {"design": "trial", "wholenumbers": "Age", "nonnegative": "Reports", "mincount": "5"})
#: The worked example is in British English: in American, G14 has spellings to correct.
TRACKED = (["--english", "american"], {"english": "american", "tracked": True})
#: A journal's rules and the authors to look for in a double-blind review, as the page's form
#: is filled for them (its boxes' ids), and as `journal_form` takes them, the date the
#: instructions were read on today's, as the page gives it.
JOURNAL_BOXES = {"jname": "Journal of Examples", "jabstract": "200", "jtables": "1",
                 "jsections": "Introduction\nMethods\nResults\nDiscussion",
                 "jst-funding": True, "jst-data-availability": True, "jst-use-of-ai": True,
                 "jsh-funding": "Financial support or Funding",
                 "jblinding": "double", "author-1-given": "Ada", "author-1-family": "Example",
                 "affiliations": "Department of Examples"}
JOURNAL_FORM = {"name": "Journal of Examples", "url": "", "date": "",
                "limits": {"abstract_words": "200", "tables": "1"},
                "sections": ["Introduction", "Methods", "Results", "Discussion"],
                "abstract_headings": [], "statements": ["funding", "data-availability",
                                                        "use-of-ai"], "blinding": "double",
                # The heading a box was given, and those left empty, as the page sends them.
                "headings": {"funding": "Financial support or Funding", "data-availability": "",
                             "use-of-ai": ""}}
AUTHORS_FORM = {"authors": [{"given": "Ada", "family": "Example", "orcid": "", "email": ""}],
                "affiliations": ["Department of Examples"]}
JOURNAL = (["--journal", "journal.yaml", "--authors", "authors.yaml"], JOURNAL_BOXES)
#: How many days a run may reach, from the one it starts on: a run ends within hours, so it
#: crosses midnight once at most.
DAYS = 2
#: A LaTeX project as the page is given it, and the folder the command line is given, which
#: is the one the page unpacks it into.
ARCHIVED = {"project.zip": "project", "project.tar.gz": "project"}
#: The LaTeX project the cases are made of (tests/data/latex), where no other is named.
LATEX = TEST.parents[1] / "tests" / "data" / "latex" / "manuscript"
#: How many corrections `audit --tracked` says it wrote as tracked changes.
CORRECTIONS = re.compile(r"(\d+) corrections? as tracked changes")
#: The files of a page built for a host (web/build.py --host) that the page built without one
#: has not: the host's journals and its logo and accent. Every other file must be the same.
HOST_FILES = ("journals/", "host/")
#: The files that say which page each is, and so differ between the two.
OWN_FILES = ("manifest.json", "files.sha256")
#: The authors the page's boxes name for a blind review, set in its boxes (their ids).
AUTHORS_BOXES = {"author-1-given": "Ada", "author-1-family": "Example",
                 "affiliations": "Department of Examples"}
#: poppler's programs the page runs (web/poppler.mjs), which the command line here is given
#: as the same build, run in Node.
PROGRAMS = ("pdftotext", "pdfinfo")
#: The PDF a case is given, set from the .docx's text (`pdf_of`), and how it is set: its
#: author is the one a blind review's authors name, read from its Info dictionary.
PDF_PAPER = "paper.pdf"
PDF_SETTING = {"head": "Journal of Examples", "foot": "Page", "first_page": 1,
               "line_numbers": True, "author": "Ada Example"}
#: The width of a column of the PDF, in characters of pandoc's plain text.
PDF_COLUMNS = 50
#: The start of the reader's report a comparison writes where it is asked for, under the name
#: the page gives it (worker.js `DRAFT`); each version is in a folder of its own.
DRAFT = "report-draft.md"
VERSIONS = ("v1", "v2")
#: The example revision the page offers (web/compare.js `EXAMPLE`), a reader's comments on its
#: first version, and its letter as a .docx.
EXAMPLE = ("example-before.md", "example-paper.md", "example-letter.md")
MINE = "mine.md"
COMMENTS = ('1. The sentence "Data were analysed at two study centres" does not say which.\n\n'
            "2. Table 2 is missing.\n\n3. Please report the confidence outcome.\n")
LETTER_DOCX = "letter.docx"
#: The name two versions of one paper are given, as a journal's system may give both.
ONE_NAME = "paper.md"


def argument(name: str) -> str:
    """A file's name as the page puts it in the command (worker.js)."""
    return "./" + name if name.startswith("-") else name


#: The environment the command line here is run in (`programs_for`).
ENVIRONMENT: dict[str, str] = dict(os.environ)


def native(folder: Path, arguments: list[str]) -> dict:
    done = subprocess.run([sys.executable, "-m", "manuscript_guard.cli", *arguments], cwd=folder,
                          capture_output=True, text=True, encoding="utf-8", timeout=600,
                          check=False, env=ENVIRONMENT)  # fmt: skip
    return {"code": done.returncode, "out": done.stdout, "err": done.stderr}


def programs_for(page: Path, folder: Path) -> dict[str, str]:
    """The environment the command line here reads a PDF in with the page's own pdftotext and
    pdfinfo: a shell script for each in `folder`, which runs it as the page does, in Node
    (`program.mjs`), put first on PATH, and MANUSCRIPT_GUARD_POPPLER left out. On Windows,
    which starts no shell script, PATH as it is, and a line that says which pdftotext the
    command line reads a PDF with."""
    environment = {key: value for key, value in os.environ.items()
                   if key != "MANUSCRIPT_GUARD_POPPLER"}  # fmt: skip
    if os.name == "nt":
        print("the command line reads a PDF with the pdftotext on PATH, "
              f"{shutil.which('pdftotext') or 'none'}: Windows starts no shell script, so the "
              "PDF cases are the same only where that one runs the page's build", flush=True)
        return environment
    folder.mkdir(parents=True, exist_ok=True)
    for name in PROGRAMS:
        script = folder / name
        script.write_text(script_for(page, name), encoding="utf-8")
        script.chmod(0o755)
    environment["PATH"] = os.pathsep.join([str(folder), environment.get("PATH", "")])
    return environment


def script_for(page: Path, name: str) -> str:
    """The shell script that runs the page's program `name` in Node. The command line runs it
    from each case's own folder, so the page's folder is named whole, not as `--site` gave it,
    and Node as `node_found` names it."""
    command = [NODE, str(TEST / "program.mjs"), str(page.resolve()), name]
    return f"#!/bin/sh\nexec {shlex.join(command)} \"$@\"\n"


def pdf_of(docx: Path) -> bytes:
    """The .docx's text, as pandoc gives it in plain text, set as a PDF in two columns
    (tests/proof_pdf.py `typeset`, `PDF_SETTING`)."""
    sys.path.insert(0, str(TEST.parents[1] / "tests"))
    import proof_pdf

    done = subprocess.run(["pandoc", str(docx), "-t", "plain", "--wrap=auto",
                           f"--columns={PDF_COLUMNS}"], capture_output=True, timeout=300,
                          check=True)  # fmt: skip
    try:
        return proof_pdf.typeset(done.stdout.decode("utf-8").splitlines(), **PDF_SETTING)
    except ValueError as exc:
        raise SystemExit(f"the .docx's text cannot be set as a PDF: {exc}") from None


def in_node(site: Path, folder: Path, arguments: list[str], unpack: str | None = None,
            read: str | None = None) -> dict:
    """The command as the page runs it, in Node; `unpack`, an archive the page is given,
    unpacked there first as the page unpacks one (`parity.mjs --unpack`); `read`, a file the
    command writes, whose text is then given as "file" (`parity.mjs --read`)."""
    done = subprocess.run([NODE, str(TEST / "parity.mjs"), str(site), str(folder),
                           *(["--unpack", unpack] if unpack else []),
                           *(["--read", read] if read else []), "--",
                           *arguments], capture_output=True, text=True, encoding="utf-8",
                          timeout=900, check=False)  # fmt: skip
    if done.returncode != 0:
        raise SystemExit(f"parity.mjs failed:\n{done.stderr}")
    return json.loads(done.stdout)


def differences(said: dict, page: dict, as_json: bool) -> list[str]:
    """What the page said otherwise than the command line."""
    found = [part for part in ("code", "err") if said[part] != page[part]]
    same_out = (json.loads(said["out"]) == json.loads(page["out"]) if as_json
                else said["out"] == page["out"])  # fmt: skip
    return found if same_out else ["out", *found]


def compared(page: Path, folder: Path, cases: list, prefix: str) -> tuple[list[dict], int]:
    """Each case run by the command line here and by `page` in Node, and said the same or not;
    the cases as browser.mjs runs them, each with what the command line printed, and how many
    were not the same. A case is its name, the paper, the outputs, the options as the command
    line takes them and as the page's boxes are set, and the files the page must make of its
    form by the day it makes them (`form_files`), or None."""
    listed, failed = [], 0
    for number, (name, paper, against, (options, form), made) in enumerate(cases):
        arguments = ["audit", argument(ARCHIVED.get(paper, paper)),
                     *(["--against", *map(argument, against)] if against else []), *options]
        said = native(folder, arguments)
        unpack = paper if paper in ARCHIVED else None
        wrong = [*differences(said, in_node(page, folder, arguments, unpack), False),
                 *(f"--json {part}" for part in differences(
                     native(folder, [*arguments, "--json"]),
                     in_node(page, folder, [*arguments, "--json"], unpack), True))]  # fmt: skip
        print(f"node, {name}: {'same' if not wrong else 'DIFFERENT: ' + ', '.join(wrong)}",
              flush=True)  # fmt: skip
        failed += bool(wrong)
        expect = f"{prefix}-{number}.json"
        (folder / expect).write_text(json.dumps(said), encoding="utf-8")
        case = {"name": name, "paper": paper, "against": against, "expect": expect,
                "form": form}  # fmt: skip
        if made is not None:
            case["made"] = made
        if form.get("tracked"):
            copy = folder / f"tracked-{number}.docx"
            done = native(folder, [*arguments, "--tracked", copy.name])
            copy.unlink(missing_ok=True)
            counted = CORRECTIONS.search(done["err"])
            if done["code"] != said["code"] or not counted:
                print(f"{name}: the command line wrote no copy with tracked changes:\n"
                      f"{done['err']}", flush=True)  # fmt: skip
                failed += 1
                continue
            case["tracked"] = int(counted.group(1))
        listed.append(case)
    return listed, failed


def comparisons(page: Path, folder: Path, cases: list) -> tuple[list[dict], int]:
    """Each comparison run by the command line here and by `page` in Node, and said the same
    or not, the start of the reader's report too where it is asked for; the cases as
    browser.mjs runs them, and how many were not the same. A case is its name, the two
    versions, each by its path in `folder`, the letter and the comments or None, and whether
    the draft is asked for. The command line is given each version in the folder the page
    writes it in, under its own name."""
    listed, failed = [], 0
    for number, (name, before, after, letter, comments, draft) in enumerate(cases):
        arguments = ["compare", f"{VERSIONS[0]}/{Path(before).name}",
                     f"{VERSIONS[1]}/{Path(after).name}",
                     *(["--response", argument(letter)] if letter else []),
                     *(["--comments", argument(comments)] if comments else [])]  # fmt: skip
        asked = [*arguments, *(["--report-draft", DRAFT] if draft else [])]
        written = folder / DRAFT
        written.unlink(missing_ok=True)
        said = native(folder, asked)
        # Taken out of the folder before the page is given it, which would find it there.
        said["draft"] = written.read_text(encoding="utf-8") if written.is_file() else None
        written.unlink(missing_ok=True)
        page_said = in_node(page, folder, asked, read=DRAFT if draft else None)
        wrong = [*differences(said, page_said, False),
                 *(["draft"] if said["draft"] != page_said.get("file") else []),
                 *(f"--json {part}" for part in differences(
                     native(folder, [*arguments, "--json"]),
                     in_node(page, folder, [*arguments, "--json"]), True))]  # fmt: skip
        if draft and said["draft"] is None:
            wrong.append("no draft from the command line")
        print(f"node, {name}: {'same' if not wrong else 'DIFFERENT: ' + ', '.join(wrong)}",
              flush=True)  # fmt: skip
        failed += bool(wrong)
        expect = f"compare-{number}.json"
        (folder / expect).write_text(json.dumps(said), encoding="utf-8")
        listed.append({"name": name, "expect": expect,
                       "compare": {"before": before, "after": after, "letter": letter,
                                   "comments": comments, "draft": draft}})  # fmt: skip
    return listed, failed


def versions_in(folder: Path) -> list:
    """The comparisons' files in `folder`: each version in the folder the page writes it in,
    and beside them, by its own name, as the browser chooses it; the cases. Two versions of
    one name are two files, the example's two, so that a page that read one twice would
    not give the command line's report (round 1 of #854)."""
    for which in VERSIONS:
        (folder / which).mkdir()
    for name in EXAMPLE:
        shutil.copyfile(TEST.parent / name, folder / name)
    (folder / MINE).write_text(COMMENTS, encoding="utf-8", newline="\n")
    subprocess.run(["pandoc", str(folder / EXAMPLE[2]), "-o", str(folder / LETTER_DOCX)],
                   capture_output=True, timeout=300, check=True)  # fmt: skip
    for which, names in ((VERSIONS[0], (EXAMPLE[0], PDF_PAPER)),
                         (VERSIONS[1], (EXAMPLE[1], "paper.docx"))):  # fmt: skip
        for name in names:
            shutil.copyfile(folder / name, folder / which / name)
    for which, name in zip(VERSIONS, EXAMPLE[:2], strict=True):
        shutil.copyfile(folder / name, folder / which / ONE_NAME)
    return [
        ("the example revision, its letter, comments and the start of a report", EXAMPLE[0],
         EXAMPLE[1], EXAMPLE[2], MINE, True),
        ("a PDF beside the .docx", PDF_PAPER, "paper.docx", None, None, False),
        ("two versions of one name, the letter a .docx, and the start of a report",
         f"{VERSIONS[0]}/{ONE_NAME}", f"{VERSIONS[1]}/{ONE_NAME}", LETTER_DOCX, None, True),
    ]


def listed_files(page: Path) -> dict[str, str]:
    """The files `page` lists in its files.sha256, each with its SHA-256."""
    lines = (page / "files.sha256").read_text(encoding="utf-8").splitlines()
    return {path: digest for digest, path in (line.split("  ", 1) for line in lines if line)}


def same_code(page: Path, hosted: Path) -> int:
    """Whether the page built for a host serves the code of the page built without one, byte
    for byte, and adds only the host's own files: 0 if so, 1 if not, with what differs."""
    plain, theirs = listed_files(page), listed_files(hosted)
    changed = sorted(path for path, digest in plain.items()
                     if path not in OWN_FILES and theirs.get(path) != digest)  # fmt: skip
    added = sorted(path for path in theirs.keys() - plain.keys()
                   if not path.startswith(HOST_FILES))  # fmt: skip
    for path in changed:
        print(f"the hosted page's {path} is not the page's", flush=True)
    for path in added:
        print(f"the hosted page serves {path}, which is no host's file", flush=True)
    print(f"the hosted page's code: {'the same' if not changed and not added else 'DIFFERENT'} "
          f"({len(plain) - 1} files compared)", flush=True)  # fmt: skip
    return int(bool(changed or added))


def hosted_cases(hosted: Path, folder: Path, authors: str) -> list:
    """The cases of a page built for a host: the .docx held to each journal it offers, as
    chosen from its list, and for one whose review is blind, with the authors in its boxes.
    Each profile goes in `folder` under journals/, as the page serves it."""
    manifest = json.loads((hosted / "manifest.json").read_text(encoding="utf-8"))
    (folder / "journals").mkdir(exist_ok=True)
    cases = []
    for journal in manifest["host"]["journals"]:
        shutil.copyfile(hosted / journal["file"], folder / journal["file"])
        blind = journal["blinding"] in ("double", "triple")
        options = ["--journal", journal["file"], *(["--authors", "authors.yaml"] if blind else [])]
        form = {"journal": journal["slug"], **(AUTHORS_BOXES if blind else {})}
        cases.append((f"{journal['name']}, chosen from the page's list", "paper.docx", [],
                      (options, form), {"authors.yaml": authors} if blind else {}))
    return cases


def form_files(first: date) -> dict[str, dict[str, str]]:
    """The files the journal's form makes, as the page makes them on each day a run that
    starts on `first` may reach, by the day as the page writes it. The page dates the
    journal's instructions the day it runs a case, in this computer's own time, so a run
    that crosses midnight makes the next day's (main's `web` job at #850's merge)."""
    from manuscript_guard.journal_form import as_text, authors_of, profile_of

    days = [(first + timedelta(days=n)).isoformat() for n in range(DAYS)]
    return {day: {"journal.yaml": as_text(profile_of({**JOURNAL_FORM, "date": day})),
                  "authors.yaml": as_text(authors_of(AUTHORS_FORM))} for day in days}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--site", type=Path, required=True, help="what web/build.py built")
    parser.add_argument("--docx", type=Path, required=True, help="the worked example, built")
    parser.add_argument("--results", type=Path, required=True, help="its results file")
    parser.add_argument("--markdown", type=Path, required=True, help="its manuscript/main.md")
    parser.add_argument("--latex", type=Path, default=LATEX,
                        help="a LaTeX project's folder (default tests/data/latex/manuscript)")
    parser.add_argument("--hosted", type=Path,
                        help="a page web/build.py --host built, held the same way")
    parser.add_argument("--browsers", default="chrome,firefox",
                        help="comma-separated, or none (default chrome,firefox)")  # fmt: skip
    args = parser.parse_args(argv)
    # Each case: its name, the paper, the outputs, and where any are set, the options as
    # the command line takes them and as the page's boxes are set.
    cases = [
        ("the .docx against its results", "paper.docx", ["results.json"], ([], {})),
        ("the .docx alone", "paper.docx", [], ([], {})),
        ("the Markdown alone", "paper.md", [], ([], {})),
        ("names outside ASCII, with spaces", PAPER, [OUTPUT], ([], {})),
        ("names that start with -", DASHED_PAPER, [DASHED_OUTPUT], ([], {})),
        ("two outputs the page once named alike", "paper.docx", list(ALIKE), ([], {})),
        ("a referee's options", "paper.docx", ["results.json"], REFEREE),
        ("the copy with tracked changes", "paper.docx", [], TRACKED),
        ("a journal's rules, its review double-blind", "paper.docx", [], JOURNAL),
        ("a LaTeX project as a .zip", "project.zip", [], ([], {})),
        ("a LaTeX project as a .tar.gz", "project.tar.gz", [], ([], {})),
        ("a PDF against its results", PDF_PAPER, ["results.json"], ([], {})),
        ("a PDF held to a journal's rules, its review double-blind", PDF_PAPER, [], JOURNAL),
    ]
    failed = 0
    global ENVIRONMENT
    with (tempfile.TemporaryDirectory(prefix="mg-page-") as scratch,
          tempfile.TemporaryDirectory(prefix="mg-programs-") as programs):  # fmt: skip
        folder = Path(scratch)
        ENVIRONMENT = programs_for(args.site / AUDIT, Path(programs))
        # The files the journal's form makes, as the page makes them on each day the run may
        # reach; the command line is given the first day's.
        made = form_files(date.today())
        given = next(iter(made.values()))
        for name, text in given.items():
            (folder / name).write_bytes(text.encode("utf-8"))
        # The LaTeX project as a folder, and as the archives a reader would drop: a .zip as
        # Overleaf writes one, and a .tar.gz of "./" names as arXiv's are.
        shutil.copytree(args.latex, folder / "project")
        files = sorted(path for path in (folder / "project").rglob("*") if path.is_file())
        with zipfile.ZipFile(folder / "project.zip", "w") as archive:
            for path in files:
                archive.write(path, path.relative_to(folder / "project").as_posix())
        with tarfile.open(folder / "project.tar.gz", "w:gz") as archive:
            for path in files:
                archive.add(path, "./" + path.relative_to(folder / "project").as_posix())
        for source, names in ((args.docx, ("paper.docx", PAPER, DASHED_PAPER)),
                              (args.results, ("results.json", OUTPUT, DASHED_OUTPUT, *ALIKE)),
                              (args.markdown, ("paper.md",))):  # fmt: skip
            for name in names:
                shutil.copyfile(source, folder / name)
        (folder / PDF_PAPER).write_bytes(pdf_of(args.docx))
        listed, wrong = compared(args.site / AUDIT, folder,
                                 [(*case, made if "--journal" in case[3][0] else None)
                                  for case in cases], "expect")  # fmt: skip
        failed += wrong
        comparing, wrong = comparisons(args.site / AUDIT, folder, versions_in(folder))
        failed += wrong
        (folder / "cases.json").write_text(json.dumps([*listed, *comparing]), encoding="utf-8")
        if args.hosted:
            failed += same_code(args.site / AUDIT, args.hosted)
            # A hosted journal's form is its own profile: the page makes only the authors'
            # names, the same on any day.
            cases = [(*case[:4], dict.fromkeys(made, case[4]))
                     for case in hosted_cases(args.hosted, folder, given["authors.yaml"])]
            hosted, wrong = compared(args.hosted, folder, cases, "hosted")
            failed += wrong
            (folder / "hosted-cases.json").write_text(json.dumps(hosted), encoding="utf-8")
        for browser in [b for b in args.browsers.split(",") if b and b != "none"]:
            done = subprocess.run([NODE, str(TEST / "browser.mjs"), str(args.site), str(folder),
                                   browser], timeout=1800, check=False)  # fmt: skip
            failed += done.returncode != 0
            if args.hosted:
                done = subprocess.run([NODE, str(TEST / "browser.mjs"), str(args.hosted),
                                       str(folder), browser, "--hosted"], timeout=1800,
                                      check=False)  # fmt: skip
                failed += done.returncode != 0
    print("the page holds to the command line" if not failed else f"{failed} check(s) failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
