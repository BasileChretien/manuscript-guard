"""Lining up what was sent with what the proof prints, token by token, in time near to their
length.

difflib's matcher is exact and quadratic: a paper of eleven thousand tokens took eleven
seconds, three times that took ninety. So the two are lined up the way a patience diff
does it: the runs of keys that stand exactly once on each side are anchors, the longest
chain of them in the same order on both sides is kept, and only the gaps between anchors,
once they are small, are handed to difflib. Runs of eight keys are tried first, then four,
two and one, so that a common word does not anchor a gap it does not belong to.

Text the proof sets elsewhere is off the chain: a table or a figure set where the page had
room, a statement the journal's template moves. `moves` finds each run the alignment left
unmatched among the runs of the proof it left unmatched.
"""

from __future__ import annotations

import difflib
from bisect import bisect_left
from dataclasses import dataclass

#: Up to this many pairs, a gap is lined up by difflib.
SMALL = 40_000
#: Up to this many, a gap with no anchor in it is still lined up by difflib: a table of
#: numbers alone has none.
LARGE = 1_000_000
GRAMS = (8, 4, 2, 1)
#: The most times a run may stand on each side and still anchor, where none stands once.
REPEATS = 8
#: The fewest tokens of a run of what was sent that is looked for elsewhere in the proof.
MOVE_LEAST = 6
#: How much of such a run has to be found together elsewhere for it to have moved there.
MOVE_SHARE = 0.6

Block = tuple[int, int, int]


@dataclass(frozen=True)
class Op:
    """A stretch of the alignment, as difflib names them: "equal", "replace", "delete"
    (sent, not printed) or "insert" (printed, not sent). `moved` where it is a stretch of a
    run the proof set elsewhere."""

    tag: str
    i1: int
    i2: int
    j1: int
    j2: int
    moved: bool = False


def matching_blocks(a: list[str], b: list[str]) -> list[Block]:
    """The runs of `a` and `b` that are the same, as (i, j, n), in order of both."""
    found: list[Block] = []
    stack = [(0, len(a), 0, len(b))]
    while stack:
        alo, ahi, blo, bhi = stack.pop()
        while alo < ahi and blo < bhi and a[alo] == b[blo]:
            found.append((alo, blo, 1))
            alo, blo = alo + 1, blo + 1
        while alo < ahi and blo < bhi and a[ahi - 1] == b[bhi - 1]:
            ahi, bhi = ahi - 1, bhi - 1
            found.append((ahi, bhi, 1))
        if alo >= ahi or blo >= bhi:
            continue
        size = (ahi - alo) * (bhi - blo)
        chain = [] if size <= SMALL else _anchors(a, b, alo, ahi, blo, bhi)
        if not chain:
            if size <= LARGE:
                matcher = difflib.SequenceMatcher(None, a[alo:ahi], b[blo:bhi], autojunk=False)
                found += [(alo + i, blo + j, n) for i, j, n in matcher.get_matching_blocks() if n]
            continue
        i0, j0 = alo, blo
        for i, j, n in chain:
            stack.append((i0, i, j0, j))
            found.append((i, j, n))
            i0, j0 = i + n, j + n
        stack.append((i0, ahi, j0, bhi))
    return _merged(sorted(found))


def _anchors(a: list[str], b: list[str], alo: int, ahi: int, blo: int, bhi: int) -> list[Block]:
    """The longest chain, in the order of both, of runs that stand once in each range; or,
    where no run does, of runs that stand as often in each, up to `REPEATS` times, the first
    with the first: a table of numbers alone, or a passage the paper repeats."""
    for most in (1, REPEATS):
        for size in GRAMS:
            blocks = _chained(a, b, alo, ahi, blo, bhi, size, most)
            if blocks:
                return blocks
    return []


def _chained(a: list[str], b: list[str], alo: int, ahi: int, blo: int, bhi: int, size: int,
             most: int) -> list[Block]:  # fmt: skip
    if ahi - alo < size or bhi - blo < size:
        return []
    left: dict[tuple[str, ...], list[int]] = {}
    right: dict[tuple[str, ...], list[int]] = {}
    for i in range(alo, ahi - size + 1):
        left.setdefault(tuple(a[i : i + size]), []).append(i)
    for j in range(blo, bhi - size + 1):
        right.setdefault(tuple(b[j : j + size]), []).append(j)
    pairs = sorted(
        pair
        for gram, found in left.items()
        if len(found) <= most and len(right.get(gram, ())) == len(found)
        for pair in zip(found, right[gram], strict=True)
    )
    blocks: list[Block] = []
    for i, j in _longest_chain(pairs):
        if blocks:
            pi, pj, pn = blocks[-1]
            if i - pi == j - pj and i <= pi + pn:
                blocks[-1] = (pi, pj, i + size - pi)
                continue
            if i < pi + pn or j < pj + pn:
                continue
        blocks.append((i, j, size))
    return blocks


def _longest_chain(pairs: list[tuple[int, int]]) -> list[tuple[int, int]]:
    """The longest run of `pairs`, which are in order of their first, in order of their
    second too: patience sorting."""
    tails: list[int] = []
    ends: list[int] = []
    before: list[int] = [-1] * len(pairs)
    for index, (_i, j) in enumerate(pairs):
        at = bisect_left(tails, j)
        if at == len(tails):
            tails.append(j)
            ends.append(index)
        else:
            tails[at] = j
            ends[at] = index
        before[index] = ends[at - 1] if at else -1
    chain = []
    index = ends[-1] if ends else -1
    while index >= 0:
        chain.append(pairs[index])
        index = before[index]
    return chain[::-1]


def _merged(blocks: list[Block]) -> list[Block]:
    out: list[Block] = []
    for i, j, n in blocks:
        if out and out[-1][0] + out[-1][2] == i and out[-1][1] + out[-1][2] == j:
            out[-1] = (out[-1][0], out[-1][1], out[-1][2] + n)
        else:
            out.append((i, j, n))
    return out


def opcodes(a: list[str], b: list[str], *, i0: int = 0, j0: int = 0, moved: bool = False
            ) -> list[Op]:  # fmt: skip
    """The alignment of `a` and `b` as difflib's opcodes, offset by `i0` and `j0`."""
    out: list[Op] = []
    i = j = 0
    for bi, bj, n in [*matching_blocks(a, b), (len(a), len(b), 0)]:
        if i < bi and j < bj:
            out.append(Op("replace", i0 + i, i0 + bi, j0 + j, j0 + bj, moved))
        elif i < bi:
            out.append(Op("delete", i0 + i, i0 + bi, j0 + j, j0 + j, moved))
        elif j < bj:
            out.append(Op("insert", i0 + i, i0 + i, j0 + j, j0 + bj, moved))
        if n:
            out.append(Op("equal", i0 + bi, i0 + bi + n, j0 + bj, j0 + bj + n, moved))
        i, j = bi + n, bj + n
    return out


def slid(ops: list[Op], a: list[str], b: list[str], starts: frozenset[int]) -> list[Op]:
    """The alignment with each stretch sent and not printed, or printed and not sent, moved
    along the tokens alike on both sides of it until it starts where a part starts, where it
    can: "unknown . Funding … agency ." less "Funding … agency ." is the same as less
    ". Funding … agency", and only the first leaves the paragraph before it whole."""
    out = list(ops)
    for k in range(1, len(out) - 1):
        op, before, after = out[k], out[k - 1], out[k + 1]
        if op.tag not in ("delete", "insert") or before.tag != "equal" or after.tag != "equal":
            continue
        if op.i1 in starts or op.moved or before.moved or after.moved:
            continue
        side, lo, hi = (a, op.i1, op.i2) if op.tag == "delete" else (b, op.j1, op.j2)
        shift = _shift(side, lo, hi, op.i1, before.i2 - before.i1, after.i2 - after.i1, starts)
        if shift:
            out[k - 1] = Op("equal", before.i1, before.i2 + shift, before.j1, before.j2 + shift)
            out[k] = Op(op.tag, op.i1 + shift, op.i2 + shift, op.j1 + shift, op.j2 + shift)
            out[k + 1] = Op("equal", after.i1 + shift, after.i2, after.j1 + shift, after.j2)
    return [op for op in out if op.tag != "equal" or op.i2 > op.i1]


def _shift(side: list[str], lo: int, hi: int, at: int, room_before: int, room_after: int,
           starts: frozenset[int]) -> int:  # fmt: skip
    """How far a stretch [lo, hi) of `side` can move, keeping the alignment, to start at a
    part's start: forward first, then back; 0 where it cannot."""
    for step in range(1, room_after + 1):
        if hi + step - 1 >= len(side) or side[lo + step - 1] != side[hi + step - 1]:
            break
        if at + step in starts:
            return step
    for step in range(1, room_before + 1):
        if lo - step < 0 or side[lo - step] != side[hi - step]:
            break
        if at - step in starts:
            return -step
    return 0


def whole_parts(ops: list[Op], a: list[str], b: list[str], starts: frozenset[int]) -> list[Op]:
    """The alignment with a part the proof leaves out left out whole, where that lines up
    as many tokens as the alignment did. Next to a part the proof changed, "remained … . |
    Juliet … ." printed "stayed … .", the words the two parts end with were lined up with the
    second's end, and the part left out read as part of a copy-edit of the first."""
    edges = sorted(starts | {len(a)})
    bounds = list(zip(edges, edges[1:], strict=False))
    out = list(ops)
    k = 0
    while k < len(out):
        op = out[k]
        if op.tag == "replace" and not op.moved:
            after = out[k + 1] if k + 1 < len(out) else None
            before = out[k - 1] if k else None
            done = _left_out_after(out, k, op, after, a, b, bounds) or _left_out_before(
                out, k, op, before, a, b, bounds)  # fmt: skip
            if done:
                continue
        k += 1
    return out


def _left_out_after(out, k, op, after, a, b, bounds) -> bool:
    """A part that starts inside a stretch changed and ends inside the stretch alike after
    it, left out whole if that lines up as many: what it shares with the end of the part
    before it is then that part's."""
    if after is None or after.tag != "equal" or after.moved:
        return False
    for first, end in bounds:
        if not (op.i1 < first < op.i2 < end <= after.i2):
            continue
        alike = end - op.i2
        kept = matching_blocks(a[op.i1 : first], b[op.j1 : after.j1 + alike])
        if sum(n for _i, _j, n in kept) < alike:
            continue
        j = after.j1 + alike
        new = opcodes(a[op.i1 : first], b[op.j1 : j], i0=op.i1, j0=op.j1)
        new.append(Op("delete", first, end, j, j))
        if after.i2 > end:
            new.append(Op("equal", end, after.i2, j, after.j2))
        out[k : k + 2] = new
        return True
    return False


def _left_out_before(out, k, op, before, a, b, bounds) -> bool:
    """The same, a part that starts inside the stretch alike before a stretch changed and
    ends inside it."""
    if before is None or before.tag != "equal" or before.moved:
        return False
    for first, end in bounds:
        if not (before.i1 <= first < op.i1 < end < op.i2):
            continue
        alike = op.i1 - first
        j = before.j1 + (first - before.i1)
        kept = matching_blocks(a[end : op.i2], b[j : op.j2])
        if sum(n for _i, _j, n in kept) < alike:
            continue
        new = [Op("equal", before.i1, first, before.j1, j)] if first > before.i1 else []
        new.append(Op("delete", first, end, j, j))
        new += opcodes(a[end : op.i2], b[j : op.j2], i0=end, j0=j)
        out[k - 1 : k + 1] = new
        return True
    return False


def align(a: list[str], b: list[str], starts: frozenset[int] = frozenset()) -> list[Op]:
    """`a` lined up with `b`, with the runs of `a` that `b` sets elsewhere lined up there and
    marked `moved`; in the order of `a`. `starts` are where the parts of `a` start, which a
    stretch is slid to where it can be (`slid`), and a part left out is left out whole where
    it can be (`whole_parts`)."""
    ops = slid(opcodes(a, b), a, b, starts)
    if starts:
        ops = whole_parts(ops, a, b, starts)
    gone = sorted(
        (op for op in ops if op.tag in ("delete", "replace") and op.i2 - op.i1 >= MOVE_LEAST),
        key=lambda op: op.i1 - op.i2,
    )
    free = [(op.j1, op.j2) for op in ops if op.tag in ("insert", "replace") and op.j2 > op.j1]
    found: dict[tuple[int, int], tuple[int, int]] = {}
    for op in gone:
        best: tuple[int, int, int, int] | None = None
        for at, (j1, j2) in enumerate(free):
            blocks = matching_blocks(a[op.i1 : op.i2], b[j1:j2])
            matched = sum(n for _i, _j, n in blocks)
            if matched >= MOVE_SHARE * (op.i2 - op.i1) and (best is None or matched > best[0]):
                lo = j1 + min(j for _i, j, _n in blocks)
                hi = j1 + max(j + n for _i, j, n in blocks)
                best = (matched, at, lo, hi)
        if best is None:
            continue
        _matched, at, lo, hi = best
        # Not the place it stood: a run lined up with a part of its own stretch is no move.
        if op.tag == "replace" and op.j1 <= lo and hi <= op.j2:
            continue
        j1, j2 = free.pop(at)
        free += [span for span in ((j1, lo), (hi, j2)) if span[1] > span[0]]
        found[(op.i1, op.i2)] = (lo, hi)
    if not found:
        return ops
    taken = sorted(found.values())
    out: list[Op] = []
    for op in ops:
        if op.tag == "equal":
            out.append(op)
            continue
        moved_away = (op.i1, op.i2) in found
        if not moved_away and op.i2 > op.i1 and not _overlaps(op.j1, op.j2, taken):
            out.append(op)
            continue
        if not moved_away and op.i2 > op.i1:
            out.append(Op("delete", op.i1, op.i2, op.j1, op.j1))
        for lo, hi in _left(op.j1, op.j2, taken):
            out.append(Op("insert", op.i1, op.i1, lo, hi))
    for (i1, i2), (lo, hi) in found.items():
        out += opcodes(a[i1:i2], b[lo:hi], i0=i1, j0=lo, moved=True)
    return sorted(out, key=lambda op: (op.i1, op.i2, op.j1))


def _overlaps(j1: int, j2: int, taken: list[tuple[int, int]]) -> bool:
    return any(lo < j2 and j1 < hi for lo, hi in taken)


def _left(j1: int, j2: int, taken: list[tuple[int, int]]) -> list[tuple[int, int]]:
    """What of [j1, j2) no span of `taken` covers."""
    out, at = [], j1
    for lo, hi in taken:
        if hi <= at or lo >= j2:
            continue
        if lo > at:
            out.append((at, lo))
        at = max(at, hi)
    if at < j2:
        out.append((at, j2))
    return out
