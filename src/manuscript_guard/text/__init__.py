"""Reading manuscript source: what to ignore, what counts as a number, how bindings work."""

from manuscript_guard.text.masking import line_at, line_col, mask, masked_spans
from manuscript_guard.text.placeholders import Placeholder, parse, substitute
from manuscript_guard.text.tokens import Atom, find_atoms

__all__ = [
    "Atom",
    "Placeholder",
    "find_atoms",
    "line_at",
    "line_col",
    "mask",
    "masked_spans",
    "parse",
    "substitute",
]
