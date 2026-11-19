"""Every finding the source makes with no subject is one whose code may fall back (`keys`).

`tests/test_finding_keys.py` runs papers and projects, and so sees only the codes its inputs
happen to make. This reads the source instead: each `Finding`, `Question`, `Item` or
`question` made with no `subject`, and not handed to what keys it (`about`, `of_number`,
`_notice`), is a code that falls back on its context. Its code is in `ON_THE_FALLBACK` with
why, or its gate is one whose findings the corpus never reads (`WHOLE_GATES`); a code made
from a name, not typed, is listed by where it is made (`VARIABLE_SITES`). A list that keys as
one thing (`Asked`, `Listed`, `Undefined`) names its own key.
"""

from __future__ import annotations

import ast
from pathlib import Path

from test_finding_keys import KEYED, ON_THE_FALLBACK

SRC = Path(__file__).resolve().parents[1] / "src" / "manuscript_guard"

#: What makes a finding, by the module it is imported from, and where the code and the gate
#: stand among its arguments where they are not given by name.
MAKERS = {
    "manuscript_guard.findings": {"Finding": (1, 0), "Question": (1, 0)},
    "manuscript_guard.auditing.report": {"Item": (2, 1), "question": (1, None)},
}
#: What makes a finding that keys itself, or keys one it is handed.
KEYING = {"about", "of_number", "_notice"}
SELF_KEYED = {"Asked", "Listed", "Undefined"}

_RECORDS = ("reads the project's records, not a paper's text, and the corpus of judged papers "
            "never runs it")  # fmt: skip
#: The gates the corpus never reads, each with why: their findings are keyed on their context.
WHOLE_GATES = {
    "G0": f"the project's settings and files: {_RECORDS}",
    "G1": f"the analysis's provenance and inputs: {_RECORDS}",
    "G3": f"the figures and their files: {_RECORDS}",
    "G4": f"the journal's profile; in an audit only under --journal: {_RECORDS}",
    "G5": f"the reporting checklist: {_RECORDS}",
    "G9": f"the models the analysis fitted: {_RECORDS}",
    "G10": f"the figures' reviews: {_RECORDS}",
    "G11": f"the review panel's records: {_RECORDS}",
    "G12": f"the analysis plan and its registration: {_RECORDS}",
    "G13": f"the declarations and the authors: {_RECORDS}",
    "G15": f"the statistician's sign-offs on the models: {_RECORDS}",
    "G16": f"the data's quality rules: {_RECORDS}",
    "BUILD": f"the build of the document: {_RECORDS}",
    "COMM": f"the communication of a published paper: {_RECORDS}",
    "DEPOSIT": f"a deposit's bundle: {_RECORDS}",
    "PACKAGE": f"the reproducibility package: {_RECORDS}",
    "VAULT": f"the data held in the vault: {_RECORDS}",
    "VERIFY": f"a re-run of the analysis: {_RECORDS}",
    "REWORDED": f"a rewording checked against its source: {_RECORDS}",
}
#: G7 outside the audit reads the literature's records (`literature/`), which an audited paper
#: has none of; the audit's G7 keys each entry by its label (`auditing.references.Problem`).
G7_RECORDS = "gates/"

#: Where a finding is made with a code that is a name, not typed, each with why.
VARIABLE_SITES = {
    "gates/numbers.py:_emitted_tables": "a table of the results; its code is one of two",
    "gates/pointers.py:_bound": "a pointer's binding; the code is one of two pointer codes",
    "gates/held_out.py:said": "the plan's held-out data, G12, a project record",
    "gates/held_out.py:check_held_out": "the plan's held-out data, G12, a project record",
    "gates/held_out.py:check_held_out_reads": "the plan's held-out data, G1, a project record",
    "gates/figure_source.py:judge_code_numbers": "a figure's code block, G3, a project record",
    "gates/formats.py:not_read_in_latex": "a gate's note that it reads no LaTeX",
    "gates/numbers.py:abstract_in_header": "the front matter's abstract, a settings note",
    "gates/numbers.py:unreadable_header": "the front matter that could not be read",
    "contracts/_schema.py:validate": "a settings file's schema, a project record",
    "cli.py:_guarded": "a gate that raised, `gate-errored`, which names the gate",
    "gates/recomputed.py:_p_finding": "G8's recomputation from the results, a project record",
    "gates/recomputed.py:_worded_finding": "G8's recomputation from the results",
    "gates/relations.py:_finding": "G8's relations between results, a project record",
    "gates/consistency.py:check_consistency": "G8's consistency of the results",
    "auditing/report.py:_document_items": "an editor's list of what a .docx holds",
    "auditing/report.py:_causal_items": "the causal words, one code",
    "auditing/package.py:say": "the authors' package, PACKAGE",
    "auditing/report.py:question": "made by `question`, keyed by its callers (`of_number`)",
    "comparing/differences.py:_item": "made by `_item`, keyed by its callers (`about`) but "
    "for compare's claims, which are on the fallback",
    "comparing/differences.py:_display_item": "compare's tables and figures, on the fallback",
    "comparing/letters.py:comment_items": "a referee's comment matched to the revision",
    "comparing/letters.py:letter_items": "a response letter's quotation",
}


def _module(name: str, here: Path, level: int) -> str:
    if not level:
        return name
    parts = list(here.relative_to(SRC.parent).with_suffix("").parts)
    base = parts[: len(parts) - level]
    return ".".join([*base, *([name] if name else [])])


def _path_of(module: str) -> Path | None:
    parts = module.split(".")
    if parts[0] != "manuscript_guard":
        return None
    base = SRC.joinpath(*parts[1:])
    return next((one for one in (base.with_suffix(".py"), base / "__init__.py")
                 if one.is_file()), None)  # fmt: skip


_KNOWN: dict[Path, dict[str, str]] = {}


def _constants(path: Path) -> dict[str, str]:
    """The strings a module names at its top, its own and those it imports from the
    package; each module read once, an import cycle read as far as it got."""
    if path in _KNOWN:
        return _KNOWN[path]
    found: dict[str, str] = {}
    _KNOWN[path] = found
    for node in ast.parse(path.read_text(encoding="utf-8")).body:
        if isinstance(node, ast.ImportFrom):
            other = _path_of(_module(node.module or "", path, node.level))
            if other is not None and other != path:
                theirs = _constants(other)
                found.update({alias.asname or alias.name: theirs[alias.name]
                              for alias in node.names if alias.name in theirs})  # fmt: skip
        pairs = []
        if isinstance(node, ast.Assign):
            pairs = [(target, node.value) for target in node.targets]
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            pairs = [(node.target, node.value)]
        for target, value in pairs:
            if (isinstance(target, ast.Name) and isinstance(value, ast.Constant)
                    and isinstance(value.value, str)):
                found[target.id] = value.value
    return found


def _makers(tree: ast.AST, path: Path) -> dict[str, tuple[int, int | None]]:
    """What makes a finding in this module, by the name it is called by."""
    made: dict[str, tuple[int, int | None]] = {}
    own = ".".join(path.relative_to(SRC.parent).with_suffix("").parts)
    made.update(MAKERS.get(own, {}))
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            module = _module(node.module or "", path, node.level)
            for alias in node.names:
                if alias.name in MAKERS.get(module, {}):
                    made[alias.asname or alias.name] = MAKERS[module][alias.name]
    return made


def unkeyed() -> list[tuple[str, str, str]]:
    """Each finding the source makes with no subject: its gate, its code and where it is
    made, `file:function`; a name in angle brackets where either is not typed."""
    found = []
    for path in sorted(SRC.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        makers, names = _makers(tree, path), _constants(path)
        parents = {child: node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)}

        def value(node: ast.AST | None, names: dict = names) -> str:
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                return node.value
            if isinstance(node, ast.Name):
                return names.get(node.id, f"<{node.id}>")
            return "<?>"

        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
                continue
            if node.func.id not in makers:
                continue
            given = {one.arg: one.value for one in node.keywords}
            if "subject" in given or None in given:
                continue
            up = parents.get(node)
            if isinstance(up, ast.Call) and getattr(up.func, "id", None) in KEYING:
                continue
            at_code, at_gate = makers[node.func.id]
            code = given.get("code", node.args[at_code] if len(node.args) > at_code else None)
            gate_node = given.get("gate")
            if gate_node is None and at_gate is not None and len(node.args) > at_gate:
                gate_node = node.args[at_gate]
            gate = "audit" if node.func.id == "question" else value(gate_node)
            where, scope = path.relative_to(SRC).as_posix(), node
            while scope in parents and not isinstance(scope, ast.FunctionDef):
                scope = parents[scope]
            name = scope.name if isinstance(scope, ast.FunctionDef) else "<module>"
            found.append((gate, value(code), f"{where}:{name}"))
    return found


def _whole(gate: str, site: str) -> bool:
    """Whether the gate is one the corpus never reads, G7 outside the audit among them."""
    return gate in WHOLE_GATES or (gate == "G7" and site.startswith(G7_RECORDS))


def _allowed(gate: str, code: str, site: str) -> bool:
    if site in VARIABLE_SITES or _whole(gate, site):
        return True
    if code.startswith("<") or gate.startswith("<"):
        return False
    return code in ON_THE_FALLBACK


def test_every_finding_made_without_a_subject_is_listed() -> None:
    """A finding made with no subject keys on its context. Its code is listed, with why, or
    its gate is one the corpus never reads; and a code that is a name is listed where it is
    made. A new code made with no subject fails here until it names one or is listed."""
    found = unkeyed()
    assert len(found) > 300, "the walk found the findings"
    unlisted = sorted({(gate, code, site) for gate, code, site in found
                       if not _allowed(gate, code, site)})  # fmt: skip
    assert unlisted == [], unlisted


def test_no_code_a_family_keys_is_made_without_a_subject() -> None:
    """The codes the families key never fall back, wherever they are made (`KEYED`)."""
    made = sorted({(code, site) for gate, code, site in unkeyed()
                   if code in KEYED and not _whole(gate, site)})  # fmt: skip
    assert made == [], made


def test_every_listing_is_of_something_made_and_says_why() -> None:
    sites = {site for _gate, _code, site in unkeyed()}
    assert sorted(set(VARIABLE_SITES) - sites) == []
    assert all(reason.split() for reason in (*WHOLE_GATES.values(), *VARIABLE_SITES.values()))
