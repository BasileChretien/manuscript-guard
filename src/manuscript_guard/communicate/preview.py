"""`communication/preview.html`: every text as it would be read, in one page, and what the
check says of each.

Each text is printed: its front matter set out above it, each binding its display, each
anchor nothing, each slot still to write shown as one, and a thread's posts apart with each
one's length against its channel's. The page is written from the texts and the results
alone, with no date and no link to anything outside it, so that the same texts give the
same bytes. It is for reading before anything is shared; nothing reads it back.
"""

from __future__ import annotations

import html
import re
from pathlib import Path

from manuscript_guard.communicate import texts as texts_module
from manuscript_guard.findings import FAIL, WARN

_SLOT = re.compile(r"<!--[ \t\n]*write:(?P<what>.*?)-->", re.DOTALL)
_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)

_STYLE = """
:root { --ink: #1b1b1b; --muted: #5a5a5a; --paper: #ffffff; --card: #f5f5f2;
  --rule: #d8d8d2; --fail: #a4262c; --warn: #8a5a00; --slot: #0b5cad; }
@media (prefers-color-scheme: dark) {
  :root { --ink: #ececec; --muted: #a8a8a8; --paper: #161616; --card: #222220;
    --rule: #3a3a36; --fail: #ff8a8f; --warn: #f2c14e; --slot: #79b8ff; } }
body { background: var(--paper); color: var(--ink); margin: 0 auto; max-width: 46rem;
  padding: 1.5rem 1rem; font: 16px/1.5 system-ui, sans-serif; }
h1 { font-size: 1.4rem; } h2 { font-size: 1.15rem; margin-top: 2.5rem; }
.meta { color: var(--muted); font-size: 0.9rem; margin: 0 0 0.75rem; }
.post { background: var(--card); border: 1px solid var(--rule); border-radius: 6px;
  padding: 0.75rem 1rem; margin: 0.75rem 0; white-space: pre-wrap; overflow-wrap: anywhere; }
.length { color: var(--muted); font-size: 0.8rem; display: block; margin-top: 0.5rem; }
.slot { color: var(--slot); font-style: italic; }
.fail { color: var(--fail); } .warn { color: var(--warn); }
ul.found { padding-left: 1.2rem; font-size: 0.9rem; }
"""


def _printed(text: str, namespace: dict) -> str:
    """A post as read: each binding its display, each anchor nothing, each slot marked."""
    from manuscript_guard.text.placeholders import substitute

    shown = substitute(texts_module.LINK.sub("", text),
                       {ref: value.display for ref, value in namespace.items()})
    out, at = [], 0
    for found in _SLOT.finditer(shown):
        out.append(html.escape(_COMMENT.sub("", shown[at : found.start()])))
        out.append(f'<span class="slot">[to write: {html.escape(" ".join(found["what"].split()))}'
                   "]</span>")  # fmt: skip
        at = found.end()
    out.append(html.escape(_COMMENT.sub("", shown[at:])))
    return re.sub(r"\n{3,}", "\n\n", "".join(out)).strip()


def page(project, context, found: dict[Path, list]) -> str:
    """The preview of every text under communication/, with the findings `found` of each."""
    from manuscript_guard.communicate.checking import (
        channel_rules,
        limit_of,
        post_length,
        text_files,
    )
    from manuscript_guard.contracts._schema import read_text

    title = str(project.paper.get("title") or project.root.name)
    lines = ["<!doctype html>", '<html lang="en">', "<head>", '<meta charset="utf-8">',
             '<meta name="viewport" content="width=device-width, initial-scale=1">',
             "<title>Communication preview</title>", f"<style>{_STYLE}</style>", "</head>",
             "<body>", f"<h1>What is said of: {html.escape(title)}</h1>",
             '<p class="meta">Written by <code>manuscript-guard communicate build</code> from '
             "the texts under communication/ and the results as they stand. Nothing is sent "
             "from here.</p>"]  # fmt: skip
    for path in text_files(project):
        raw = read_text(path).replace("\r\n", "\n")
        read = texts_module.read(raw)
        channel = str(read.front.get("channel") or "")
        rules = channel_rules(channel)
        lines.append(f"<h2>{html.escape(path.name)}</h2>")
        meta = [f"{key}: {read.front[key]}" for key in
                ("channel", "audience", "version_shared", "links", "attachments")
                if key in read.front]  # fmt: skip
        lines.append(f'<p class="meta">{html.escape("; ".join(meta))}</p>')
        for low, high in read.posts or [(read.body_start, len(raw))]:
            shown = _printed(raw[low:high], context.namespace)
            if not shown:
                continue
            limit, _own = limit_of(context, channel, rules)
            size = post_length(context, read, low, high, rules)
            length = ""
            if limit is not None and size is not None:
                length = (f'<span class="length">{size} of {limit} '
                          f'{rules.get("unit") or "characters"}</span>')  # fmt: skip
            lines.append(f'<div class="post">{shown}{length}</div>')
        mine = [one for one in found.get(path, []) if one.severity in (FAIL, WARN)]
        if mine:
            lines.append('<ul class="found">')
            for one in mine:
                kind = "fail" if one.severity == FAIL else "warn"
                lines.append(f'<li class="{kind}"><code>{html.escape(one.code)}</code> '
                             f"{html.escape(one.message)}</li>")  # fmt: skip
            lines.append("</ul>")
        else:
            lines.append('<p class="meta">communicate check: nothing to say of it.</p>')
    lines += ["</body>", "</html>", ""]
    return "\n".join(lines)
