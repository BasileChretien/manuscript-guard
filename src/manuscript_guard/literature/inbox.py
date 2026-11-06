"""`sync-sources --inbox <folder>`: the PDFs the user saved, from their own browser, filed under
the cited work each shows it is.

The works no open copy and no publisher's link gave this computer are listed with their DOI
links (`fetching.asked`). The user opens them in their browser, signed in through their
library, or an agent drives that browser for them, and saves each PDF where the browser puts
downloads. Those files are named as the publisher named them ("1-s2.0-S0166432820301234-
main.pdf", "jnp.12345.pdf"), not by DOI, so `--from`, which reads a name, cannot file them.
This reads what each shows instead (`literature/matching.py`): its DOI or its title on its
first two pages, or its DOI in its metadata.

Only the PDFs directly in the folder are read, not those in folders under it: a Downloads
folder holds years of other files, and its subfolders are someone else's. A PDF that shows two
cited works, a review that names another cited paper on its first page, is filed for neither,
and two that show one work and differ are both left, as with Zotero and `--from`. A PDF that
shows no cited work is counted, so that a wrong folder shows; what it is is not said.
"""

from __future__ import annotations

from pathlib import Path

from manuscript_guard.contracts.project import Project
from manuscript_guard.literature import matching
from manuscript_guard.literature.copies import FROM_INBOX, Candidate, digest, wanted_keys
from manuscript_guard.literature.downloads import FolderUnreadable, Offer
from manuscript_guard.literature.fetching import Work, works_of
from manuscript_guard.literature.sources import filed_name
from manuscript_guard.lookup.download import MAX_BYTES


def _pdfs(folder: Path) -> list[Path]:
    try:
        if not folder.is_dir():
            raise FolderUnreadable(f"{folder} is not a folder")
        return sorted(entry for entry in folder.iterdir()
                      if entry.suffix.lower() == ".pdf" and entry.is_file())  # fmt: skip
    except OSError as exc:
        raise FolderUnreadable(f"{folder} could not be read ({exc.strerror or exc})") from exc


def _shown(path: Path, works: dict[str, Work]) -> tuple[dict[str, str], str | None]:
    """The works a PDF shows it is, each with how; or why it was not read."""
    try:
        if path.stat().st_size > MAX_BYTES:
            return {}, f"the folder's {path.name} is over {MAX_BYTES >> 20} MB, and was not read"
        raw = path.read_bytes()
    except OSError as exc:
        return {}, f"the folder's {path.name} could not be read ({exc.strerror or exc})"
    if not raw.startswith(matching.PDF_HEADER):
        return {}, (f"the folder's {path.name} does not begin with %PDF-, so it is not a PDF "
                    "(a sign-in or paywall page saved under that name, most likely)")
    text = matching.first_pages(path)
    found = {}
    for key, work in works.items():
        shown = matching.judged(raw, text, work.doi, work.title)
        if shown.by is not None:
            found[key] = shown.by
    return found, None


def _same_work(works: dict[str, Work], keys: list[str]) -> bool:
    """Whether the keys are one work cited under several: one DOI, or one key."""
    dois = {works[key].doi for key in keys}
    return len(keys) == 1 or (len(dois) == 1 and None not in dois)


def offer(project: Project, folder: Path) -> Offer:
    """What the folder holds for each work the manuscript cites or the methods review names."""
    pdfs = _pdfs(folder)
    works = works_of(project, wanted_keys(project))
    held: dict[str, dict[str, tuple[Path, str, int, str]]] = {}
    why: dict[str, list[str]] = {}
    unread: list[str] = []
    unmatched = 0
    for path in pdfs:
        shown, problem = _shown(path, works)
        if problem:
            unread.append(problem)
            continue
        keys = sorted(shown)
        if not keys:
            unmatched += 1
            continue
        if not _same_work(works, keys):
            for key in keys:
                why.setdefault(key, []).append(
                    f"the folder's {path.name} shows several cited works ({', '.join(keys)}), "
                    "and which it is is not guessed")  # fmt: skip
            continue
        try:
            sha, size = digest(path)
        except OSError as exc:
            unread.append(f"the folder's {path.name} could not be read ({exc.strerror or exc})")
            continue
        for key in keys:
            held.setdefault(key, {}).setdefault(sha, (path, sha, size, shown[key]))
    chosen: dict[str, list[Candidate]] = {}
    for key, versions in held.items():
        if len(versions) > 1:
            names = ", ".join(sorted(path.name for path, *_ in versions.values()))
            why.setdefault(key, []).append(
                f"{len(versions)} PDFs of the folder show it ({names}) and differ, and which is "
                "the work's is not guessed")  # fmt: skip
            continue
        path, sha, size, by = next(iter(versions.values()))
        chosen[key] = [Candidate(filed_name(key, ".pdf"), path, FROM_INBOX, None, sha, size,
                                 about=f"from the inbox's {path.name}, matched by its {by}",
                                 doi=works[key].doi, matched=by)]  # fmt: skip
    for key in wanted_keys(project):
        if key not in chosen and key not in why:
            why[key] = ["no PDF in the folder shows its DOI or its title"
                        if key in works else "not in references.bib, so there is nothing to "
                        "know its PDF by"]  # fmt: skip
    return Offer(chosen, why, len(pdfs), unmatched, tuple(unread), inbox=True)


__all__ = ["offer"]
