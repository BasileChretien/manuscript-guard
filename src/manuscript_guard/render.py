"""Recording what a figure script actually rendered.

G3 reads a figure's text layer, which only vector formats have. A raster beside a vector of
the same name was therefore skipped: the sibling carries the text, so the numbers are
checked and warning twice would be noise.

Nothing proved the two were the same picture. Render `forest.svg` and `forest.png` honestly,
then re-render only the PNG from a script somewhere else — retouched, with a different
number in it — and the check passes while the build embeds the PNG. Verified end to end
during an adversarial review: the PNG in the .docx had the retouched digest, and the SVG
that G3 had inspected showed the correct value.

So the pairing has to be recorded rather than assumed. A figure script calls `record()` with
everything it wrote, and gets `figures/<stem>.render.json` holding each file's digest and
the script's. G3 skips a raster only when the manifest says it came from the same run as the
vector it is standing behind, and both files still match their digests.

    from manuscript_guard.render import record

    fig.savefig(OUT / "forest.svg")
    fig.savefig(OUT / "forest.png", dpi=300)
    record(__file__, OUT / "forest.svg", OUT / "forest.png")
"""

from __future__ import annotations

import json
from pathlib import Path

from manuscript_guard.emit import sha256_of

SUFFIX = ".render.json"
SCHEMA = "manuscript-guard/render/1"


def manifest_path(figure: Path) -> Path:
    return figure.with_name(f"{figure.stem}{SUFFIX}")


def record(script: str | Path, *outputs: str | Path) -> Path:
    """Write the manifest for one figure. Returns its path.

    All outputs must share a stem — they are one figure in several formats, which is the
    only thing this proves anything about.
    """
    paths = [Path(p).resolve() for p in outputs]
    if not paths:
        raise ValueError("record() needs at least one rendered file")
    missing = [p for p in paths if not p.exists()]
    if missing:
        raise FileNotFoundError(f"not written yet: {', '.join(p.name for p in missing)}")
    stems = {p.stem for p in paths}
    if len(stems) != 1:
        raise ValueError(
            f"one manifest describes one figure, but these have different stems: "
            f"{', '.join(sorted(stems))}"
        )

    script_path = Path(script).resolve()
    document = {
        "schema": SCHEMA,
        "rendered_by": script_path.name,
        "rendered_by_sha256": sha256_of(script_path),
        "outputs": {p.name: sha256_of(p) for p in sorted(paths, key=lambda p: p.name)},
    }
    path = manifest_path(paths[0])
    path.write_text(
        json.dumps(document, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n"
    )
    return path


def read(figure: Path) -> dict | None:
    path = manifest_path(figure)
    if not path.exists():
        return None
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return document if isinstance(document, dict) else None


def same_render(raster: Path, vector: Path) -> bool:
    """Whether the manifest says these two came from one run, and both still match it."""
    document = read(raster)
    if document is None:
        return False
    outputs = document.get("outputs")
    if not isinstance(outputs, dict):
        return False
    for path in (raster, vector):
        recorded = outputs.get(path.name)
        if not recorded or not path.exists() or sha256_of(path) != recorded:
            return False
    return True


__all__ = ["SCHEMA", "SUFFIX", "manifest_path", "read", "record", "same_render"]
