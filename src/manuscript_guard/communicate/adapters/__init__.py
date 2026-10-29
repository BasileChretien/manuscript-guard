"""What `communicate publish --post` sends a text with, one module for each service.

- `bluesky.py`: a session, an image's blob with its alternative text, and a record for each
  post, a link marked at its UTF-8 bytes, a thread's posts each a reply to its root and to
  the post before.
- `mastodon.py`: an image with its description, then a status for each post, each sent with
  an `Idempotency-Key`, a thread's each in reply to the post before.
- `linkedin.py`: deferred. The text, printed for the author to paste.
- `researchgate.py`: the steps, by hand; ResearchGate has no interface a tool may post
  through.
- `orcid.py`: whether the paper's DOI is already on an author's public ORCID record. It reads
  and never writes.

Every request goes through a transport given as an argument (`net.py`). The default one
refuses when `MANUSCRIPT_GUARD_NO_NETWORK` is set, which the test suite sets: a test answers
from a loopback server or from a table, and never reaches a service. Nothing sends an e-mail.
"""
