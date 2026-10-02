"""The reference document a build hands pandoc.

Generated, never committed: a reference `.docx` is a binary, a project ignores `*.docx` so
that build products cannot be mistaken for sources, and a style sheet that can be
regenerated from a command is one fewer thing to keep in sync.

One style is added, and it is a reading aid rather than a house style. The journal sets the
typography of what it prints; this is the .docx an author and a co-author read, where a
caption set in the body font leaves nothing to say where the caption ends and the argument
resumes.

**It is generated from the author's own reference document when there is one.** Passing
`--reference-doc` tells pandoc to ignore `reference.docx` in its user data directory, which
is where an author who wants double spacing or a journal's font puts it, and that is the
only way this toolkit ever let them set it. So the style is added to that file when it
exists, and to pandoc's built-in default when it does not.
"""

from __future__ import annotations

import re
import subprocess
import zipfile
from pathlib import Path

#: The style `figure_caption.lua` names, and the name Word shows in its style gallery.
FIGURE_CAPTION = "Figure Caption"

#: Two points below the reference document's body text, which pandoc sets at 12 (`w:sz` is
#: in half-points). Smaller than that reads as fine print at a glance, and a caption that
#: carries the conditions of a figure has to be read.
_CAPTION_HALF_POINTS = 20

#: As it appears in `word/styles.xml`, which is how an author's own definition is recognised.
_CAPTION_ID = 'w:styleId="FigureCaption"'

_CAPTION_STYLE = (
    '<w:style w:type="paragraph" w:customStyle="1" w:styleId="FigureCaption">'
    f'<w:name w:val="{FIGURE_CAPTION}"/>'
    '<w:basedOn w:val="BodyText"/>'
    "<w:qFormat/>"
    '<w:pPr><w:spacing w:before="120" w:after="240"/></w:pPr>'
    f'<w:rPr><w:sz w:val="{_CAPTION_HALF_POINTS}"/>'
    f'<w:szCs w:val="{_CAPTION_HALF_POINTS}"/></w:rPr>'
    "</w:style>"
)


#: `pandoc --version` prints "User data directory: ..."; older pandoc printed "Default user
#: data directory: ...". Asking pandoc is the only way that is right on every platform and
#: that honours XDG_DATA_HOME, PANDOC_USER_DATA_DIR and whatever else it decides to read.
_DATA_DIR = re.compile(r"^.*user data directory:\s*(.+?)\s*$", re.IGNORECASE | re.MULTILINE)


def user_reference(pandoc: str) -> Path | None:
    """The author's own `reference.docx`, from pandoc's user data directory, if it is there.

    This is the file pandoc would have used had the build passed no `--reference-doc`; a
    build that passes one has to start from it or it silently drops the author's typography.
    """
    try:
        printed = subprocess.run(
            [pandoc, "--version"], capture_output=True, check=True, text=True
        ).stdout
    except (OSError, subprocess.CalledProcessError):
        return None
    found = _DATA_DIR.search(printed or "")
    if found is None:
        return None
    candidate = Path(found.group(1)) / "reference.docx"
    return candidate if candidate.is_file() else None


def reference_with(pandoc: str, target: Path, extra: str = "") -> Path:
    """The author's reference document, or pandoc's own, plus the caption style and `extra`.

    `extra` is further `w:style` elements, as the annotated build's highlights are.
    """
    from manuscript_guard.build.document import BuildError

    target.parent.mkdir(parents=True, exist_ok=True)
    scratch = target.with_suffix(".default.docx")
    theirs = user_reference(pandoc)
    if theirs is not None:
        scratch.write_bytes(theirs.read_bytes())
    else:
        scratch.write_bytes(
            subprocess.run(
                [pandoc, "--print-default-data-file", "reference.docx"],
                capture_output=True,
                check=True,
            ).stdout
        )
    try:
        with (
            zipfile.ZipFile(scratch) as zin,
            zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as zout,
        ):
            for item in zin.infolist():
                data = zin.read(item.filename)
                if item.filename == "word/styles.xml":
                    xml = data.decode("utf-8")
                    if "</w:styles>" not in xml:
                        raise BuildError("the reference document has no styles to add to")
                    # An author who has defined Figure Caption in their own reference
                    # document has said what a caption should look like; two definitions of
                    # one style id is not a document, and theirs is the one to keep.
                    caption = "" if _CAPTION_ID in xml else _CAPTION_STYLE
                    data = (xml.replace("</w:styles>", caption + extra + "</w:styles>")).encode(
                        "utf-8"
                    )
                zout.writestr(item, data)
    finally:
        scratch.unlink(missing_ok=True)
    return target
