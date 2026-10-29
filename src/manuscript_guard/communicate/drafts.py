"""What `communicate build` writes for each channel: the texts, from the brief alone.

Every sentence a text takes from the brief is the statement's `text` as the brief writes
it, each of its sentences anchored to the statement (`[](#brief:findings.2)`), so that
`communicate check` holds it to its quote. What the tool cannot write, a headline, a quote
from an author, a sentence in plain words, is left as a slot for the author or an agent,
`<!-- write: … -->`, which prints nothing and which the check does not read. The skill
research-communication says how a slot is filled: from the brief, with no number and no
claim the brief does not make.

Each text opens with front matter that says what it is: its `channel`, its `audience`, the
version of the paper it shares (`version_shared`: `published` where it links the paper, once
the paper is online, and `none` before), its `links` and its `attachments`.
"""

from __future__ import annotations

from dataclasses import dataclass

import yaml

from manuscript_guard.claims import sentence_spans
from manuscript_guard.communicate.brief import Brief, Statement


def anchored(statement: Statement, *, bare: bool = False) -> str:
    """A statement's text with each of its sentences anchored to it, right after its stop;
    `bare`, for a post, without its bracketed citations and its marks of emphasis."""
    from manuscript_guard.communicate.svg import bare as without_marks

    text = " ".join((without_marks(statement.text) if bare else statement.text).split())
    pieces = [text[first:end].strip() for _piece, first, end in sentence_spans(text)]
    pieces = [piece for piece in pieces if piece] or [text]
    return " ".join(f"{piece} [](#brief:{statement.id})" for piece in pieces)


def front_matter(channel: str, audience: str, *, version: str = "none",
                 links: list[str] | None = None, attachments: list[str] | None = None,
                 extra: dict | None = None) -> str:  # fmt: skip
    document = {
        "channel": channel,
        "audience": audience,
        "version_shared": version,
        "links": list(links or []),
        "attachments": list(attachments or []),
        **(extra or {}),
    }
    body = yaml.safe_dump(document, sort_keys=False, allow_unicode=True, width=10**6,
                          default_flow_style=None)  # fmt: skip
    return f"---\n{body}---\n"


def slot(instruction: str) -> str:
    """A slot for the author or an agent: what to write there, which prints nothing."""
    return f"<!-- write: {_commented(instruction)} -->"


def _commented(text: str) -> str:
    """Text that can stand inside a comment: no `-->` to close it early."""
    return " ".join(text.split()).replace("-->", "-- >")


def ids(statements: list[Statement]) -> str:
    return ", ".join(one.id for one in statements) or "nothing in the brief"


@dataclass(frozen=True)
class Parts:
    """The brief's statements as the texts use them."""

    question: list[Statement]
    how: list[Statement]
    primary: list[Statement]
    secondary: list[Statement]
    limitations: list[Statement]
    conclusion: list[Statement]

    @classmethod
    def of(cls, brief: Brief) -> Parts:
        findings = brief.of("findings")
        return cls(
            brief.of("question"),
            [*brief.of("design"), *brief.of("population"), *brief.of("methods"),
             *brief.of("primary_outcome")],
            [one for one in findings if one.primary],
            [one for one in findings if not one.primary],
            brief.of("limitations"),
            brief.of("conclusion"),
        )  # fmt: skip


def said(statements: list[Statement], *, bare: bool = False) -> list[str]:
    return [anchored(one, bare=bare) for one in statements]


def paragraphs(*blocks: str | list[str] | None) -> str:
    out: list[str] = []
    for block in blocks:
        if block is None:
            continue
        out += [block] if isinstance(block, str) else [one for one in block if one]
    return "\n\n".join(out) + "\n"


# ------------------------------------------------------------------------------ the posts


def post(parts: Parts, link: str | None, with_conclusion: bool) -> str:
    """One post: the primary findings, the conclusion's first statement where it fits, and
    the link to the paper once it is online. A post and a thread carry no citation and no
    emphasis (`svg.bare`)."""
    return paragraphs(said(parts.primary, bare=True),
                      said(parts.conclusion[:1], bare=True) if with_conclusion else None,
                      link)  # fmt: skip


def thread(parts: Parts, link: str | None) -> str:
    """A thread: a post for each statement, the question, the findings primary first, the
    limitations and the conclusion, and the link to the paper last once it is online."""
    statements = [*parts.question, *parts.primary, *parts.secondary, *parts.limitations,
                  *parts.conclusion]  # fmt: skip
    posts = said(statements, bare=True) + ([f"Read the paper: {link}"] if link else [])
    return "\n\n---\n\n".join(posts) + "\n"


def overview_note() -> str:
    return paragraphs(
        "The slide is `overview.svg` beside this file, drawn from the brief: the question, "
        "the primary finding and what it means. `communicate build --force` draws it again "
        "from the brief and the results as they stand.",
    )


def poster(parts: Parts, title: str) -> str:
    sections = [
        "## Title", slot(f"the poster's title: the paper's, '{title}', or a shorter one that "
                         "claims no more"),
        "## Question", said(parts.question),
        "## Methods", said(parts.how),
        "## Findings", said(parts.primary), said(parts.secondary),
        "## Limitations", said(parts.limitations) or slot(
            "the brief holds no limitation: write one into it, quoted from the paper, and "
            "build again"),
        "## Conclusion", said(parts.conclusion),
        "## Figure", slot("which figure of the paper to show, and its caption as the paper "
                          "prints it"),
    ]  # fmt: skip
    return paragraphs(*sections)


def storyboard(parts: Parts) -> str:
    scenes = [("The question", parts.question), ("How it was studied", parts.how[:1]),
              ("The finding", parts.primary), ("What it cannot show", parts.limitations),
              ("What it means", parts.conclusion)]  # fmt: skip
    blocks: list[str] = []
    for heading, statements in scenes:
        if not statements:
            continue
        blocks += [f"## {heading}",
                   slot(f"what is on screen while this is said: {ids(statements)}"),
                   *said(statements)]  # fmt: skip
    return paragraphs(*blocks)


#: Where a licence's SPDX identifier is read: its page on the SPDX list.
SPDX_PAGE = "https://spdx.org/licenses/{}.html"


def announcement(package_doi: str, licences: list[str], link: str | None) -> str:
    """The deposit announced, each licence named by its page on the SPDX list: a link, which
    the check does not read as a number, where `CC-BY-4.0` written out would be one."""
    named = " and ".join(SPDX_PAGE.format(one) for one in licences)
    kind = "licence" if len(licences) == 1 else "licences"
    return paragraphs(
        f"The code and results behind the paper are deposited at "
        f"https://doi.org/{package_doi}, under the {kind} {named}.",
        f"The paper is at {link}." if link else None,
    )


def translation(parts: Parts, language: str) -> str:
    """A slot for each statement, with its English and its bindings beside it."""
    from manuscript_guard.text.placeholders import VALUE_NAMESPACES, parse

    blocks: list[str] = []
    for one in [*parts.question, *parts.primary, *parts.secondary, *parts.limitations,
                *parts.conclusion]:  # fmt: skip
        bound = [p.raw for p in parse(one.text)[0] if p.namespace in VALUE_NAMESPACES]
        kept = (f"keep {', '.join(dict.fromkeys(bound))} as written, " if bound else "")
        blocks.append(
            f"<!-- source, {one.id}: {_commented(one.text)} -->\n"
            + slot(f"{one.id} in {language}: {kept}add no number and no claim, and end each "
                   f"sentence with [](#brief:{one.id})")
        )  # fmt: skip
    return paragraphs(*blocks)


# ------------------------------------------------------------------------------ the slots

#: Each scaffold: what is written, in order. A string is a slot's instruction, and a name of
#: the brief's parts in angle brackets its statements, anchored.
_PLAIN = ("in words a reader with no training in research follows, keeping each binding "
          "and its anchor; or leave the sentence below as it is")  # fmt: skip
SCAFFOLDS: dict[str, tuple[str, ...]] = {
    "linkedin": (
        "an opening line for LinkedIn that says what question.1 asks, with no number",
        "<primary>", "<conclusion>",
        "one line on who did the study, without a claim the brief does not make",
        "<link>",
    ),
    "researchgate": (
        "the summary ResearchGate shows under the paper: two or three sentences from the "
        "brief, each claiming sentence anchored to its statement",
        "<primary>", "<conclusion>",
    ),
    "press-release": (
        "a headline of at most twelve words that says what the primary finding says, with "
        "no number and no more strongly",
        "the opening paragraph: what the study asked and what it found, each claiming "
        "sentence anchored to its statement",
        "<primary>", "<secondary>",
        "why it matters, from the conclusion's statements only",
        "<limitations>", "<conclusion>",
        "a quote from an author, in the author's own words and approved by them, with no "
        "number and no claim the brief does not make",
        "notes to editors: the paper's title and journal, and a contact",
        "<link>",
    ),
    "pitch": (
        "the e-mail's subject, of at most ten words, with no number; this is a draft, and "
        "manuscript-guard sends no e-mail",
        "a greeting, and one sentence on why this reader would care",
        "<primary>", "<limitations>", "<conclusion>",
        "what you offer: an interview, the paper under embargo, a figure; and a signature",
    ),
    "newsletter": (
        "a title for the item, with no number",
        "<question>", "<primary>", "<conclusion>",
        "where to read more, before the link to the paper below once it is online",
        "<link>",
    ),
    "plain-language-summary": (
        "what the study asked, " + _PLAIN, "<question>",
        "what it found, " + _PLAIN, "<primary>",
        "what it cannot show, " + _PLAIN, "<limitations>",
        "what it means, " + _PLAIN, "<conclusion>",
    ),
    "plain-language-patients": (
        "what the study asked, for people who take the medicine or have the condition, "
        + _PLAIN, "<question>",
        "what it found, " + _PLAIN, "<primary>",
        "what it cannot show, " + _PLAIN, "<limitations>",
        "what it means for them, from the conclusion only, with no advice the paper does not "
        "give", "<conclusion>",
    ),
    "plain-language-clinicians": (
        "what the study asked, for clinicians, in one or two sentences", "<question>",
        "how it was done, from the brief's design, population and methods", "<how>",
        "<primary>", "<secondary>", "<limitations>",
        "what it means in practice, from the conclusion only", "<conclusion>",
    ),
    "plain-language-policymakers": (
        "what the study asked, for those who decide policy, in one sentence", "<question>",
        "<primary>", "<limitations>",
        "what it means for policy, from the conclusion only, with no recommendation the "
        "paper does not make", "<conclusion>",
    ),
    "video-script": (
        "about ten seconds: what the study asked, spoken", "<question>",
        "about twenty seconds: what it found, spoken, the values as their bindings",
        "<primary>",
        "about fifteen seconds: what it cannot show", "<limitations>",
        "about fifteen seconds: what it means, and where to read the paper", "<conclusion>",
    ),
}


def scaffold(name: str, parts: Parts, link: str | None) -> str:
    blocks: list[str | list[str] | None] = []
    for step in SCAFFOLDS[name]:
        if step == "<link>":
            blocks.append(link)
        elif step.startswith("<") and step.endswith(">"):
            statements = getattr(parts, step[1:-1])
            if step == "<limitations>" and not statements:
                blocks.append(slot("the brief holds no limitation: write one into it, quoted "
                                   "from the paper, and build again"))  # fmt: skip
            blocks.append(said(statements))
        else:
            blocks.append(slot(step))
    return paragraphs(*blocks)
