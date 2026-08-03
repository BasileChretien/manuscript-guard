"""Recipe file -> checklist profile.

The recipe carries both the parsing instructions and the bibliographic facts a profile must
record: where the document came from, when it was fetched, and under what licence. That
last field decides whether the generated profile can be redistributed with the toolkit or
must stay local to whoever ran it.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from manuscript_guard.reporting.transcribe import Recipe, RecipeError, transcribe, verify

RECIPE_SUFFIX = ".recipe.yaml"


def load_recipe(path: Path) -> tuple[Recipe, dict]:
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise RecipeError(f"{path.name} is not a mapping")
    meta = document.get("meta", {})
    for required in ("name", "source_url", "retrieved_on", "licence"):
        if not meta.get(required):
            raise RecipeError(f"{path.name}: meta.{required} is required")
    parse = {k: v for k, v in document.items() if k not in {"schema", "meta"}}
    parse["name"] = meta["name"]
    # Column-mode keys belong to the PDF reader, not to the table reader.
    layout = {key: parse.pop(key, None) for key in ("format", "pages", "column_split")}
    parse.pop("download_url", None)
    recipe = Recipe.from_dict(parse)
    return recipe, {**meta, "_layout": layout}


def build_profile(
    recipe_path: Path, sources_dir: Path, out_dir: Path, *, allow_changed: bool = False
) -> tuple[Path, int, list[str]]:
    """Transcribe one checklist. Returns the profile path, item count and any unverified ids."""
    recipe, meta = load_recipe(recipe_path)
    layout = meta.pop("_layout", {})
    parse_mode = layout.get("format") or "docx-table"
    pages = layout.get("pages")
    column_split = layout.get("column_split")

    document = sources_dir / recipe.document
    if not document.exists():
        raise FileNotFoundError(
            f"{recipe.document} is not in {sources_dir}. Download it from "
            f"{meta['source_url']} and put it there."
        )

    expected = meta.get("sha256")
    if expected and not allow_changed:
        import hashlib

        actual = hashlib.sha256(document.read_bytes()).hexdigest()
        if actual != expected:
            raise RecipeError(
                f"{recipe.document} is not the document this recipe was written for.\n"
                f"    expected {expected[:16]}…\n    found    {actual[:16]}…\n"
                f"    A revised checklist may have moved or renumbered items, so the recipe's "
                f"column mapping may no longer fit. Check {meta['source_url']}, update the "
                f"recipe, and record the new sha256. Use --allow-changed to transcribe anyway."
            )

    if str(parse_mode).startswith("pdf"):
        from manuscript_guard.literature.sources import contains
        from manuscript_guard.reporting.columns import ColumnRecipe, transcribe_columns

        column_recipe = ColumnRecipe(
            document=recipe.document,
            pages=tuple(pages or (1,)),
            column_split=int(column_split or 0),
        )
        from manuscript_guard.reporting.columns import opening

        items, haystack = transcribe_columns(document, column_recipe)
        unverified = [item.id for item in items if not contains(haystack, opening(item.text))]
        meta = {**meta, "verification": "opening clause only (column-laid-out PDF)"}
    else:
        items = transcribe(document, recipe)
        unverified = verify(items, document)

    profile = {
        "schema": "manuscript-guard/reporting/1",
        "name": meta["name"],
        "long_name": meta.get("long_name", meta["name"]),
        "version": meta.get("version", ""),
        "source_url": meta["source_url"],
        "source_file": f"sources/{recipe.document}",
        "retrieved_on": str(meta["retrieved_on"]),
        "retrieved_by": meta.get("retrieved_by", "manuscript-guard transcribe"),
        "applies_to": meta.get("applies_to", ""),
        "licence": meta["licence"],
        "verification": meta.get("verification", "every item verified verbatim in the source"),
        "items": [
            {
                "id": item.id,
                "section": item.section,
                "topic": item.topic or item.section,
                "text": item.text,
            }
            for item in items
        ],
    }
    profile = {k: v for k, v in profile.items() if v != ""}

    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{meta['name']}.yaml"
    header = (
        f"# Transcribed by `manuscript-guard transcribe` from the official document.\n"
        f"# Source: {meta['source_url']}\n"
        f"# Licence: {meta['licence']}\n"
        f"# Do not edit by hand: re-run the transcription instead, so the profile stays a\n"
        f"# function of the published checklist rather than of anyone's memory.\n\n"
    )
    path.write_text(
        header + yaml.safe_dump(profile, sort_keys=False, allow_unicode=True, width=100),
        encoding="utf-8",
    )
    return path, len(items), unverified
