"""Sending a manuscript's numbers to a co-author, and taking their answers back.

Every gate in this toolkit asks whether a number in the manuscript is the number the analysis
produced. None of them can ask the question a reader of the source asks: does the document
really say this, and does the sentence say what the document says. That is a person's work, and
on the first manuscript written with this toolkit it was the work that found the only error
three machine passes had missed — a share whose value and quote were both right while the
sentence and the ledger agreed with each other about the wrong denominator.

A co-author who can find that is rarely a co-author who will clone a repository, install Python
and run a server. So:

* `checker build --for "<name>"` writes **one file**: a page carrying every item, the sentences
  each appears in, and the evidence already rendered into it. It opens by double-clicking, in
  any current browser, offline, with nothing installed, no account and no network.
* The co-author clicks through the items and saves their answers — a few kilobytes — or copies
  them to the clipboard where a download is blocked.
* `checker import --answers <file>` records them under their name, refusing any answer whose
  item has changed since they saw it; and `checker status` says who has answered what, which
  answers are about text that has changed since — those items are outstanding again — and where
  two people disagree.

**What is the toolkit's and what is the project's.** The toolkit finds four kinds of item from
files every project keeps (`produce.py`): values quoted from the literature with the passage
each came from, sentences that cite something, the references, and the authors. So a round can
be sent from a project that has written nothing of its own.

What only the project knows, it contributes: that this number came from row 14 of that workbook,
and that one from a sentence on page 65 of a PDF, with the evidence rendered to images, tables
and text excerpts. It writes `checks/items.json`
(`contracts/schemas/checking.schema.json`), those items are asked first, and a group it fills it
fills alone — the two producers key their ids on different things, so a group taken item by item
would ask a co-author the same value twice.

`produce` and `merge` are not exported here: imported into this package under those names they
shadowed the submodule `checking.produce`, so `manuscript_guard.checking.produce` was a function
and not the module. They are imported from `checking.produce`.

Carrying all of it to a person who is not a programmer, and keeping the record of what came
back, is the rest of this package. Nothing here needs a dependency the toolkit did not already
have, and nothing in it is particular to one model, one vendor or one agent.
"""

from manuscript_guard.checking.bundle import BundleError, build_bundle
from manuscript_guard.checking.items import ItemsError, load_items
from manuscript_guard.checking.store import (
    AnswersError,
    import_answers,
    read_decisions,
    status,
)

__all__ = [
    "AnswersError",
    "BundleError",
    "ItemsError",
    "build_bundle",
    "import_answers",
    "load_items",
    "read_decisions",
    "status",
]
