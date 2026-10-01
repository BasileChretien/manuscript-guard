"""Having the review panel read by models from several providers.

A panel drawn from one model shares that model's blind spots, and a panel that exists only as
an agent's skill is closed to anyone who does not run that agent. This package sends each
reviewer's remit and the manuscript to the models the author lists in `paper.yaml`, and files
what comes back as review records.

**Nothing here is a gate, and no gate imports this package.** The gates run in CI with no
network and no model. A provider's reply is untrusted input: it is validated against the
reply schema and refused if it does not fit, never repaired. What is filed is a review
record like any other, and G11 reads records. A model does not decide whether the manuscript
is clean.

The manuscript is unpublished, and sending it to a third party is the author's decision.
Nothing is sent before the command has said which files go to which provider and been told
yes; the dry run shows the same thing and sends nothing.
"""
