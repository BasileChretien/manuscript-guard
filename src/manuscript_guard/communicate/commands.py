"""What each verb of `manuscript-guard communicate` does, apart from the command line."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from manuscript_guard.communicate import (
    Refused,
    brief_path,
    checking,
    graphical_abstract_folder,
    require_enabled,
    svg,
    templates,
)
from manuscript_guard.communicate import brief as brief_module


def write_brief(project, *, force: bool = False) -> Path:
    """Write the scaffolded brief, and refuse to write over one: it holds the author's marks
    of the primary finding and their own texts."""
    require_enabled(project)
    path = brief_path(project)
    if path.exists() and not force:
        raise Refused(
            f"{path} exists, and holds what you marked and wrote in it: edit it, or give "
            "--force to write it again from the manuscript as it stands"
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(brief_module.dump(brief_module.scaffold(project)).encode("utf-8"))
    return path


@dataclass(frozen=True)
class Drawn:
    written: list[Path]
    size: svg.Size
    template: str
    why: str


def draw(project, template: str | None = None) -> Drawn:
    """Draw both concepts of the graphical abstract, their alternative text and their notes,
    and the report `communicate check --only graphical-abstract` gives of them."""
    from manuscript_guard.contracts import load_namespace
    from manuscript_guard.palettes import colours

    require_enabled(project)
    brief, report = brief_module.load(project)
    if brief is None:
        why = report.findings[0].message if report.findings else "there is no brief"
        raise Refused(f"{why}: write it with `communicate brief`, and mark the primary finding")
    if not report.ok:
        raise Refused(f"{brief.path} is not a brief that can be read: {report.findings[0].message}")
    if not brief.primary:
        raise Refused(
            f"no finding of {brief.path} is marked `primary: true`: the graphical abstract "
            "draws the primary finding large, and which one it is is yours to say"
        )
    namespace, _results, _literature, _load = load_namespace(project)
    unbound = sorted({ref for one in brief.statements
                      for ref in svg.unbound_refs(one, namespace)})  # fmt: skip
    if unbound:
        raise Refused(f"the brief binds values nothing emits: {', '.join(unbound)}")
    held = svg.panels(brief)
    drawn = [*held.asked, *held.how, *held.primary, *held.secondary, *held.means]
    refused = [(one.id, why) for one in drawn if (why := svg.not_drawn(one.text))]
    if refused:
        raise Refused(
            "the graphical abstract does not draw what it cannot print as the build does: "
            + "; ".join(f"{name}: {why}" for name, why in refused)
            + "; shorten the statement's text in the brief"
        )
    chosen, why = templates.chosen(template, project.study_type)
    rules, _profile = checking.journal_rules(project)
    size = svg.size_of(rules)
    palette = colours("okabe-ito")
    # Blue, orange and bluish green: three of Okabe and Ito's that stay apart from each
    # other for each deficiency, black being the text's.
    panel_colours = [palette[5], palette[1], palette[3]]
    least = rules.get("min_text_pt")
    folder = graphical_abstract_folder(project)
    folder.mkdir(parents=True, exist_ok=True)
    pointers = svg.pointers(project)
    shown = {**namespace, **pointers}
    files = {
        "concept-1.svg": svg.concept_1(brief, chosen, size, panel_colours, shown, least),
        "concept-2.svg": svg.concept_2(brief, chosen, size, panel_colours, shown, least),
        checking.CONCEPT: svg.concept_md(brief, chosen, why, size).encode("utf-8"),
        checking.ALT_TEXT: svg.alt_text(brief, chosen, pointers).encode("utf-8"),
    }
    written = []
    for name, data in files.items():
        (folder / name).write_bytes(data)
        written.append(folder / name)
    report_path = folder / checking.VALIDATION_REPORT
    validation = checking.check(project, only="graphical-abstract")
    report_path.write_bytes(
        checking.render(validation, project.root,
                        "communicate check --only graphical-abstract").encode("utf-8")  # fmt: skip
    )
    written.append(report_path)
    return Drawn(written, size, chosen.name, why)
