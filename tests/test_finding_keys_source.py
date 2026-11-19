"""Every finding the source makes with no subject is one whose code may fall back (`keys`).

`tests/test_finding_keys.py` runs papers and projects, and so sees only the codes its inputs
happen to make. This reads the source instead: each `Finding`, `Question`, `Item` or
`question`, and each arithmetic `Disagreement` or `Asked`, made with no `subject`, and not
handed to `about` with one, is a code that falls back on its context. `of_number` and
`_notice` key what they are handed, so that is held where it is made: a `Disagreement`
here, and a note on the inputs where it is added to its list (`unnoted`). Its code is in
`ON_THE_FALLBACK` with why, or its gate is one whose findings the corpus never reads
(`WHOLE_GATES`); a code made from a name, not typed, is listed by where it is made
(`VARIABLE_SITES`). A list that keys as one thing (G14's `Asked`, `Listed`, `Undefined`)
names its own key.
"""

from __future__ import annotations

import ast
from pathlib import Path

from test_finding_keys import KEYED, ON_THE_FALLBACK

SRC = Path(__file__).resolve().parents[1] / "src" / "manuscript_guard"

#: What makes a finding, by the module it is imported from, and where the code and the gate
#: stand among its arguments where they are not given by name.
MAKERS = {
    "manuscript_guard.findings": {"Finding": (1, 0, None, None), "Question": (1, 0, None, None)},
    "manuscript_guard.auditing.report": {"Item": (2, 1, None, None),
                                         "question": (1, None, "audit", None)},
    "manuscript_guard.audit": {"Disagreement": (4, None, "audit", "does-not-fit")},
    "manuscript_guard.auditing.adjusted": {"Asked": (4, None, "audit", None)},
}  # fmt: skip
#: The lists of the audit's notes on its inputs, each of which is a `keys.Notice`, and the
#: modules that fill them.
NOTES = {"passed_over", "not_audited", "headings"}
NOTED_IN = ("audit.py", "auditing/latex.py", "cli.py")
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


#: Where a note is added as a string and made a `Notice` afterwards, with why.
NOTE_SITES = {
    "auditing/latex.py:read_latex": "each note on a file the LaTeX reading passes over is "
    "made a Notice about that file once its notes are said",
}
#: Where an arithmetic finding is made with no subject and keyed by its caller, or never
#: reaches an item that takes its code, each with why.
KEYED_BY_CALLER = {
    "auditing/adjusted.py:asked_p": "keyed by its caller, `audit._disagreements`",
    "auditing/adjusted.py:asked_share": "keyed by its caller, `audit._disagreements`",
    "audit.py:_flows": "a flow's finding: its item says flow-broken or flow-note, listed",
    "audit.py:_not_assessable": "a mean not assessable: its item says "
    "mean-not-assessable, listed",
    "audit.py:_margins": "a total or an n over the header: its item says sum-off, "
    "over-header-n or count-recoverable, listed",
    "auditing/skew.py:_passed_over": "a row passed over: its note is listed",
    "auditing/spreads.py:whole_number_sd": "an SD not possible: its item says sd-not-possible, "
    "listed",
    "auditing/spreads.py:binary_means": "a binary mean not possible: its item says "
    "binary-not-possible, listed",
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


def _makers(tree: ast.AST, path: Path) -> dict[str, tuple]:
    """What makes a finding in this module, by the name it is called by: where its code and
    its gate stand among the arguments, and the gate and the code it has where none is
    given."""
    made: dict[str, tuple] = {}
    own = ".".join(path.relative_to(SRC.parent).with_suffix("").parts)
    made.update(MAKERS.get(own, {}))
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            module = _module(node.module or "", path, node.level)
            for alias in node.names:
                if alias.name in MAKERS.get(module, {}):
                    made[alias.asname or alias.name] = MAKERS[module][alias.name]
    return made


def _names_a_subject(call: ast.Call) -> bool:
    """Whether a call that keys what it is handed gives it a subject: `about`'s second
    argument, or `subject=`, is anything but the constant None. `of_number` and `_notice`
    take the subject from what they are handed, which is held where it is made."""
    if getattr(call.func, "id", None) != "about":
        return True
    given = {one.arg: one.value for one in call.keywords}
    subject = given.get("subject", call.args[1] if len(call.args) > 1 else None)
    return not (subject is None or (isinstance(subject, ast.Constant) and subject.value is None))


def _makes_notices(node: ast.AST) -> bool:
    return any(isinstance(one, ast.Call) and getattr(one.func, "id", None) == "Notice"
               for one in ast.walk(node))  # fmt: skip


def _a_notice(node: ast.AST, scope: ast.AST) -> bool:
    """Whether what is put in a list of notes is a `Notice`: one made there, a name the
    function binds to what makes Notices, or another such list of notes."""
    if isinstance(node, ast.Starred):
        node = node.value
    if isinstance(node, (ast.ListComp, ast.GeneratorExp)):
        node = node.elt
    if isinstance(node, (ast.List, ast.Tuple)):
        return all(_a_notice(one, scope) for one in node.elts)
    if isinstance(node, ast.Attribute):
        return node.attr in NOTES
    if isinstance(node, ast.Name):
        return any(isinstance(one, ast.Assign) and _makes_notices(one.value)
                   and any(getattr(target, "id", None) == node.id for target in one.targets)
                   for one in ast.walk(scope))  # fmt: skip
    return isinstance(node, ast.Call) and getattr(node.func, "id", None) == "Notice"


def _put_in_notes(node: ast.AST) -> list[ast.AST]:
    """What `node` puts in one of the lists of notes: an append, an extend, an insert, a
    `+=`, an assignment, or `AuditReport(...)` and `replace(...)` given one by name."""
    def notes(target: ast.AST) -> bool:
        return isinstance(target, ast.Attribute) and target.attr in NOTES

    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and notes(
            node.func.value):
        return {"append": node.args[:1], "extend": node.args[:1],
                "insert": node.args[1:2]}.get(node.func.attr, [])  # fmt: skip
    if isinstance(node, ast.AugAssign) and notes(node.target):
        return node.value.elts if isinstance(node.value, ast.List) else [node.value]
    if isinstance(node, ast.Assign) and any(notes(target) for target in node.targets):
        return [node.value]
    if isinstance(node, ast.Call) and getattr(node.func, "id", None) in ("AuditReport",
                                                                         "replace"):
        return [one.value for one in node.keywords if one.arg in NOTES]
    return []


def unnoted() -> list[tuple[str, int]]:
    """Each place a note on the inputs is put in its list as a plain string, as
    `file:function` and the line: it would fall back on its context
    (`auditing.report._notice`)."""
    found = []
    for path in (SRC / name for name in NOTED_IN):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        parents = {child: node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)}
        for node in ast.walk(tree):
            scope = node
            while scope in parents and not isinstance(scope, ast.FunctionDef):
                scope = parents[scope]
            for one in _put_in_notes(node):
                if not _a_notice(one, scope):
                    name = scope.name if isinstance(scope, ast.FunctionDef) else "<module>"
                    found.append((f"{path.relative_to(SRC).as_posix()}:{name}", node.lineno))
    return found


def made(instead: dict[str, str] | None = None) -> list[tuple[str, str, str, bool]]:
    """Each finding the source makes: its gate, its code, where it is made, `file:function`,
    and whether it names its subject; a name in angle brackets where the gate or the code is
    not typed. `instead` gives the text to read in place of a file's, by its path under
    the package, to show what the walk makes of a change."""
    found = []
    for path in sorted(SRC.rglob("*.py")):
        written = (instead or {}).get(path.relative_to(SRC).as_posix())
        tree = ast.parse(written if written is not None else path.read_text(encoding="utf-8"))
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
            up = parents.get(node)
            keyed = "subject" in given or None in given or (
                isinstance(up, ast.Call) and getattr(up.func, "id", None) in KEYING
                and _names_a_subject(up))  # fmt: skip
            at_code, at_gate, gate_given, code_given = makers[node.func.id]
            code = given.get("code", node.args[at_code] if len(node.args) > at_code else None)
            gate_node = given.get("gate")
            if gate_node is None and at_gate is not None and len(node.args) > at_gate:
                gate_node = node.args[at_gate]
            gate = gate_given or value(gate_node)
            if code is None and code_given is not None:
                code = ast.Constant(code_given)
            where, scope = path.relative_to(SRC).as_posix(), node
            while scope in parents and not isinstance(scope, ast.FunctionDef):
                scope = parents[scope]
            name = scope.name if isinstance(scope, ast.FunctionDef) else "<module>"
            found.append((gate, value(code), f"{where}:{name}", keyed))
    return found


def unkeyed(instead: dict[str, str] | None = None) -> list[tuple[str, str, str]]:
    """Each finding the source makes with no subject (`made`)."""
    return [(gate, code, site) for gate, code, site, keyed in made(instead) if not keyed]


def _whole(gate: str, site: str) -> bool:
    """Whether the gate is one the corpus never reads, G7 outside the audit among them."""
    return gate in WHOLE_GATES or (gate == "G7" and site.startswith(G7_RECORDS))


def _allowed(gate: str, code: str, site: str) -> bool:
    if code in ON_THE_FALLBACK or _whole(gate, site) or site in KEYED_BY_CALLER:
        return True
    # A site listed covers the codes it makes from a name, and never a code typed there.
    return site in VARIABLE_SITES and code.startswith("<")


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
                   if code in KEYED and not _whole(gate, site)
                   and site not in KEYED_BY_CALLER})  # fmt: skip
    assert made == [], made


def test_every_note_on_the_inputs_is_a_notice() -> None:
    """A note added to the audit's lists of what it read is a `Notice`, which knows the file
    or the part it is about, or is made one where its file's notes are said (`NOTE_SITES`)."""
    found = unnoted()
    assert sorted((site, line) for site, line in found if site not in NOTE_SITES) == []
    assert sorted(set(NOTE_SITES) - {site for site, _line in found}) == []


def test_a_site_keyed_by_its_caller_makes_nothing_keyed_itself() -> None:
    """A function listed as keyed by its caller makes only what its caller keys: one that
    also made a keyed finding would let a new unkeyed one in beside it pass."""
    sites = {site for _gate, _code, site, keyed in made() if keyed}
    assert sorted(sites & set(KEYED_BY_CALLER)) == []
    assert sorted(set(KEYED_BY_CALLER) - {site for _g, _c, site in unkeyed()}) == []


def test_dropping_the_subject_of_a_grim_or_a_skewed_mean_is_caught() -> None:
    """The walk is shown a copy of the source with the subject taken off the GRIM mean, and
    one with it taken off the skewed mean: each is a code a family keys, made without one."""
    for where, typed, site in (
        ("audit.py", 'subject=f"{mean.mean}/n={mean.n}@{_header_of(table, mean)}",',
         "audit.py:_whole_number_means"),
        ("auditing/skew.py", "subject=spread.printed,", "auditing/skew.py:non_negative_means"),
    ):
        text = (SRC / where).read_text(encoding="utf-8")
        assert text.count(typed) == 1, (where, typed)
        caught = [one for one in unkeyed({where: text.replace(typed, "")}) if one[2] == site]
        assert caught and not any(_allowed(*one) for one in caught), (where, caught)


def test_every_listing_is_of_something_made_and_says_why() -> None:
    sites = {site for _gate, _code, site in unkeyed()}
    assert sorted(set(VARIABLE_SITES) - sites) == []
    assert all(reason.split() for reason in (*WHOLE_GATES.values(), *VARIABLE_SITES.values()))
