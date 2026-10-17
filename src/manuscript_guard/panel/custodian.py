"""The data custodian decides whether the manuscript may go to a model provider.

Many data-use agreements forbid sending the data, or what is computed from them, anywhere
the custodian has not agreed to. A review panel read by a model sends the manuscript, and
its results with it, to whichever provider `review.models` names. Where `paper.yaml` says
the custodian restricts that (`custodian: {restricts_sending: true}`), `review --run` sends
to the built-in Ollama on this machine, and to any other provider only where the data
custodian `authors.yaml` names has authorised it: a sign-off (`sign_offs.py`) of that
provider, bound to where its calls go. A provider the author adds is authorised whatever its
address, since one at localhost may be a router or a tunnel, and an Ollama model that the
server here passes on to Ollama's own servers leaves the machine too. Nothing here sends
anything.
"""

from __future__ import annotations

from manuscript_guard.contracts.project import Project
from manuscript_guard.findings import INFO, Finding
from manuscript_guard.panel.plan import passed_on
from manuscript_guard.panel.providers import ConfigError, Model, Provider, configured_models
from manuscript_guard.sign_offs import Signable, digest_of, settle

GATE = "G11"
CODE = "provider-not-authorised"
ROLE = "data_custodian"


def restricts_sending(project: Project) -> bool:
    custodian = project.paper.get("custodian") if isinstance(project.paper, dict) else None
    return isinstance(custodian, dict) and custodian.get("restricts_sending") is True


def signable_id(provider: Provider) -> str:
    return f"{GATE}/custodian/send-to/{provider.name}"


def leaves(model: Model) -> bool:
    """Whether a call to this model may take the manuscript off this machine. Only a
    built-in provider here is taken at its address, for a model it is not known to pass on:
    a provider the author adds at localhost may be a router or a tunnel that sends what it
    receives elsewhere (round 1 of #323), so it is authorised like any other."""
    provider = model.provider
    return not (provider.builtin and provider.local and not passed_on(model))


def _where(provider: Provider, passes_on: bool) -> str:
    if provider.builtin and provider.local and passes_on:
        return f"{provider.host} and on to Ollama's servers"
    return provider.host


def send_signables(project: Project) -> list[Signable]:
    """One for each provider `review.models` would send the manuscript off this machine
    through, where the custodian restricts sending; none otherwise. What is signed is the
    provider, its address, and whether a server here passes its calls on."""
    if not restricts_sending(project):
        return []
    try:
        models = configured_models(project.paper)
    except ConfigError:
        return []
    leaving: dict[str, tuple[Provider, bool]] = {}
    for model in models:
        if not leaves(model):
            continue
        provider = model.provider
        on = provider.local and passed_on(model)
        held = leaving.get(provider.name)
        leaving[provider.name] = (provider, on or bool(held and held[1]))
    out = []
    for provider, on in leaving.values():
        finding = Finding(
            GATE,
            CODE,
            f"the data custodian restricts where the manuscript and its results may be sent, "
            f"and review.models sends them to {_where(provider, on)}",
            path=project.root / "paper.yaml",
        )
        digest = digest_of("send-to", provider.name, provider.base_url, on)
        out.append(Signable(ROLE, signable_id(provider), digest, (finding,)))
    return out


def unauthorised(project: Project, models: list[Model]) -> list[Finding]:
    """What stops a run calling these models: for each provider they would leave this
    machine through that the custodian has not authorised as it now stands, the finding,
    with a hint that says who authorises it. A provider with no sign-off to give is
    refused too, rather than sent to."""
    if not restricts_sending(project):
        return []
    standing = {signable.id: signable for signable in send_signables(project)}
    stopped: list[Finding] = []
    for provider in {m.provider.name: m.provider for m in models if leaves(m)}.values():
        signable = standing.get(signable_id(provider))
        if signable is None:
            stopped.append(Finding(GATE, CODE, "the data custodian restricts where the "
                                   f"manuscript may be sent, and {provider.host} is not one "
                                   "review.models names", path=project.root / "paper.yaml",
                                   hint="list the model in review.models, so that the "
                                   "custodian can authorise its provider"))  # fmt: skip
            continue
        stopped += [f for f in settle(project, signable) if f.severity != INFO]
    return stopped


__all__ = [
    "CODE",
    "ROLE",
    "leaves",
    "restricts_sending",
    "send_signables",
    "signable_id",
    "unauthorised",
]
