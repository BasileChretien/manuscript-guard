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
    layout = {
        key: parse.pop(key, None)
        for key in (
            "format",
            "pages",
            "column_split",
            "min_options",
            "items",
            "options",
            "stop_at",
            "table",
        )
    }
    if layout["format"] == "jats-table":
        # A paper's table is not the checklist file: the recipe says which it read.
        for required in ("read_from",):
            if not meta.get(required):
                raise RecipeError(f"{path.name}: a jats-table recipe needs meta.{required}")
        if not layout["table"]:
            raise RecipeError(f"{path.name}: a jats-table recipe names its `table`")
    parse.pop("download_url", None)
    recipe = Recipe.from_dict(parse)
    return recipe, {**meta, "_layout": layout}


def rows_digest_of(recipe_path: Path, sources_dir: Path) -> str | None:
    """The digest of the rows a jats-table recipe reads, for its author to record; None for
    any other recipe, or where the document is not there to read."""
    _recipe, meta = load_recipe(recipe_path)
    layout = meta["_layout"]
    document = sources_dir / _recipe.document
    if layout.get("format") != "jats-table" or not document.exists():
        return None
    from manuscript_guard.reporting.jats import rows_digest, table_rows

    return rows_digest(*table_rows(document, str(layout["table"])))


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

    # The bytes of a paper's XML can change with nothing in its table changed; such a recipe
    # records a digest of the rows instead, checked where they are read.
    expected = meta.get("sha256") if parse_mode != "jats-table" else None
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

    if parse_mode == "pdf-scale":
        # A rating scale, not a checklist: numbered items with the statements a rater chooses
        # between. There is nothing here to verify the items against — they are the reader's
        # output read line by line from its input — so the profile records which counts the
        # recipe stated instead of claiming a check. `scale.py` states the rules the reader reads
        # by; the cases worth knowing are pinned in the tests DESIGN.md's Known gaps names, and
        # that entry says which cases are pinned by nothing.
        from manuscript_guard.reporting.scale import (
            ScaleRecipe,
            transcribe_scale,
            verification_for,
        )

        items, _read = transcribe_scale(
            document,
            ScaleRecipe(
                document=recipe.document,
                pages=tuple(pages or (1,)),
                min_options=int(layout.get("min_options") or 2),
                items=layout.get("items"),
                options=layout.get("options"),
                stop_at=layout.get("stop_at"),
            ),
        )
        unverified = []
        # Which of the four true sentences this profile gets. One string for every recipe said
        # "with the item counts the recipe states" of a recipe that states none, and the two
        # that replaced it said "no count" of a recipe that states one.
        meta = {
            **meta,
            "verification": verification_for(layout.get("items"), layout.get("options")),
            "kind": "scale",
        }
    elif parse_mode == "jats-table":
        from manuscript_guard.literature.sources import contains
        from manuscript_guard.reporting.jats import article_text, rows_digest, table_rows

        head, body = table_rows(document, str(layout["table"]))
        expected_rows = meta.get("rows_sha256")
        if expected_rows and not allow_changed and rows_digest(head, body) != expected_rows:
            raise RecipeError(
                f"table {layout['table']} of {recipe.document} is not the table this recipe "
                f"was written for: its rows have changed.\n"
                f"    A revised checklist may have moved or renumbered items. Check "
                f"{meta['source_url']}, update the recipe, and record the new rows_sha256 "
                f"(`manuscript-guard transcribe` prints it). Use --allow-changed to "
                f"transcribe anyway."
            )
        items = transcribe(document, recipe, tables=[body])
        haystack = article_text(document)
        unverified = [item.id for item in items if not contains(haystack, item.text)]
    elif str(parse_mode).startswith("pdf"):
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
        # "scale" where the items are a rater's, not a journal's: the submission pack presents
        # those differently, and a reader of the profile should not have to infer it.
        "kind": meta.get("kind", ""),
        "licence": meta["licence"],
        # Which document the items were read from, where it is not the checklist file: a
        # table of the statement paper can differ from the file in a column or a footnote.
        "read_from": meta.get("read_from", ""),
        # The guideline that replaced this one, as its authors say; G5 points it out.
        "superseded_by": meta.get("superseded_by", ""),
        # What actually happened, not what was hoped for. This was a constant string saying
        # "every item verified verbatim in the source", written whether or not verify()
        # came back clean — so a profile with eleven unverified items was byte-identical in
        # its own account of itself to one with none. The failure was printed to stdout and
        # then lost. Two different guarantees must not look the same on disk; that is the
        # reason this field exists at all.
        "verification": meta.get("verification")
        or (
            "every item verified verbatim in the source"
            if not unverified
            else f"{len(unverified)} of {len(items)} items NOT found verbatim in the source "
            f"({', '.join(unverified[:12])}"
            + (", …" if len(unverified) > 12 else "")
            + ") — treat this profile as unverified"
        ),
        "items": [
            {
                "id": item.id,
                "section": item.section,
                "topic": item.topic or item.section,
                "text": item.text,
                # A scale's parts, kept apart as the form prints them: the statements in order
                # and the score beside each. Absent for a checklist, whose item is one text.
                **(
                    {
                        "clarification": item.extras.get("clarification", ""),
                        "options": [
                            {"score": score, "statement": statement}
                            for statement, score in zip(
                                item.extras.get("statements", ()),
                                item.extras.get("scores", ()),
                                strict=True,
                            )
                        ],
                    }
                    if item.extras.get("statements")
                    else {}
                ),
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
        newline="\n",
    )
    return path, len(items), unverified
