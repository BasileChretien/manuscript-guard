"""The one value type every source of numbers resolves to.

Results, the literature ledger and author attestations all produce `Value` objects in a
single namespace-qualified space, so the substitution engine and the classifier never need
to know where a number came from — only the reporting does.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

RESULTS = "results"
LITERATURE = "literature"
ATTESTED = "attested"


class DisplayError(Exception):
    """A value cannot be rendered without the author deciding how."""


@dataclass(frozen=True)
class Value:
    key: str
    value: object
    display: str
    origin: str
    source: Path | None = None
    unit: str | None = None
    quoted: bool = True
    detail: dict | None = None

    @property
    def namespace(self) -> str:
        return "results" if self.origin == RESULTS else "lit"

    @property
    def reference(self) -> str:
        """How this value is written in manuscript source."""
        return f"{{{{{self.namespace}.{self.key}}}}}"


def derive_display(key: str, value: object, display: str | None, digits: int | None) -> str:
    """Work out the prose form of a value, or refuse.

    A float with neither an explicit display string nor a digit count is rejected rather
    than formatted with some default. Implicit rounding is exactly how the same quantity
    comes to be written 4.3 in the abstract and 4.28 in a table, and no downstream check
    can recover the author's intent once it is lost.
    """
    if display is not None:
        return display
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if digits is None:
            raise DisplayError(
                f"{key}: a float needs `display` or `digits` so that every place it is "
                f"quoted rounds it identically"
            )
        return f"{value:.{digits}f}"
    if isinstance(value, str):
        return value
    raise DisplayError(f"{key}: values of type {type(value).__name__} need an explicit `display`")
