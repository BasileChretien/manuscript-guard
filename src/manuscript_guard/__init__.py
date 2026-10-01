"""manuscript-guard — make every number in a manuscript traceable to its source.

The public promise of this package is deterministic: given the same project tree it
returns the same verdict, with no language model involved. Anything that constitutes a
guarantee lives here; the Claude Code plugin layered on top only helps an author write.
"""

# One number with pyproject.toml, plugin.json and the marketplace entry: see tests/test_version.py.
__version__ = "0.2.320"

from manuscript_guard.findings import Finding, Report

__all__ = ["Finding", "Report", "__version__"]
