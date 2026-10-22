"""What identifies the data an analysis read: when they were extracted, what they cover, the
source's version where it has one, and the file itself.

"Data were extracted from VigiBase on 1 March 2024, covering reports to 31 December 2023" is
a claim like any number, and a date typed into the Methods, or into the script, was tied to
nothing: the data could be extracted again and the analysis run again, and the old date went
out with every gate green. Many databases have one version, or none a user can name, so a
version cannot be what identifies them. The extraction date can, with the file: so the date
is pinned to the file's digest where the analysis declares it (`Emitter.dataset`,
`em$dataset` in R), and a run on another file is refused.

The rules live here, once, for the Python emitter to apply as it runs; G1 holds the record
each fragment carries to the inputs it recorded, whichever emitter wrote it.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date

from manuscript_guard.dates import Dated, as_dated, parse_iso, written

#: A dataset's name, as `design/data_sources.yaml` names a source, with underscores too.
NAME = re.compile(r"[a-z0-9][a-z0-9_-]*")
#: The parts of a dataset's keys that are dates: `dataset.<name>.extracted` and the rest.
#: Its version is not one, however it is written: a release called "2024-03" is a name.
DATE_PARTS = ("extracted", "covers_from", "covers_to")
#: A pin: the first characters of a digest, at least twelve of them.
_PIN = re.compile(r"[0-9a-f]{12,64}")
#: The shortest pin a message proposes; any longer prefix is the same pin.
PROPOSED = 16
#: How many entries of the data's dates a refusal names before it counts the rest.
_NAMED = 3


def slug(name: str) -> str:
    """The name as a part of a results key: `dataset.<slug>.extracted`."""
    return name.replace("-", "_")


def dataset_digest(entries: Sequence[tuple[str, str]]) -> str:
    """The digest that identifies a dataset, from its files' paths and digests as the
    fragment records them (`sha256`, line endings left out of text).

    One file is identified by its own digest. Several are identified by the SHA-256 of one
    line for each, "<digest>  <path>\\n" as `sha256sum` prints it, in the order of their
    paths as bytes compare, so that the order they were declared in does not matter."""
    if len(entries) == 1:
        return entries[0][1]
    lines = "".join(f"{digest}  {path}\n" for path, digest in sorted(entries))
    return hashlib.sha256(lines.encode("utf-8")).hexdigest()


def pin_of(name: str, fingerprint: object, whole: str, accepted: Iterable[str], what: str,
           extracted: str) -> str:  # fmt: skip
    """The pin, checked against the file's digests, or the refusal that says what to pin."""
    proposal = f'fingerprint="{whole[:PROPOSED]}"'
    if fingerprint is None:
        raise ValueError(
            f"dataset {name!r}: pin the extraction to its data, {proposal}, the digest of "
            f"{what} as it is now. The pin is what makes a new extraction need a new date"
        )
    if not isinstance(fingerprint, str):
        raise ValueError(f"dataset {name!r}: the fingerprint is text, {proposal}")
    pin = fingerprint.strip().lower().removeprefix("sha256:")
    if not _PIN.fullmatch(pin):
        raise ValueError(
            f"dataset {name!r}: fingerprint {fingerprint!r} is not the first twelve or more "
            f"characters of a SHA-256 digest; {what} is {proposal}"
        )
    if not any(digest.startswith(pin) for digest in accepted):
        raise ValueError(
            f"dataset {name!r}: {what} is not the data pinned as extracted on {extracted} "
            f"(fingerprint {pin}); its digest begins {whole[:PROPOSED]}. If the data were "
            f"extracted again, give the date of the new extraction and pin it: "
            f'extracted="YYYY-MM-DD", {proposal}'
        )
    return pin


def stated_date(name: str, what: str, text: object, *, optional: bool = False) -> Dated | None:
    """A date the author states, as ISO 8601 text to a year, a month or a day."""
    if text is None and optional:
        return None
    if text is None:
        raise ValueError(
            f"dataset {name!r}: give the date the data were extracted or downloaded, as ISO "
            f'8601: {what}="2024-03-01", or "2024-03" or "2024" where that is all that is known'
        )
    dated = parse_iso(text) if isinstance(text, str) else None
    if dated is None:
        raise ValueError(
            f"dataset {name!r}: {what} {text!r} is not a date written as ISO 8601: "
            f'"2024-03-01", "2024-03" or "2024"'
        )
    return dated


@dataclass(frozen=True)
class Declared:
    """What one `dataset()` call states, checked: the dates and version to emit, and the
    record the fragment carries."""

    extracted: Dated
    covers_from: Dated | None
    covers_to: Dated | None
    version: str | None
    observed: dict | None

    def values(self, english: str | None) -> list[tuple[str, str, str]]:
        """Each value to emit: the last part of its key, the value and its display."""
        dates = zip(DATE_PARTS, (self.extracted, self.covers_from, self.covers_to),
                    strict=True)  # fmt: skip
        found = [(part, dated.iso, written(dated, english)) for part, dated in dates if dated]
        if self.version is not None:
            found.append(("version", self.version, self.version))
        return found

    def record(self, inputs: list[str], pin: str) -> dict:
        record: dict = {"inputs": inputs, "fingerprint": pin, "extracted": self.extracted.iso}
        covers = {end: dated.iso for end, dated in (("from", self.covers_from),
                                                    ("to", self.covers_to)) if dated}  # fmt: skip
        if covers:
            record["covers"] = covers
        if self.version is not None:
            record["version"] = self.version
        if self.observed is not None:
            record["observed"] = self.observed
        return record


def declare(
    name: str,
    *,
    extracted: object,
    covers: object,
    version: object,
    dates: object,
    today: date | None = None,
) -> Declared:
    """Check what a `dataset()` call states, apart from the files: the dates in order, none
    after the extraction, and the data's own dates within them."""
    when = stated_date(name, "extracted", extracted)
    assert when is not None
    if when.first > (today or date.today()):
        raise ValueError(f"dataset {name!r}: extracted {when.iso} is after today")
    start = end = None
    if covers is not None:
        if isinstance(covers, str) or not isinstance(covers, Sequence) or len(covers) != 2:
            raise ValueError(
                f"dataset {name!r}: covers is a pair, (from, to), each an ISO date or None "
                f'where it is not stated: covers=("1968", "2023-12-31")'
            )
        start = stated_date(name, "covers from", covers[0], optional=True)
        end = stated_date(name, "covers to", covers[1], optional=True)
        if start is None and end is None:
            raise ValueError(f"dataset {name!r}: covers states neither end; leave it out")
        if start is not None and end is not None and start.first > end.last:
            raise ValueError(
                f"dataset {name!r}: covers runs backwards, from {start.iso} to {end.iso}"
            )
    for end_of, dated in (("from", start), ("to", end)):
        if dated is not None and dated.first > when.last:
            raise ValueError(
                f"dataset {name!r}: the data cannot cover a period after they were extracted, "
                f"and covers {end_of} {dated.iso} is after {when.iso}"
            )
    return Declared(when, start, end, _version(name, version), _observed(name, dates, start,
                                                                         end, when))


def _version(name: str, version: object) -> str | None:
    if version is None:
        return None
    if not isinstance(version, str):
        # A number has no digits of its own: 5.0 is "5" in R and "5.0" here.
        raise ValueError(
            f"dataset {name!r}: give the version as text, as the source writes it "
            f'("2024 Q1", "5.0"), not {version!r}'
        )
    given = " ".join(version.split())
    if not given:
        raise ValueError(f"dataset {name!r}: the version is empty; leave it out where the "
                         f"source has none")  # fmt: skip
    return given


def _observed(
    name: str, dates: object, start: Dated | None, end: Dated | None, when: Dated
) -> dict | None:
    """The data's own dates against what the call states: the earliest, the latest and how
    many, or the refusal that names the first that lie wholly outside the period covered,
    or wholly after the extraction."""
    if dates is None:
        return None
    if isinstance(dates, (str, bytes)) or not isinstance(dates, Iterable):
        raise ValueError(f"dataset {name!r}: dates is the data's own dates, a column of them")
    count = 0
    earliest: Dated | None = None
    latest: Dated | None = None
    outside: list[tuple[int, Dated]] = []
    after: list[tuple[int, Dated]] = []
    for position, item in enumerate(dates):
        try:
            dated = as_dated(item)
        except ValueError as exc:
            raise ValueError(f"dataset {name!r}: dates[{position}]: {exc}") from None
        if dated is None:
            continue
        count += 1
        if earliest is None or dated.first < earliest.first:
            earliest = dated
        if latest is None or dated.last > latest.last:
            latest = dated
        # Wholly outside: a report dated "2023" may lie within data covered to 2023-06-30,
        # and only one that cannot is refused.
        if (start is not None and dated.last < start.first) or (
            end is not None and dated.first > end.last
        ):
            outside.append((position, dated))
        elif dated.first > when.last:
            after.append((position, dated))
    if not count:
        raise ValueError(f"dataset {name!r}: dates holds no date")
    if outside:
        period = f"{start.iso if start else '...'} to {end.iso if end else '...'}"
        raise ValueError(
            f"dataset {name!r}: {len(outside)} of {count} dates lie outside the period the data "
            f"are declared to cover ({period}): {_named(outside)}"
        )
    if after:
        raise ValueError(
            f"dataset {name!r}: {len(after)} of {count} dates are after the extraction on "
            f"{when.iso}: {_named(after)}"
        )
    assert earliest is not None and latest is not None
    return {"earliest": earliest.iso, "latest": latest.iso, "count": count}


def _named(found: list[tuple[int, Dated]]) -> str:
    named = ", ".join(f"{dated.iso} at dates[{position}]" for position, dated in found[:_NAMED])
    return named + (f" and {len(found) - _NAMED} more" if len(found) > _NAMED else "")
