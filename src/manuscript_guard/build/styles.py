"""The reference document a build hands pandoc.

Generated from pandoc's own, never committed: a reference `.docx` is a binary, a project
ignores `*.docx` so that build products cannot be mistaken for sources, and a style sheet
that can be regenerated from a command is one fewer thing to keep in sync.

One style lives here, and it is a reading aid rather than a house style. The journal sets
the typography of what it prints; this is the .docx an author and a co-author read, where a
caption set in the body font leaves nothing to say where the caption ends and the argument
resumes.
"""

from __future__ import annotations

import subprocess
import zipfile
from pathlib import Path

#: The style `figure_caption.lua` names, and the name Word shows in its style gallery.
FIGURE_CAPTION = "Figure Caption"

#: Two points below the reference document's body text, which pandoc sets at 12 (`w:sz` is
#: in half-points). Smaller than that reads as fine print at a glance, and a caption that
#: carries the conditions of a figure has to be read.
_CAPTION_HALF_POINTS = 20

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


def reference_with(pandoc: str, target: Path, extra: str = "") -> Path:
    """Pandoc's default reference document, plus the figure-caption style and `extra`.

    `extra` is further `w:style` elements, as the annotated build's highlights are.
    """
    from manuscript_guard.build.document import BuildError

    target.parent.mkdir(parents=True, exist_ok=True)
    default = subprocess.run(
        [pandoc, "--print-default-data-file", "reference.docx"],
        capture_output=True,
        check=True,
    ).stdout
    scratch = target.with_suffix(".default.docx")
    scratch.write_bytes(default)
    added = _CAPTION_STYLE + extra
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
                        raise BuildError("pandoc's reference document has no styles to add to")
                    data = xml.replace("</w:styles>", added + "</w:styles>").encode("utf-8")
                zout.writestr(item, data)
    finally:
        scratch.unlink(missing_ok=True)
    return target
