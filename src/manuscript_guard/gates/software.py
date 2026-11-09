"""G12 — the plan's Software section against the packages the analysis loads.

On a real disproportionality paper the analysis of VigiBase wrote its own code where a
package written for that source, `vigicaen`, held the source's own logic for identifying
drugs and reactions, and nothing in the toolkit asked which software suited the data and the
question. The analysis-plan skill now asks it before the analysis section is fixed (Basile,
2026-11-05), and the plan records the answer in a section headed Software: one list item for
each package, opening with its name in backticks, with its version and which of its
functions does which step; the packages considered and not taken under a heading of their
own (2026-11-09). This check holds that record to the scripts:

* an item none of whose names a script of `analysis/` or `figures/` loads, nor the
  emitter's `software()` recorded, is `planned-package-unloaded`: a warning from the
  analysis stage on (at the design stage no script has to exist yet), at every stage after,
  as G12's other findings of the plan; the item's name in backticks under Deviations stands
  it down, as it does a planned result's;
* a package a script loads that no item names is `plan-package-unnamed`, a note: base R,
  Python's standard library, the project's own modules and the toolkit's emitters aside.
  Its name in backticks under Deviations, the record of a package added after the plan was
  agreed, stands it down too.

A load is read where the code writes the package's name: `library()`, `require()`,
`requireNamespace()`, `loadNamespace()`, `pkg::` and `pkg:::` in R; `import`, `from` and
`importlib.import_module()` in Python; anywhere in the file, a function's body included,
outside its comments and strings; in an R Markdown or Quarto file, in its R and Python
chunks; in a notebook, in its code cells. A name the code computes is not read, nor a
package another loads for it (DESIGN.md, Known gaps). Whether the package is the right one
for the data is the author's and the panel's to judge, not a gate's.
"""

from __future__ import annotations

import ast
import dataclasses
import json
import re
import sys
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from manuscript_guard.contracts.project import Project
from manuscript_guard.contracts.results import Results
from manuscript_guard.findings import INFO, WARN, Finding, Report
from manuscript_guard.text.blocks import list_items
from manuscript_guard.text.inline import code_spans
from manuscript_guard.text.masking import mask
from manuscript_guard.text.sections import subsections

GATE = "G12"
R = "r"
PYTHON = "python"

#: The folders whose scripts are read: the analysis and the figures (Basile, 2026-11-09).
FOLDERS = ("analysis", "figures")
#: Folders never read, wherever they are: others' code installed into the project.
LIBRARIES = frozenset({"renv", "packrat", "node_modules", "venv", "site-packages", "__pycache__"})
#: A script's language by its suffix, or how its code is found in it.
_BY_SUFFIX = {".r": R, ".py": PYTHON, ".rmd": "chunks", ".qmd": "chunks", ".ipynb": "notebook"}

#: The packages of base R, those of priority "base", which every R has and nobody chooses.
#: The recommended ones, survival and MASS among them, are a choice, and are named.
R_BASE = frozenset({
    "base", "compiler", "datasets", "grDevices", "graphics", "grid", "methods", "parallel",
    "splines", "stats", "stats4", "tcltk", "tools", "utils",
})  # fmt: skip
#: The toolkit's emitters, which every project loads, in Python and in R.
EMITTERS = frozenset({"manuscript_guard", "manuscriptguard"})
_EMITTER_KEYS = frozenset(re.sub(r"[^a-z0-9]+", "_", name) for name in EMITTERS)
#: An item that names the language itself is of a script in it.
INTERPRETERS = {"r": R, "python": PYTHON}

#: The headings of the plan's Software section.
SOFTWARE_HEADING = re.compile(r"\bsoftware\b|\bpackages?\b|\blibraries\b", re.IGNORECASE)
#: Under it, the heading of the packages considered and not taken, whose items are not held
#: to the scripts.
NOT_USED_HEADING = re.compile(
    r"\bnot\s+(?:used|taken|chosen|adopted)\b|\bconsidered\b|\brejected\b|\bset\s+aside\b",
    re.IGNORECASE,
)
#: A code span that names a package: a bare name, or `pkg::fn()` for its package. A span
#: with brackets alone, `glm()`, is a function, and one that opens with a digit a version.
NAME_SPAN = re.compile(r"([A-Za-z][A-Za-z0-9._-]*)(?::::?\S*)?")


def _stdlib() -> frozenset[str]:
    """The modules of Python's standard library, as the Python running the check has them."""
    return _STDLIB


_STDLIB = frozenset(sys.stdlib_module_names)


@dataclass(frozen=True)
class Load:
    """A package a script loads, as the script writes it, its language, and the line of the
    load: None in a notebook, whose lines are the JSON's."""

    name: str
    language: str
    line: int | None


@dataclass(frozen=True)
class Planned:
    """An item of the plan's Software section: the names it gives in code spans, the first
    the package, the line it starts on, and whether the plan means to use it (False under a
    heading of the packages considered and not used)."""

    names: tuple[str, ...]
    line: int
    used: bool


def _line(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def _norm(name: str) -> str:
    """A name as two spellings of it compare: `scikit-learn`, `scikit_learn` and the key
    `software.scikit_learn` the emitter writes for it alike, and `data.table` as
    `data_table`."""
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")


# ---------------------------------------------------------------------------------- R


_R_COMMENT = re.compile(r"#[^\n]*")
_R_STRING = re.compile(r"\"(?:[^\"\\]|\\.)*\"|'(?:[^'\\]|\\.)*'", re.DOTALL)
_R_RAW = re.compile(r"[rR]([\"'])(-*)([(\[{])")
_R_BACKTICK = re.compile(r"`(?:[^`\\]|\\.)*`", re.DOTALL)
_R_NAME = re.compile(r"(?:[A-Za-z]|\.(?![0-9]))[A-Za-z0-9._]*")
_R_NUMBER = re.compile(r"[0-9][A-Za-z0-9._]*")
_R_OPERATOR = re.compile(r":::|::|%[^%\n]*%|<<-|<-|->|[(),=$@\[\]{}]")
_CLOSE = {"(": ")", "[": "]", "{": "}"}
#: A package's name as R allows it: two characters or more, letters, digits and points,
#: opening with a letter and not ending with a point.
_R_PACKAGE = re.compile(r"[A-Za-z][A-Za-z0-9.]*[A-Za-z0-9]")
#: The calls that load a package named in them, and whether a bare name there is the
#: package's (`library(dplyr)`) or a variable holding it (`requireNamespace(pkg)`).
_R_LOADERS = {"library": True, "require": True, "requireNamespace": False,
              "loadNamespace": False, "attachNamespace": False}  # fmt: skip
#: What follows a package's name where the code calls into its namespace, `pkg::fn`.
_NAMESPACED = frozenset({("op", "::"), ("op", ":::")})

Token = tuple[str, str, int]


def r_tokens(text: str) -> list[Token]:
    """R's tokens, as `(kind, text, offset)`, kind `name`, `string` or `op`: a comment left
    out, a string's contents and a raw string's (`r"(...)"`) as one string, a backticked
    name as a name."""
    tokens: list[Token] = []
    at, end = 0, len(text)
    while at < end:
        if text[at].isspace():
            at += 1
            continue
        if found := _R_COMMENT.match(text, at):
            at = found.end()
            continue
        if raw := _R_RAW.match(text, at):
            quote, dashes, opened = raw.groups()
            close = _CLOSE[opened] + dashes + quote
            stop = text.find(close, raw.end())
            stop = end if stop < 0 else stop
            tokens.append(("string", text[raw.end() : stop], at))
            at = min(end, stop + len(close))
            continue
        if found := _R_STRING.match(text, at):
            tokens.append(("string", found.group()[1:-1], at))
        elif found := _R_BACKTICK.match(text, at):
            tokens.append(("name", found.group()[1:-1], at))
        elif found := _R_NAME.match(text, at):
            tokens.append(("name", found.group(), at))
        elif found := _R_NUMBER.match(text, at):
            pass
        elif found := _R_OPERATOR.match(text, at):
            tokens.append(("op", found.group(), at))
        else:
            tokens.append(("op", text[at], at))
            at += 1
            continue
        at = found.end()
    return tokens


def _r_arguments(tokens: list[Token], start: int) -> list[list[Token]] | None:
    """The arguments of the call whose `(` is just before `start`, each as its tokens, split
    at the commas outside brackets; None where the call is not closed."""
    arguments: list[list[Token]] = []
    current: list[Token] = []
    depth = 0
    for token in tokens[start:]:
        kind, value, _at = token
        if kind == "op" and value in ("(", "[", "{"):
            depth += 1
        elif kind == "op" and value in (")", "]", "}"):
            if depth == 0:
                arguments.append(current)
                return [argument for argument in arguments if argument]
            depth -= 1
        elif kind == "op" and value == "," and depth == 0:
            arguments.append(current)
            current = []
            continue
        current.append(token)
    return None


def _computed(named: dict[str, list[Token]]) -> bool:
    """Whether a call says its package is a name it computes: `character.only = TRUE`."""
    given = named.get("character.only")
    if not given:
        return False
    return not (len(given) == 1 and given[0][1] in ("FALSE", "F"))


def _r_package(tokens: list[Token], start: int, bare: bool) -> str | None:
    """The package a loading call names, where it is written in it: its `package` argument
    or its first, a string, or a bare name where the call takes one for the package's. None
    for `library(help = ...)`, which loads nothing, and for a name the code computes."""
    arguments = _r_arguments(tokens, start)
    if not arguments:
        return None
    named: dict[str, list[Token]] = {}
    positional: list[list[Token]] = []
    for argument in arguments:
        if len(argument) >= 2 and argument[0][0] in ("name", "string") and \
                argument[1][:2] == ("op", "="):  # fmt: skip
            named[argument[0][1]] = argument[2:]
        else:
            positional.append(argument)
    if "help" in named or _computed(named):
        return None
    given = named.get("package") or (positional[0] if positional else None)
    if not given or len(given) != 1:
        return None
    kind, value, _at = given[0]
    if kind == "string" or (kind == "name" and bare):
        return value if _R_PACKAGE.fullmatch(value) else None
    return None


def r_loads(text: str) -> list[Load]:
    """The packages R code loads, in the order it writes them: each `pkg::` and `pkg:::`,
    and each package a loading call names (`_R_LOADERS`), a member's call (`x$library()`)
    aside."""
    tokens = r_tokens(text)
    loads = []
    for index, (kind, value, at) in enumerate(tokens):
        if kind != "name" or (index and tokens[index - 1][:2] in (("op", "$"), ("op", "@"))):
            continue
        after = tokens[index + 1][:2] if index + 1 < len(tokens) else None
        if after in _NAMESPACED:
            if _R_PACKAGE.fullmatch(value):
                loads.append(Load(value, R, _line(text, at)))
        elif after == ("op", "(") and value in _R_LOADERS:
            named = _r_package(tokens, index + 2, _R_LOADERS[value])
            if named:
                loads.append(Load(named, R, _line(text, at)))
    return loads


# ------------------------------------------------------------------------------ Python


#: An import, where a file does not parse: a line that opens with one.
_PYTHON_IMPORT = re.compile(
    r"^[ \t]*(?:import[ \t]+([A-Za-z_]\w*)|from[ \t]+([A-Za-z_]\w*)[\w.]*[ \t]+import\b)",
    re.MULTILINE,
)


def _python_nodes(tree: ast.AST) -> Iterable[ast.AST]:
    """Every node of a module, a function's body and a `try` block's included."""
    return ast.walk(tree)


def _from_module(node: ast.ImportFrom) -> str | None:
    """The package `from x.y import z` loads: `x`. None for a relative import, which is of
    the project's own modules."""
    return node.module.split(".")[0] if node.level == 0 and node.module else None


def _imported_by_call(node: ast.Call) -> str | None:
    """The package `importlib.import_module("x")` or `__import__("x")` loads, where its
    name is written in the call."""
    called = node.func
    name = called.attr if isinstance(called, ast.Attribute) else \
        called.id if isinstance(called, ast.Name) else None  # fmt: skip
    if name not in ("import_module", "__import__"):
        return None
    if isinstance(called, ast.Attribute) and not (
            isinstance(called.value, ast.Name) and called.value.id == "importlib"):  # fmt: skip
        return None
    if not node.args or not isinstance(node.args[0], ast.Constant):
        return None
    module = node.args[0].value
    if not isinstance(module, str) or not module or module.startswith("."):
        return None
    return module.split(".")[0]


def python_loads(text: str) -> list[Load]:
    """The packages Python code loads, by their top-level names, in the order of their
    lines. Code the Python running the check cannot parse is read line by line, for the
    lines that open with an import."""
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError):
        return [Load(found.group(1) or found.group(2), PYTHON, _line(text, found.start()))
                for found in _PYTHON_IMPORT.finditer(text)]  # fmt: skip
    loads = []
    for node in _python_nodes(tree):
        if isinstance(node, ast.Import):
            loads += [Load(alias.name.split(".")[0], PYTHON, node.lineno) for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            if module := _from_module(node):
                loads.append(Load(module, PYTHON, node.lineno))
        elif isinstance(node, ast.Call) and (module := _imported_by_call(node)):
            loads.append(Load(module, PYTHON, node.lineno))
    return sorted(loads, key=lambda load: load.line or 0)


# ------------------------------------------------------------------------ the scripts


_FENCE = re.compile(r"^[ \t]*(`{3,}|~{3,})(.*)$")
_CHUNK = re.compile(r"[ \t]*\{[ \t]*([A-Za-z]+)\b[^}]*\}[ \t]*")
_LANGUAGES = {"r": R, "python": PYTHON}
#: A line of a notebook's cell that is IPython's and not Python's.
_MAGIC = re.compile(r"^[ \t]*[%!]")


def chunks(text: str) -> dict[str, str]:
    """The code of an R Markdown or Quarto file, R's and Python's, each as the file with
    every line that is not that language's code blank, so that a line is the file's. A
    chunk is a fenced block whose fence opens `{r` or `{python`; a block fenced otherwise
    is shown, not run, and is not read."""
    lines = text.split("\n")
    kept = {R: [""] * len(lines), PYTHON: [""] * len(lines)}
    fence: str | None = None
    language: str | None = None
    for number, line in enumerate(lines):
        if fence is None:
            if opened := _FENCE.match(line):
                fence = opened.group(1)
                chunk = _CHUNK.fullmatch(opened.group(2))
                language = _LANGUAGES.get(chunk.group(1).lower()) if chunk else None
            continue
        if re.fullmatch(rf"[ \t]*{re.escape(fence)}{re.escape(fence[0])}*[ \t]*", line):
            fence = None
            continue
        if language:
            kept[language][number] = line
    return {name: "\n".join(lines) for name, lines in kept.items()}


def _notebook(text: str) -> dict[str, str]:
    """The code of a notebook's code cells, in the language its kernel names (Python where
    it names none), IPython's magics and shell lines left out."""
    try:
        document = json.loads(text)
    except ValueError:
        return {}
    if not isinstance(document, dict):
        return {}
    meta = _mapping(document.get("metadata"))
    kernel, info = _mapping(meta.get("kernelspec")), _mapping(meta.get("language_info"))
    language = _LANGUAGES.get(str(kernel.get("language") or info.get("name") or PYTHON).lower())
    found = document.get("cells")
    cells: list = found if isinstance(found, list) else []
    code: list[str] = []
    for cell in cells:
        if not isinstance(cell, dict) or cell.get("cell_type") != "code":
            continue
        source = cell.get("source")
        source = "".join(part for part in source if isinstance(part, str)) \
            if isinstance(source, list) else source if isinstance(source, str) else ""  # fmt: skip
        code += ["" if language == PYTHON and _MAGIC.match(line) else line
                 for line in source.split("\n")]  # fmt: skip
    return {language: "\n".join(code)} if language else {}


def _mapping(value: object) -> dict:
    return value if isinstance(value, dict) else {}


def code_of(relative: str, text: str) -> dict[str, str]:
    """The code of one script, by language, as its suffix says it holds it; nothing for a
    file of another kind."""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    kind = _BY_SUFFIX.get(Path(relative).suffix.lower())
    if kind in (R, PYTHON):
        return {kind: text}
    if kind == "chunks":
        return chunks(text)
    if kind == "notebook":
        return _notebook(text)
    return {}


def script_loads(relative: str, text: str) -> list[Load]:
    """What one script loads, by the code its suffix says it holds: without a line in a
    notebook."""
    return _loads_in(relative, code_of(relative, text))


def _loads_in(relative: str, code: dict[str, str]) -> list[Load]:
    loads = []
    for language, lines in code.items():
        found = r_loads(lines) if language == R else python_loads(lines)
        if Path(relative).suffix.lower() == ".ipynb":
            found = [dataclasses.replace(load, line=None) for load in found]
        loads += found
    return loads


def scripts(project: Project) -> dict[str, str]:
    """The text of each script of `analysis/` and `figures/` that may load a package, by its
    path from the root, a hidden folder and an installed library aside."""
    found = {}
    for folder in FOLDERS:
        base = project.root / folder
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*")):
            parts = path.relative_to(project.root).parts
            if any(part.startswith(".") or part in LIBRARIES for part in parts):
                continue
            if path.suffix.lower() not in _BY_SUFFIX or not path.is_file():
                continue
            try:
                raw = path.read_bytes()
            except OSError:
                continue
            found["/".join(parts)] = raw.decode("utf-8-sig", errors="replace")
    return found


def own_modules(root: Path, read: Iterable[str]) -> frozenset[str]:
    """The names a script can import that are the project's own: each Python file and each
    folder holding one, in the project's folder and in the folder of each script read."""
    folders = {root} | {(root / relative).parent for relative in read}
    names = set()
    for folder in folders:
        try:
            children = list(folder.iterdir())
        except OSError:
            continue
        for child in children:
            if child.is_file() and child.suffix.lower() == ".py":
                names.add(child.stem)
            elif child.is_dir() and not child.name.startswith(".") and any(child.glob("*.py")):
                names.add(child.name)
    return frozenset(names)


def _given(load: Load, own: frozenset[str]) -> bool:
    """A load nobody chooses: of base R, of Python's standard library, of the project's own
    modules, or of the toolkit's emitter."""
    if _norm(load.name) in _EMITTER_KEYS:
        return True
    if load.language == R:
        return load.name in R_BASE
    return load.name in _stdlib() or load.name in own


# -------------------------------------------------------------------------- the plan


def planned_packages(text: str) -> list[Planned] | None:
    """The items of the plan's Software section, each with the names its code spans give
    and whether it is under a heading of the packages considered and not used; None where
    the plan has no such section. An item is read up to the next item or its first blank
    line, as a planned result is; an item whose spans name nothing is not read."""
    from manuscript_guard.gates.design import _plan_sections

    text = text.replace("\r\n", "\n").replace("\r", "\n")
    sections = _plan_sections(text)
    spans = code_spans(mask(text))
    items = list_items(text)
    ends = [section.line for section in sections[1:]] + [text.count("\n") + 2]
    found = False
    planned: list[Planned] = []
    done: set[int] = set()
    for index, section in enumerate(sections):
        if index in done or not SOFTWARE_HEADING.search(section.title):
            continue
        found = True
        stack: list[tuple[int, bool]] = []
        for offset, part in enumerate(subsections(sections, index)):
            at = index + offset
            done.add(at)
            while stack and stack[-1][0] >= part.level:
                stack.pop()
            unused = bool(NOT_USED_HEADING.search(part.title)) or bool(stack and stack[-1][1])
            stack.append((part.level, unused))
            inside = [start for start in items if part.line < _line(text, start) < ends[at]]
            planned += _items(text, spans, inside, _offset(text, ends[at]), not unused)
    return planned if found else None


def _offset(text: str, line: int) -> int:
    """Where `line` starts, or the end of the text."""
    at = 0
    for _ in range(line - 1):
        at = text.find("\n", at)
        if at < 0:
            return len(text)
        at += 1
    return at


def _items(text: str, spans: list[tuple[int, int]], inside: list[int], end: int,
           used: bool) -> list[Planned]:  # fmt: skip
    found = []
    for number, start in enumerate(inside):
        stop = inside[number + 1] if number + 1 < len(inside) else end
        blank = re.compile(r"\n[ \t]*\n").search(text, start, stop)
        stop = blank.start() if blank else stop
        names = tuple(dict.fromkeys(name for span in spans if start <= span[0] < stop
                                    if (name := _span_name(text[span[0] : span[1]]))))
        if names:
            found.append(Planned(names, _line(text, start), used))
    return found


def _span_name(span: str) -> str | None:
    named = NAME_SPAN.fullmatch(span.strip("`").strip())
    return named.group(1) if named else None


def deviation_names(text: str) -> set[str]:
    """The names the plan's Deviations section gives in code spans, as names compare."""
    from manuscript_guard.gates.design import deviations_said

    said = deviations_said(text.replace("\r\n", "\n").replace("\r", "\n"))
    return {_norm(name) for found in re.finditer(r"(`+)(.+?)\1", said)
            if (name := _span_name(found.group(2)))}  # fmt: skip


# ------------------------------------------------------------------------- the check


def check_software(project: Project, results: Results | None, stage: str | None) -> Report:
    """G12: the plan's Software section against what the scripts load and the emitter
    recorded. Nothing where there is no plan, which `no-analysis-plan` says."""
    from manuscript_guard.gates.design import _read_plan, plan_path

    path = plan_path(project)
    if not path.is_file():
        return Report()
    text, _unreadable = _read_plan(path)
    read = scripts(project)
    emitted = [] if results is None else [
        key.removeprefix("software.") for key, value in results.values.items()
        if value.role == "software" and key.startswith("software.")
    ]  # fmt: skip
    return judge_software(project.root, text, read, emitted, own_modules(project.root, read),
                          stage)  # fmt: skip


def judge_software(root: Path, text: str, read: dict[str, str], emitted: Iterable[str],
                   own: frozenset[str], stage: str | None) -> Report:  # fmt: skip
    """What G12 says of a plan's Software section, `text` the plan, against the scripts in
    `read` (by their paths from `root`), the names the emitter recorded software under, and
    the project's own modules, at `stage`."""
    from manuscript_guard.gates.design import PLAN
    from manuscript_guard.policy import DESIGN

    planned = planned_packages(text)
    codes = {relative: code_of(relative, script) for relative, script in sorted(read.items())}
    languages = {language for code in codes.values() for language, lines in code.items()
                 if lines.strip()}  # fmt: skip
    loads = [(relative, load) for relative, code in codes.items()
             for load in _loads_in(relative, code)]  # fmt: skip
    loaded = {(load.language, _norm(load.name)) for _relative, load in loads}
    made = {_norm(name) for name in emitted}
    deviations = deviation_names(text)
    used = [item for item in planned or () if item.used]
    findings = []
    if stage not in (None, DESIGN):
        for item in used:
            if any(_is_loaded(name, loaded, made, languages) for name in item.names) or \
                    any(_norm(name) in deviations for name in item.names):  # fmt: skip
                continue
            findings.append(Finding(
                GATE, "planned-package-unloaded",
                f"the plan's Software section names {item.names[0]}, and no script in "
                "analysis/ or figures/ loads it",
                severity=WARN, path=root / PLAN, line=item.line,
                hint="load it in the script that does the step it was chosen for; or, if "
                "the analysis does not use it, say why under Deviations from the plan, "
                f"naming it in backticks, `{item.names[0]}`. A package scripts import by "
                "another name takes that name in its item too: `scikit-learn`, `sklearn`",
            ))  # fmt: skip
    chosen = [(relative, load) for relative, load in loads if not _given(load, own)]
    findings += _unnamed(root, planned, chosen, deviations)
    counts = {"software_planned": len(used),
              "software_loaded": len({(load.language, _norm(load.name)) for _r, load in chosen})}
    return Report(tuple(findings), counts)


def _is_loaded(name: str, loaded: set[tuple[str, str]], made: set[str],
               languages: set[str]) -> bool:  # fmt: skip
    """Whether a name an item gives is of a package loaded or recorded: by its name, by its
    first part where Python loads that (`statsmodels.api`), or as the language of a script
    read (`R`, `Python`)."""
    key = _norm(name)
    return (
        any((language, key) in loaded for language in (R, PYTHON))
        or (PYTHON, _norm(name.split(".")[0])) in loaded
        or key in made
        or INTERPRETERS.get(key) in languages
    )


def _unnamed(root: Path, planned: list[Planned] | None, chosen: list[tuple[str, Load]],
             deviations: set[str]) -> list[Finding]:  # fmt: skip
    """A note for each package a script loads that no item of the Software section names,
    at its first load."""
    names: dict[bool, set[str]] = {True: set(), False: set()}
    for item in planned or ():
        for name in item.names:
            names[item.used] |= {_norm(name), _norm(name.split(".")[0])}
    first: dict[tuple[str, str], tuple[str, Load]] = {}
    for relative, load in chosen:
        first.setdefault((load.language, _norm(load.name)), (relative, load))
    findings = []
    for (_language, key), (relative, load) in first.items():
        if key in names[True] or key in deviations:
            continue
        if planned is None:
            why = "and the plan has no Software section"
        elif key in names[False]:
            why = "and the plan's Software section lists it among those considered and not used"
        else:
            why = "and the plan's Software section does not name it"
        findings.append(Finding(
            GATE, "plan-package-unnamed", f"{relative} loads {load.name}, {why}",
            severity=INFO, path=root / relative, line=load.line,
            hint=f"give it an item in the plan's Software section that opens with `{load.name}`: "
            "its version, which of its functions does which step, and why it was chosen over "
            "what was considered; if it was taken up after the plan was agreed, say so under "
            "Deviations from the plan, naming it in backticks",
        ))  # fmt: skip
    return findings


__all__ = ["check_software", "judge_software", "planned_packages", "script_loads"]
