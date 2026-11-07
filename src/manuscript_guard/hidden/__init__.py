"""What a file holds that a person reading it does not see, and a model reading it does.

One reader, used wherever a file is read for a model or sent to one: `read_hidden` reads a
Word document (`hidden.word`), and `hidden.words` holds the rules of the characters and the
words that every reader applies to text.
"""

from manuscript_guard.hidden.word import (
    BACKGROUND,
    HIDDEN,
    TINY,
    TO_A_MODEL,
    ZERO_WIDTH,
    Hidden,
    Reading,
    read_hidden,
)

__all__ = [
    "BACKGROUND",
    "HIDDEN",
    "TINY",
    "TO_A_MODEL",
    "ZERO_WIDTH",
    "Hidden",
    "Reading",
    "read_hidden",
]
