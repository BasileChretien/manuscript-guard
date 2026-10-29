"""The guides `communicate build` writes beside the texts, under `communication/guides/`: what
is shared when, and the steps ResearchGate takes by hand. They are no texts: nothing of the
paper is said in them, and `communicate check` does not read them.
"""

from __future__ import annotations

from manuscript_guard.communicate import lifecycle as when
from manuscript_guard.communicate.sharing import VERSIONS, _policy
from manuscript_guard.communicate.status import OUT, publication


def lifecycle_text(held: when.Standing) -> list[str]:
    lines = ["| Channel | When | Now |", "|---|---|---|"]
    for one in held.due:
        lines.append(f"| {one.channel} | {one.when} | {one.state}, {one.why} |")
    return lines if held.due else ["No channel is named: list them under "
                                   "`communication.channels`, or `communication.triggers`, in "
                                   "paper.yaml."]  # fmt: skip


def lifecycle(project) -> str:
    """What is shared when, as `communicate status` says it today."""
    held = when.standing(project)
    lines = [
        "# When each text is shared",
        "",
        "Written by `manuscript-guard communicate build` from paper.yaml's `publication` and "
        "`communication.triggers`, and written again each time it runs. `manuscript-guard "
        "communicate status` says the same for the day it is asked, and `--prepare` writes "
        "what is due. Nothing is shared by the tool, and nothing runs in the background.",
        "",
        f"Publication status: {held.status}.",
    ]
    if held.embargo:
        lines.append(f"Embargo: until {held.embargo}. Nothing is shared before it lifts.")
    lines += ["", *lifecycle_text(held), ""]
    return "\n".join(lines)


def researchgate(project) -> str:
    """ResearchGate has no interface a tool may post through: the steps, by hand."""
    said = publication(project)
    doi = said.get("doi")
    out = said.get("status") in OUT
    where = (f"its DOI, {doi}" if doi and out
             else "its DOI, once the paper is online and paper.yaml's `publication` says so")
    lines = [
        "# Adding the paper to ResearchGate, by hand",
        "",
        "ResearchGate has no interface a tool may post through, so these steps are yours, "
        "and nothing here is sent.",
        "",
        f"1. Sign in, and add the paper as a publication by {where}.",
        "2. For its summary, paste `communication/researchgate.md` as printed, once its slots "
        "are written and `manuscript-guard communicate check` passes it.",
        "3. Upload a file of the paper only where the journal's sharing policy allows it:",
        "",
    ]
    policy = _policy(project)
    if policy is None:
        lines.append("   - The journal's profile records no sharing policy: link the DOI and "
                     "upload nothing.")  # fmt: skip
    else:
        for version in VERSIONS:
            entry = policy.get(version)
            if not isinstance(entry, dict):
                lines.append(f"   - The {version} version: the policy says nothing of it; "
                             "upload nothing of it.")  # fmt: skip
                continue
            allowed = "academic-network" in (entry.get("where") or [])
            text = f"   - The {version} version: " + (
                "may be uploaded to an academic network" if allowed else "not to an academic "
                "network")  # fmt: skip
            if allowed and entry.get("embargo_months"):
                text += f", {entry['embargo_months']} months after publication"
            if allowed and entry.get("licence"):
                text += f", under {entry['licence']}"
            if allowed and entry.get("set_statement"):
                text += f", carrying the statement: \"{entry['set_statement']}\""
            lines.append(text + ".")
    lines += [
        "",
        "4. Name the file you upload in the front matter of `communication/researchgate.md`, "
        "under `attachments`, with the version under `version_shared`: "
        "`communicate check` then holds the upload to the policy.",
        "",
    ]
    return "\n".join(lines)
