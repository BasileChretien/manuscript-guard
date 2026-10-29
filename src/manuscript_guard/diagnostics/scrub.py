"""Take what names the machine, the person and the project out of a text.

A convenience, not a guarantee. It replaces exact strings and a few patterns: the project's
folder, the home folder, the temporary folder and Python's own, each in the spellings Windows,
POSIX and Git Bash give it; e-mail addresses; a user and password in a link; the value of
every environment variable that holds a credential; and the names and ORCIDs `authors.yaml`
lists. A path written another way, a name the file does not list, or a line of the manuscript
quoted in a message stays as it was. Whoever sends a report reads all of it first.
"""

from __future__ import annotations

import contextlib
import os
import re
import sys
import sysconfig
import tempfile
from collections.abc import Iterable, Mapping
from pathlib import Path

#: The variables the toolkit reads a credential from (`review --providers`, `lookup`,
#: `deposit`, `communicate`). Any other whose name ends as `SECRET_ENDINGS` does is taken too.
SECRET_VARIABLES = frozenset({
    "ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GEMINI_API_KEY", "MISTRAL_API_KEY",
    "DEEPSEEK_API_KEY", "MOONSHOT_API_KEY", "OPENROUTER_API_KEY", "NCBI_API_KEY", "NCBI_KEY",
    "OPENALEX_API_KEY", "OPENALEX_KEY", "ZENODO_TOKEN", "ZENODO_SANDBOX_TOKEN", "OSF_TOKEN",
    "BLUESKY_APP_PASSWORD", "MASTODON_TOKEN",
})  # fmt: skip
SECRET_ENDINGS = ("KEY", "TOKEN", "SECRET", "PASSWORD", "PASSWD")
#: A shorter value is left: "1", "true" or "yes" would be replaced wherever they stand.
SHORTEST_SECRET = 6

_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_USER_IN_LINK = re.compile(r"(?P<scheme>\b[A-Za-z][A-Za-z0-9+.-]*://)[^/\s@]+@")
#: A folder's name continues with a letter, a digit or an underscore: `C:\Users\Ada` is not
#: replaced inside `C:\Users\Adam`.
_GOES_ON = r"(?![A-Za-z0-9_])"
_DRIVE = re.compile(r"^[A-Za-z]:/")


def scrub(text: str, *, root: Path | None = None, environ: Mapping[str, str] | None = None) -> str:
    """`text` with the paths, addresses, secrets and authors above replaced by labels."""
    environ = os.environ if environ is None else environ
    for value, label in _secrets(environ):
        text = text.replace(value, label)
    for pattern, label in _paths(root, environ):
        text = pattern.sub(label, text)
    text = _USER_IN_LINK.sub(r"\g<scheme>", text)
    # Addresses before names: a name replaced inside an address would leave the rest of it.
    text = _EMAIL.sub("<EMAIL>", text)
    for pattern, label in _authors(root):
        text = pattern.sub(label, text)
    return text


def _secrets(environ: Mapping[str, str]) -> list[tuple[str, str]]:
    """Each credential's value with its label, longest first, so that no value is cut by a
    shorter one inside it."""
    found = [
        (value, f"<SECRET:{name}>")
        for name, value in environ.items()
        if _is_secret(name) and len(value) >= SHORTEST_SECRET
    ]
    return sorted(found, key=lambda pair: -len(pair[0]))


def _is_secret(name: str) -> bool:
    upper = name.upper()
    return upper in SECRET_VARIABLES or upper.endswith(SECRET_ENDINGS)


def _paths(root: Path | None, environ: Mapping[str, str]) -> list[tuple[re.Pattern[str], str]]:
    """A pattern for each spelling of each folder, longest first: the project inside the home
    folder is `<PROJECT>`, not `<HOME>/...`."""
    folders = [(root, "<PROJECT>"), (Path(tempfile.gettempdir()), "<TEMP>")]
    folders += [(Path(p), "<PYTHON>") for p in _python_folders()]
    home = environ.get("USERPROFILE") or environ.get("HOME")
    folders.append((Path(home) if home else Path.home(), "<HOME>"))
    spelt: dict[str, str] = {}
    for folder, label in folders:
        if folder is None:
            continue
        for spelling in _spellings(folder):
            spelt.setdefault(spelling, label)
    flags = re.IGNORECASE if os.name == "nt" else 0
    ordered = sorted(spelt.items(), key=lambda pair: -len(pair[0]))
    return [(re.compile(re.escape(s) + _GOES_ON, flags), label) for s, label in ordered]


def _python_folders() -> Iterable[str]:
    seen = {sys.prefix, sys.base_prefix, sys.exec_prefix}
    for key in ("purelib", "platlib", "stdlib"):
        try:
            seen.add(sysconfig.get_path(key))
        except KeyError:
            continue
    return (path for path in seen if path)


def _spellings(folder: Path) -> set[str]:
    """`folder` as a message may write it: as resolved and as given, with either slash,
    in Windows' long form, and as Git Bash writes a drive (`/c/Users/...`)."""
    given = {str(folder)}
    with contextlib.suppress(OSError):
        given.add(str(folder.resolve()))
    found: set[str] = set()
    for path in given:
        forward = path.replace("\\", "/").rstrip("/")
        back = forward.replace("/", "\\")
        # Doubled as repr() shows a Windows path in an error's message: 'C:\\Users\\...'.
        found.update({forward, back, back.replace("\\", "\\\\")})
        if _DRIVE.match(forward + "/"):
            found.add("\\\\?\\" + back)
            found.add(f"/{forward[0].lower()}{forward[2:]}")
    # A drive or the root alone would be replaced everywhere it appears.
    return {spelling for spelling in found if len(spelling) > 3}


#: A name is a whole word as `authors.yaml` writes it ("Lovelace", not "Lovelaces" nor the
#: "line" of an error when the family is Line), with either apostrophe.
_NOT_A_LETTER_BEFORE = r"(?<![^\W\d_])"
_NOT_A_LETTER_AFTER = r"(?![^\W\d_])"
#: And a family name in a citation key: in any case, its accents, apostrophes, hyphens and
#: spaces dropped (Chrétien as "chretien2020", van der Berg as "vanderberg_2020"), run into
#: the digits or the underscore that make it a key.
_RUNS_INTO_A_KEY = r"(?=[\d_])"
_APOSTROPHES = ("'", "\N{RIGHT SINGLE QUOTATION MARK}")


def _authors(root: Path | None) -> list[tuple[re.Pattern[str], str]]:
    """A pattern for each author's names and ORCID, longest first, where `authors.yaml` reads;
    nothing where it does not."""
    if root is None:
        return []
    try:
        import yaml

        listed = yaml.safe_load((root / "authors.yaml").read_text(encoding="utf-8"))
        people = listed.get("authors") or []
    except Exception:  # noqa: BLE001 - a file that does not read names nobody to take out
        return []
    found: list[tuple[int, re.Pattern[str], str]] = []
    for number, person in enumerate(people, start=1):
        if not isinstance(person, dict):
            continue
        label = f"<AUTHOR-{number}>"
        for text in _named(person):
            found.append((len(text), _as_written(text), label))
        keyed = _folded(str(person.get("family") or ""))
        if len(keyed) >= 2:
            found.append((len(keyed), re.compile(
                _NOT_A_LETTER_BEFORE + re.escape(keyed) + _RUNS_INTO_A_KEY, re.IGNORECASE),
                label))  # fmt: skip
    return [(pattern, label) for _length, pattern, label in sorted(found, key=lambda f: -f[0])]


def _as_written(text: str) -> re.Pattern[str]:
    spellings = {text}
    for one, other in (_APOSTROPHES, _APOSTROPHES[::-1]):
        spellings.add(text.replace(one, other))
    either = "|".join(re.escape(s) for s in sorted(spellings, key=len, reverse=True))
    return re.compile(_NOT_A_LETTER_BEFORE + f"(?:{either})" + _NOT_A_LETTER_AFTER)


def _folded(name: str) -> str:
    """`name` as a citation key writes it: its letters only, unaccented, in lower case."""
    import unicodedata

    plain = unicodedata.normalize("NFKD", name)
    return "".join(c for c in plain if c.isalpha() and not unicodedata.combining(c)).lower()


def _named(person: dict) -> list[str]:
    given = str(person.get("given") or "").strip()
    family = str(person.get("family") or "").strip()
    whole = str(person.get("name") or f"{given} {family}").strip()
    texts = [whole, family, str(person.get("orcid") or "").strip()]
    return [text for text in texts if len(text) >= 2]
