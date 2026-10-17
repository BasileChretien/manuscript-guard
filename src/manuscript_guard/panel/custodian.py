"""The data custodian decides whether the manuscript may go to a model provider.

Many data-use agreements forbid sending the data, or what is computed from them, anywhere
the custodian has not agreed to. A review panel read by a model sends the manuscript, and
its results with it, to whichever provider `review.models` names. Where `paper.yaml` says
the custodian restricts that (`custodian: {restricts_sending: true}`), `review --run` sends
to a provider on this machine, and to any other only where the data custodian `authors.yaml`
names has authorised it: a sign-off (`sign_offs.py`) of that provider, bound to where its
calls go. An Ollama model that the server on this machine passes on to Ollama's own servers
leaves the machine, and is authorised like any other. Nothing here sends anything.
"""

from __future__ import annotations

from manuscript_guard.contracts.project import Project
from manuscript_guard.findings import INFO, Finding
from manuscript_guard.panel.plan import passed_on
from manuscript_guard.panel.providers import ConfigError, Provider, configured_models
from manuscript_guard.sign_offs import Signable, digest_of, settle

GATE = "G11"
CODE = "provider-not-authorised"
ROLE = "data_custodian"


def restricts_sending(project: Project) -> bool:
    custodian = project.paper.get("custodian") if isinstance(project.paper, dict) else None
    return isinstance(custodian, dict) and custodian.get("restricts_sending") is True


def signable_id(provider: Provider) -> str:
    return f"{GATE}/custodian/send-to/{provider.name}"


def _where(provider: Provider, passes_on: bool) -> str:
    if not provider.local:
        return provider.host
    return f"{provider.host} and on to Ollama's servers" if passes_on else provider.host


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
        provider = model.provider
        on = provider.local and passed_on(model)
        if provider.local and not on:
            continue
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


def unauthorised(project: Project, providers: list[Provider]) -> list[Finding]:
    """What stops a run sending to these providers: for each one the custodian has not
    authorised as it now stands, the finding, with a hint that says who authorises it."""
    standing = {signable.id: signable for signable in send_signables(project)}
    stopped: list[Finding] = []
    for provider in providers:
        signable = standing.get(signable_id(provider))
        if signable is None:
            continue
        stopped += [f for f in settle(project, signable) if f.severity != INFO]
    return stopped


__all__ = ["CODE", "ROLE", "restricts_sending", "send_signables", "signable_id", "unauthorised"]
