"""The encoding the two entry points write in when their output is not a console.

Imported by `manuscript-guard-hook` before it knows whether it has work to do, so it imports
nothing beyond the standard library.
"""

from __future__ import annotations

import codecs
import contextlib
import io
import os
import sys

#: What a person sets to choose the encoding of standard output. Either one, set to any value
#: but an empty one, is followed as Python reads it, and nothing here overrides it.
_SAID_BY_THE_USER = ("PYTHONIOENCODING", "PYTHONUTF8")


def utf8_when_piped() -> None:
    """Write UTF-8 to a standard output or error that is a pipe or a file.

    Python opens a pipe in the locale's code page on Windows, cp1252 for most, and every
    character outside it was written as `?`: a Japanese quote in a finding's context came out
    as "?????", and the `é` of an author's name as the single byte 0xE9, which no reader of
    UTF-8 can decode. An agent's tool, `> file` and a CI log all read the output through a
    pipe, and read it as UTF-8.

    A console is left as Python opened it: on Windows Python writes to it as UTF-16 whatever
    the code page, and elsewhere it is in the terminal's own encoding. So is every stream when
    `PYTHONIOENCODING` or `PYTHONUTF8` is set to a value, whatever it is (an empty one counts
    as unset, as it does to Python), or Python runs with `-X utf8`. A stream that cannot be
    reconfigured (one a host or a test put in place) is left as it is.
    """
    if any(os.environ.get(name) for name in _SAID_BY_THE_USER):
        return
    if "utf8" in getattr(sys, "_xoptions", {}):
        return
    for stream in (sys.stdout, sys.stderr):
        if stream is None:
            continue
        try:
            if stream.isatty():
                continue
        except (AttributeError, ValueError):  # no isatty, or closed
            continue
        encoding = getattr(stream, "encoding", None) or "utf-8"
        with contextlib.suppress(LookupError):
            if codecs.lookup(encoding).name == "utf-8":
                continue
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        # Its own error handler kept: `reconfigure` puts back `strict` when given an encoding
        # and no handler, and standard error would then raise on a lone surrogate in the
        # message it was writing, which `backslashreplace` writes as `\udcxx`.
        errors = getattr(stream, "errors", None) or "strict"
        with contextlib.suppress(ValueError, OSError, io.UnsupportedOperation):
            reconfigure(encoding="utf-8", errors=errors)
