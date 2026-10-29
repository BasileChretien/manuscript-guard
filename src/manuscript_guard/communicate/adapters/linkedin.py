"""LinkedIn: deferred. The text, printed for the author to paste.

Posting to LinkedIn takes an app of the author's own with the `w_member_social` permission,
which LinkedIn reviews, and a token that lasts sixty days: more than one paper's post is
worth setting up. So `communicate publish linkedin` prints the text as it would be read and
where to paste it, and posts nothing, with `--post` or without. An adapter is built when an
author asks for one (DESIGN.md, Known gaps).
"""

from __future__ import annotations

#: Where a post is begun.
FEED = "https://www.linkedin.com/feed/"


def manual(posts: list[str], images: list) -> str:
    lines = [f"LinkedIn, by hand: nothing posts to LinkedIn for you. Open {FEED}, choose "
             "\"Start a post\", and paste:", ""]  # fmt: skip
    lines.append("\n\n".join(posts))
    for image in images:
        lines += ["", f"Add {image.name} as an image, with the alternative text: {image.alt}"]
    return "\n".join(lines) + "\n"
