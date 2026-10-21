"""Which parts of the two documents are the same, which were edited, and which are new or gone.

Two levels, one rule each. Blocks (paragraphs and tables, a table's rows) are paired first by
being identical, in order (`difflib`, with no heuristic for frequent items, so the pairing
depends on nothing but the two sequences). Between two identical pairs, what is left on each
side is paired only where it is alike: a paragraph with a paragraph sharing more than half its
words in order, a table with a table of as many columns, a row with a row that has a cell in
common. Each pairing keeps the order of both documents. Whatever is not paired was deleted or
inserted; a paragraph moved is one of each.

Within a paragraph, atoms are aligned the same way, and then a short stretch left unchanged
between two changes is taken into them: "The ~~odd~~ ratio ~~was~~" reads worse than "~~The
odd ratio was~~ The ratio is". A stretch is taken in when it holds no word, or when it is
shorter than the change on each side of it (diff-match-patch's semantic clean-up, with a
strict bound so that two numbers apart stay two changes).
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Sequence
from difflib import SequenceMatcher

#: (tag, i1, i2, j1, j2) as `difflib` writes them: "equal", "delete", "insert" or "replace".
Op = tuple[str, int, int, int, int]
#: More than this share of the words in order makes two paragraphs one edited.
ALIKE = 0.5


def _matched(a: Sequence, b: Sequence) -> int:
    return sum(
        block.size for block in SequenceMatcher(None, a, b, autojunk=False).get_matching_blocks()
    )


def alike(a: Sequence, b: Sequence) -> float:
    """The share of the longer side's words that the two have in common, in order."""
    longest = max(len(a), len(b))
    if not longest:
        return 0.0
    # The words in common, in any order, bound the words in common in order.
    if sum((Counter(a) & Counter(b)).values()) <= ALIKE * longest:
        return 0.0
    return _matched(a, b) / longest


def _kind(op: tuple[int, int, int, int]) -> str:
    i1, i2, j1, j2 = op
    if i1 == i2:
        return "insert"
    if j1 == j2:
        return "delete"
    return "replace"


def _merged(ops: list[Op]) -> list[Op]:
    """Adjacent changes as one."""
    out: list[Op] = []
    for op in ops:
        if out and op[0] != "equal" and out[-1][0] != "equal":
            _t, i1, _i2, j1, _j2 = out[-1]
            span = (i1, op[2], j1, op[4])
            out[-1] = (_kind(span), *span)
        elif op[1] != op[2] or op[3] != op[4]:
            out.append(op)
    return out


def changes(
    a: Sequence, b: Sequence, length_a: Sequence[int], length_b: Sequence[int],
    word_a: Sequence[bool],
) -> list[Op]:  # fmt: skip
    """How `a` became `b`: the stretches equal, and those changed, a short equal stretch
    between two changes taken into them. `length_*` is each item's length in characters,
    `word_a` whether each item of `a` is a word."""
    ops = _merged(SequenceMatcher(None, a, b, autojunk=False).get_opcodes())
    changed = True
    while changed:
        changed = False
        for index in range(1, len(ops) - 1):
            tag, i1, i2, _j1, _j2 = ops[index]
            if tag != "equal" or ops[index - 1][0] == "equal" or ops[index + 1][0] == "equal":
                continue
            size = sum(length_a[i1:i2])

            def side(op: Op) -> int:
                return max(sum(length_a[op[1] : op[2]]), sum(length_b[op[3] : op[4]]))

            wordless = not any(word_a[i1:i2])
            if wordless or (size < side(ops[index - 1]) and size < side(ops[index + 1])):
                ops[index] = ("replace", *ops[index][1:])
                ops = _merged(ops)
                changed = True
                break
    return ops


def pairs(n: int, m: int, score: Callable[[int, int], float]) -> list[tuple[int, int]]:
    """The pairs of `n` items and `m` items, in the order of both, whose scores add up to
    the most; only pairs that score above nothing. On a tie, a pair is taken."""
    best = [[0.0] * (m + 1) for _ in range(n + 1)]
    taken: dict[tuple[int, int], float] = {}
    for i in range(n - 1, -1, -1):
        for j in range(m - 1, -1, -1):
            skip = max(best[i + 1][j], best[i][j + 1])
            value = score(i, j)
            if value > 0 and value + best[i + 1][j + 1] >= skip:
                taken[(i, j)] = value
                best[i][j] = value + best[i + 1][j + 1]
            else:
                best[i][j] = skip
    out: list[tuple[int, int]] = []
    i = j = 0
    while i < n and j < m:
        if (i, j) in taken and taken[(i, j)] + best[i + 1][j + 1] >= max(
            best[i + 1][j], best[i][j + 1]
        ):
            out.append((i, j))
            i, j = i + 1, j + 1
        elif best[i + 1][j] >= best[i][j + 1]:
            i += 1
        else:
            j += 1
    return out


#: One step of a merged sequence: ("equal" | "edit", i, j), ("delete", i, None) or
#: ("insert", None, j).
Step = tuple[str, int | None, int | None]


def steps(
    old: Sequence, new: Sequence, same: Callable[[object], object],
    score: Callable[[int, int], float],
) -> list[Step]:  # fmt: skip
    """The two sequences merged: items identical by `same`, in order, then those left
    between them paired by `score` (indices into the whole sequences), and the rest deleted
    or inserted, a deletion before an insertion."""
    a = [same(item) for item in old]
    b = [same(item) for item in new]
    out: list[Step] = []
    for tag, i1, i2, j1, j2 in SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if tag == "equal":
            out += [("equal", i1 + k, j1 + k) for k in range(i2 - i1)]
            continue
        i, j = i1, j1

        def gap(x: int, y: int, i1: int = i1, j1: int = j1) -> float:
            return score(i1 + x, j1 + y)

        for pi, pj in pairs(i2 - i1, j2 - j1, gap):
            out += [("delete", k, None) for k in range(i, i1 + pi)]
            out += [("insert", None, k) for k in range(j, j1 + pj)]
            out.append(("edit", i1 + pi, j1 + pj))
            i, j = i1 + pi + 1, j1 + pj + 1
        out += [("delete", k, None) for k in range(i, i2)]
        out += [("insert", None, k) for k in range(j, j2)]
    return out
