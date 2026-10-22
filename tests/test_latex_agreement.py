"""What the LaTeX reader keeps against what LaTeX prints (DESIGN.md, "LaTeX itself", step 9).

`tests/test_pandoc_agreement.py` asks pandoc, the program that builds a Markdown paper, whether
the toolkit reads its structure as pandoc does. This asks LuaLaTeX the same of the LaTeX
reader's mask: a fixed number of generated files the reader does not refuse are compiled, a
callback writes out each digit LaTeX sets on each page, and the digits must be the ones the
mask keeps, in the same order. A digit the mask keeps and LaTeX does not print is a number G2
would ask to be bound that no reader sees; one LaTeX prints and the mask drops is a typed
number G2 never reads.

What the comparison leaves out, and why:
- LaTeX's own numbers, a page's, a section's, a footnote's mark, are turned off;
- a citation command prints `?` for a key the run has no bibliography for, and a stand-in for
  natbib's prints its note, as natbib does;
- `\\mg` prints nothing, which is what the mask keeps of a binding;
- the content of a `verbatim` environment and of `\\url`, which the mask blanks on purpose: a
  listing's and a link's digits are no numbers of the paper;
- a file LaTeX stops on, with a bare `^` or `_` from the filler the Markdown suites share; the
  reader does not refuse those (Known gaps), and at least half the files must compile.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from hypothesis import HealthCheck, given, settings

from manuscript_guard.text.latex.mask import NUL, read

sys.path.insert(0, str(Path(__file__).parent))
from generated import latex_texts  # noqa: E402

LUALATEX = shutil.which("lualatex")
pytestmark = pytest.mark.skipif(LUALATEX is None, reason="lualatex is not installed")

#: How many generated files are compiled: each takes seconds.
FILES = 24

_PREAMBLE = r"""\documentclass{article}
\providecommand{\citep}[2][]{(#1)}
\providecommand{\citet}[2][]{(#1)}
\providecommand{\unknown}[1]{#1}
\providecommand{\mg}[2][]{}
\pagestyle{empty}
\setcounter{secnumdepth}{-2}
\renewcommand{\thefootnote}{}
\directlua{
local out = io.open("digits.txt", "w")
local glyph, hlist, vlist = node.id("glyph"), node.id("hlist"), node.id("vlist")
local disc = node.id("disc")
local function walk(head)
  for item in node.traverse(head) do
    if item.id == glyph then
      if item.char >= 48 and item.char <= 57 then out:write(string.char(item.char)) end
    elseif item.id == hlist or item.id == vlist then
      walk(item.head)
    elseif item.id == disc then
      walk(item.replace)
    end
  end
end
luatexbase.add_to_callback("pre_shipout_filter", function(box)
  walk(box.head) out:write("\string\n") out:flush() return true end, "digits")
}
"""
#: What the mask blanks on purpose, taken out before LaTeX is asked.
_UNREAD = re.compile(r"\\begin\{verbatim\}.*?\\end\{verbatim\}|\\url\{[^{}]*\}", re.S)


def _files() -> list[str]:
    """The first `FILES` generated bodies the reader does not refuse, the same each run."""
    drawn: list[str] = []

    @settings(max_examples=FILES * 6, derandomize=True, database=None, deadline=None,
              suppress_health_check=list(HealthCheck))  # fmt: skip
    @given(latex_texts())
    def collect(text: str) -> None:
        text = _UNREAD.sub("", text)
        whole = "\\begin{document}" in text or "\\end{document}" in text
        if len(drawn) < FILES and not whole and not read(text).refusals:
            drawn.append(text)

    collect()
    return drawn


def _printed(folder: Path, text: str) -> str | None:
    """The digits LuaLaTeX sets for `text`, or None where it stops."""
    (folder / "doc.tex").write_text(_PREAMBLE + "\\begin{document}\n" + text
                                    + "\n\\end{document}\n", encoding="utf-8")  # fmt: skip
    done = subprocess.run([LUALATEX, "-interaction=nonstopmode", "-halt-on-error", "doc.tex"],
                          cwd=folder, capture_output=True, text=True, errors="replace",
                          timeout=300, check=False)  # fmt: skip
    if done.returncode != 0:
        return None
    return "".join(re.findall(r"\d", (folder / "digits.txt").read_text(encoding="utf-8")))


def test_the_digits_latex_prints_are_the_ones_the_mask_keeps(tmp_path: Path) -> None:
    files = _files()
    assert len(files) == FILES
    compiled, differ = 0, []
    for index, text in enumerate(files):
        folder = tmp_path / f"f{index:02d}"
        folder.mkdir()
        printed = _printed(folder, text)
        if printed is None:
            continue
        compiled += 1
        kept = "".join(re.findall(r"\d", read(text).masked.replace(NUL, " ")))
        if printed != kept:
            differ.append(f"printed {printed!r}, mask keeps {kept!r}: {text!r}")
    assert compiled >= FILES // 2, f"LaTeX stopped on {FILES - compiled} of {FILES} files"
    assert not differ, "\n".join(differ)
