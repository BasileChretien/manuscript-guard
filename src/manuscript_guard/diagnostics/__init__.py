"""What the tool keeps about its own failures, on this machine only.

`crashes` writes a record when the tool fails in a way it did not expect, and `scrub` takes
paths, e-mail addresses, secrets and the authors' names out of what is kept. `issue` writes
the report a person reads and posts, and `about` the report about a gate that got something
wrong, with a test to start from. Nothing here sends anything: the package imports no network
module, and a test reads its imports to hold that.
"""
