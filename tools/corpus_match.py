"""Whether a judged finding is in a run's report, and in which of four states: the part of
`tools/corpus.py` that matches findings. docs/corpus.md says what each step of the match
holds, and DESIGN.md's Known gaps what it cannot see.
"""

from __future__ import annotations

import collections
import re

LOUD = frozenset({"warn", "fail", "warning", "error"})
#: A short form a G14 finding is about, where its message opens on it.
FORM = re.compile(r"^(?:Language \(G14\): )?(\S+) is (?:used|defined)")
#: Words in quotes, each kind closed by its own mark; an apostrophe inside a word, as in
#: "the paper's text", opens nothing.
QUOTED = re.compile(
    r"(?<!\w)'([^']{1,40})'(?!\w)|\"([^\"]{1,40})\"|`([^`]{1,40})`"
    "|\N{LEFT DOUBLE QUOTATION MARK}([^\N{RIGHT DOUBLE QUOTATION MARK}]{1,40})"
    "\N{RIGHT DOUBLE QUOTATION MARK}"
)
ABSOLUTE = re.compile(r"(?:(?<![\w/])[A-Za-z]:/|(?<![\w.:/])/(?=[^\s/]+/))(?:[^\s/:'\"]+/)+")
RUN_DIR = re.compile(r"runs/[^/\s]+/")
NUMBER = re.compile(r"(?<![\w.])(\d+(?:\.\d+)?|\.\d+)")
#: A test statistic as typed, its name, its degrees of freedom and its value: "t(29) = 2.05",
#: "F(2, 55) = 0.62", "\N{GREEK SMALL LETTER CHI}2(1) = 3.84".
#: A number as printed: a minus of any of three kinds, a point or a middle dot.
VALUE = r"[-\N{MINUS SIGN}\N{EN DASH}]?\d*[.\N{MIDDLE DOT}]?\d+"
STATISTIC = re.compile(
    r"(?<!\w)(chi-squared|t|F|z|r|H|U|W|\N{GREEK SMALL LETTER CHI}\N{SUPERSCRIPT TWO}|"
    r"\N{GREEK SMALL LETTER CHI}2|chi2|X2)\s*(?:\(\s*([^()=]{1,30}?)\s*\))?\s*=\s*"
    rf"({VALUE})"
)  # the package writes "chi-squared(1) = 3.84" and "z = 2.10" (stats/reported.py, `written`)
#: A P value as the text states it: "P = 0.20", "p < .05".
STATED_P = re.compile(rf"(?<!\w)[Pp]\s*([=<>\N{{LESS-THAN OR EQUAL TO}}])\s*({VALUE})")
#: The part of the paper a G14 finding names, which tells two findings of one form apart.
REGION = re.compile(r"\bin the (abstract|main text|supplement)\b", re.IGNORECASE)


def norm(text: object) -> str:
    """A message without the folders a run was made in, which differ from run to run."""
    plain = str(text or "").replace("\\", "/")
    return RUN_DIR.sub("runs/", ABSOLUTE.sub("", plain))


def form_of(finding: dict) -> str | None:
    hit = FORM.match(str(finding.get("message") or ""))
    return hit.group(1) if hit else None


def forms_named(finding: dict) -> set[str]:
    named = {f.get("form") for f in finding.get("forms") or [] if isinstance(f, dict)}
    return {*named, form_of(finding)} - {None}


def loud(finding: dict) -> bool:
    return str(finding.get("severity")).lower() in LOUD


def is_question(finding: dict) -> bool:
    if finding.get("question") is True or str(finding.get("code", "")).startswith("question"):
        return True
    return str(finding.get("severity")).lower() == "info" and "?" in str(finding.get("message"))


def relative(path: object, slug: str) -> str | None:
    """A finding's file as a path inside the paper's folder or its project, wherever the run
    was made; None where the finding names no file."""
    if not path:
        return None
    text = str(path).replace("\\", "/")
    for marker in (f"/{slug}/project/", f"/{slug}/files/"):
        if slug and marker in text:
            return text.rsplit(marker, 1)[1]
    return text.removeprefix("./")


def same_place(old: dict, new: dict, slug: str = "") -> bool:
    """The same line of the same file; a finding that names no file is at the place of one
    that names none."""
    line = old.get("line")
    if line is None or new.get("line") != line:
        return False
    return relative(old.get("path"), slug) == relative(new.get("path"), slug)


def quoted(message: object) -> list[str]:
    """The words a message sets in quotes, in order."""
    return [next(g for g in hit.groups() if g is not None)
            for hit in QUOTED.finditer(str(message or ""))]  # fmt: skip


def _value(value: str) -> str:
    """A number as a pattern that takes any minus and either point, and ends where it ends."""
    body = "".join("[-\N{MINUS SIGN}\N{EN DASH}]" if c in "-\N{MINUS SIGN}\N{EN DASH}" else
                   "[.\N{MIDDLE DOT}]" if c in ".\N{MIDDLE DOT}" else re.escape(c)
                   for c in value)  # fmt: skip
    return body + r"(?![\d]|[.\N{MIDDLE DOT}]\d)"


def _statistic(message: str) -> re.Pattern | None:
    """The first test statistic with its value, its spacing free; else the stated P."""
    hit = STATISTIC.search(message)
    if hit:
        name, df, value = hit.groups()
        dfs = r"\s*,\s*".join(re.escape(part.strip()) for part in (df or "").split(","))
        within = rf"\s*\(\s*{dfs}\s*\)" if df else ""
        return re.compile(rf"(?<!\w){re.escape(name)}{within}\s*=\s*{_value(value)}")
    stated = STATED_P.search(message)
    if stated:
        sign, value = stated.groups()
        return re.compile(rf"(?<!\w)[Pp]\s*{re.escape(sign)}\s*{_value(value)}")
    return None


def key_of(old: dict) -> re.Pattern | None:
    """What a finding is about, to be found in another's message: its short form; else a
    test statistic with its value as typed, "t(29) = 2.05", or failing that the P it states,
    never its degrees of freedom alone; else its first quoted words; else its first number
    of two characters or more (a single digit stands in too many messages)."""
    message = str(old.get("message") or "")
    form = form_of(old)
    if form:
        return re.compile(rf"(?<!\w){re.escape(form)}(?!\w)")
    statistic = _statistic(message)
    if statistic is not None:
        return statistic
    word = next(iter(quoted(message)), None)
    if word:
        return re.compile(rf"(?<!\w){re.escape(word)}(?!\w)")
    number = next((n for n in NUMBER.findall(message) if len(n) >= 2), None)
    return re.compile(rf"(?<![\w.]){re.escape(number)}(?![\w]|\.\d)") if number else None


def region(message: object) -> str | None:
    hit = REGION.search(str(message or ""))
    return hit.group(1).lower() if hit else None


def _same_code(old: dict, new: dict) -> bool:
    return new.get("gate") == old.get("gate") and new.get("code") == old.get("code")


def _by_message(old: dict, new: dict, slug: str, place: bool) -> bool:
    return norm(new.get("message")) == norm(old.get("message")) and (
        not place or same_place(old, new, slug))


def _by_context(old: dict, new: dict, slug: str, place: bool, shared: bool = True) -> bool:
    """The same context. Where the context is `shared` (another judged finding of the code
    has it, or another new one), the message must name what the old one was about too, and
    one with nothing to name is refused: two findings of one sentence share a context. A
    finding about another short form or name is another finding, and a grouped finding,
    which copies its first form's context, must list the old one's form."""
    context = norm(old.get("context"))
    if not context or norm(new.get("context")) != context:
        return False
    if place and not same_place(old, new, slug):
        return False
    key = key_of(old)
    if shared and (key is None or not key.search(str(new.get("message") or ""))):
        return False
    if new.get("forms"):
        return subject_of(old) in forms_named(new)
    # Two short forms or names of one sentence are two findings, shared or not.
    mine, theirs = subject_of(old), subject_of(new)
    return not (mine and theirs and mine != theirs)


def _by_both(old: dict, new: dict, slug: str, shared: bool = True) -> bool:
    return _by_message(old, new, slug, False) and _by_context(old, new, slug, False, shared)


def _about(old: dict, new: dict, slug: str, form: bool = False) -> bool:
    """The same word, at the same place or in the same part of the paper. A form a finding
    lists stands for that form in the part its message names, or in the paper where neither
    names one."""
    key = key_of(old)
    if key is None or not key.search(str(new.get("message") or "")):
        return False
    part = region(old.get("message"))
    return same_place(old, new, slug) or ((form or part is not None)
                                          and part == region(new.get("message")))


def subject_of(old: dict) -> str | None:
    """The short form or the quoted name a finding is about, as a question's `forms` give it."""
    return form_of(old) or next(iter(quoted(old.get("message"))), None)


def _entry(finding: dict, entry: dict) -> dict:
    """One form of a finding that lists several, with its own place and message."""
    return {**finding, **{k: entry[k] for k in ("line", "path", "message") if k in entry}}


#: The passes of `match`, by name, in order; `tools/corpus_keys.py` ties a judged finding to
#: a key only by the first two.
PASSES = ("message+place", "context+place", "message+context", "message", "context")
STRONG = PASSES[:2]


def match(olds: list[dict], new: list[dict], slug: str = "",
          alone: frozenset[int] = frozenset(), how: dict | None = None,
          strong: dict | None = None) -> dict[int, tuple[int, bool]]:  # fmt: skip
    """Each old finding's own finding among a report's new ones, one to one: for every old
    one first the same message at the same place, then the same context at the same place,
    then the same message and context, then the same message, then the same context (each
    context naming what the old one was about), then the same word at the same place or in
    the same part of the paper; a finding taken by one is not taken by another. A
    finding that lists forms gives each form once. An old finding that was the only one of
    its code in its report (`alone`) is the only one of its code in the new report too, where
    that names its word. Says (new index, whether by a form); `how` is given each pairing's
    pass, `form:<entry>` for a form of a finding that lists them, and `strong` each old
    finding's candidates by the first two passes, taken or not."""
    taken: set[tuple] = set()
    found: dict[int, tuple[int, bool]] = {}

    def token(i: int, old: dict) -> tuple:
        return (i, "whole", subject_of(old)) if new[i].get("forms") else (i,)

    def free(i: int, old: dict) -> bool:
        return (i,) not in taken and token(i, old) not in taken

    def take(k: int, i: int, old: dict, entry: int | None = None) -> None:
        found[k] = (i, entry is not None)
        taken.add(token(i, old) if entry is None else (i, "form", entry))

    contexts = collections.Counter((o.get("gate"), o.get("code"), norm(o.get("context")))
                                   for o in [*olds, *new])  # fmt: skip

    def shared(old: dict) -> bool:
        # More than the old one and the one it would take.
        return contexts[(old.get("gate"), old.get("code"), norm(old.get("context")))] > 2

    passes = [lambda o, f: _by_message(o, f, slug, True),
              lambda o, f: _by_context(o, f, slug, True, shared(o)),
              lambda o, f: _by_both(o, f, slug, shared(o)),
              lambda o, f: _by_message(o, f, slug, False),
              lambda o, f: _by_context(o, f, slug, False, shared(o))]  # fmt: skip
    told = how if how is not None else {}
    if strong is not None:
        for k, old in enumerate(olds):
            strong[k] = [i for i, f in enumerate(new) if _same_code(old, f)
                         and (passes[0](old, f) or passes[1](old, f))]  # fmt: skip
    for name, test in zip(PASSES, passes, strict=True):
        for k, old in enumerate(olds):
            if k not in found:
                i = next((i for i, f in enumerate(new) if _same_code(old, f) and free(i, old)
                          and test(old, f)), None)  # fmt: skip
                if i is not None:
                    take(k, i, old)
                    told[k] = name
    for k, old in enumerate(olds):
        for i, f in enumerate(new):
            if k in found or not _same_code(old, f) or not free(i, old):
                continue
            entries = [e for e in f.get("forms") or [] if isinstance(e, dict)]
            single = k in alone and sum(_same_code(old, g) for g in new) == 1 and bool(
                (key := key_of(old)) and key.search(str(f.get("message") or "")))
            if not entries and (single or _about(old, f, slug)):
                take(k, i, old)
                told[k] = "word"
            j = next((j for j, e in enumerate(entries) if (i, "form", j) not in taken
                      and e.get("form") == subject_of(old)
                      and _about(old, _entry(f, e), slug, True)), None)  # fmt: skip
            if k not in found and j is not None:
                take(k, i, old, j)
                told[k] = f"form:{j}"
    return found


def states(olds: list[dict], new: list[dict], slug: str = "",
           alone: frozenset[int] = frozenset()) -> list[tuple[str, list[int]]]:  # fmt: skip
    """Each judged finding's state among a report's findings, and the findings that make it
    so. A question or another code's warning at its place counts only where it names what the
    old one was about (`key_of`) and no judged finding of the report took it."""
    matched = match(olds, new, slug, alone)
    paired = {i for i, _ in matched.values()}
    out = []
    for k, old in enumerate(olds):
        if k in matched:
            i = matched[k][0]
            quiet = new[i].get("question") or not loud(new[i])
            out.append(("asked" if quiet else "reported", [i]))
            continue
        key = key_of(old)
        here = [i for i, f in enumerate(new) if key and i not in paired
                and not _same_code(old, f) and same_place(old, f, slug)
                and key.search(str(f.get("message") or ""))]  # fmt: skip
        asked = [i for i in here if is_question(new[i])]
        louder = [i for i in here if loud(new[i])]
        form = form_of(old) if old.get("gate") == "G14" else None
        about = [i for i, f in enumerate(new) if form and f.get("gate") == "G14"
                 and f.get("code") != old.get("code") and form in forms_named(f)]
        if asked:
            out.append(("asked", asked))
        elif louder:
            out.append(("elsewhere", louder))
        elif [i for i in about if loud(new[i])]:
            out.append(("elsewhere", [i for i in about if loud(new[i])]))
        elif about:
            out.append(("asked", about))
        else:
            out.append(("gone", []))
    return out


def state(old: dict, new: list[dict], slug: str = "") -> tuple[str, list[int]]:
    """One judged finding's state among a report's findings (`states`)."""
    return states([old], new, slug)[0]
