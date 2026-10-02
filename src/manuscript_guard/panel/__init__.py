"""Having the review panel read by models from several providers.

A panel drawn from one model shares that model's blind spots, and a panel that exists only as
an agent's skill is closed to anyone who does not run that agent. This package builds, for
each reviewer's remit and each model the author lists in `paper.yaml`, the request that
would have that model read the manuscript, and reads a reply back into the shape of a review.

**Nothing here is a gate, and no gate imports this package.** The gates run in CI with no
network and no model. A provider's reply is untrusted input: it is validated against the
reply schema and refused if it does not fit, never repaired. A model does not decide whether
the manuscript is clean; G11 reads review records, and decides.

The manuscript is unpublished, and sending it to a third party is the author's decision.
The dry run says which files would go to which provider and sends nothing. In this version
nothing is sent at all: the command that sends and files the readings follows.
"""
