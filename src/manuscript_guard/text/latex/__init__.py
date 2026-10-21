"""Reading a LaTeX manuscript as the gates read a Markdown one (DESIGN.md, "LaTeX manuscripts").

`mask.py` gives `mask`'s contract for a `.tex` file: the same length, line breaks kept, and
what is not prose replaced by NUL. `commands.py` is the closed table of what each known command
takes, and what each argument is.
"""
