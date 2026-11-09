"""One file fetched from the web, following redirects over https only: what `sync-sources`
downloads a cited work's open copy, or its publisher's PDF, with.

`lookup/http.py` follows no redirect, since one would carry a registry key to a host nobody
chose. A download cannot work that way: doi.org answers every DOI with a redirect to the
publisher, and a repository's PDF link often redirects to a storage host. So this follows
them, under its own rules:

* **https only, at every hop.** A redirect to `http://` is refused rather than followed: the
  bytes kept as the work's would otherwise be ones anybody on the network could have changed.
* **Never this computer, nor its own network.** A link a publisher, a repository or OpenAlex
  gives is somebody else's choice, and a GET is enough to set off a service that trusts its
  network: Zotero's connector on 127.0.0.1:23119, a router at 192.168.1.1, a cloud's
  metadata at 169.254.169.254. So a URL whose host is any address that is not the
  internet's (Python's `is_global`: loopback, private, link-local, carrier-grade NAT as
  Tailscale uses it, unspecified and the rest), a multicast or reserved one, or IPv6's
  site-local one, is refused, and so is a name that resolves to one, resolved again before
  each hop (round 1 of #565: a 302 to `http://127.0.0.1:9/x` was followed). A host written
  as an IPv4 number in another form than four decimal parts, `2130706433` or `127.1`, is
  judged as the address the resolver reads it as; 6to4's 2002::/16, which carries an IPv4
  address and which some Pythons count as global, is refused whole. A link whose host
  holds a percent escape, a user's name before `@` or a backslash is refused, since
  `urllib` would ask another host than the one checked. The connection is then made to the
  addresses checked, the certificate held to the name, so that a resolver that answers the
  connection otherwise than the check (DNS rebinding) reaches nothing it was not checked
  for. Through an https proxy the environment names, the proxy makes the connection and
  resolves the name on its own network, which is not checked; a name that does not resolve
  here is then left to it. A proxy tool in fake-IP mode answers every name from
  198.18.0.0/15, which is not the internet's, so every fetch is refused and the refusal
  says why. The tests answer from a server on this machine, and say so with `local=True`;
  nothing else does.
* **No key, no address, no cookie of the user's travels.** The request carries a
  User-Agent naming the toolkit and nothing else of the person running it. A cookie a
  publisher sets on the way through its redirects is kept in memory for that run only, as a
  browser would keep it, since some publishers send the PDF only to a client that returns the
  cookie their first redirect set; it is never written anywhere.
* **A cap on the size,** checked against `Content-Length` before reading and against what is
  read: a server that sends more is cut off and nothing is kept.
* **A link that cannot be read as one,** `https://[x/a.pdf`, is no answer, and the caller
  goes on to the next place and the next work (round 1 of #565: `urlsplit` raised past it and
  stopped the run).
* **Nothing leaves the machine while `MANUSCRIPT_GUARD_NO_NETWORK` is set,** which the test
  suite sets, as `communicate` does: a test that forgot its own transport fails rather than
  reaching a publisher.

Nothing fetched is ever run: the bytes are only read, as a PDF's text or a page's tags, by
the caller.
"""

from __future__ import annotations

import http.client
import http.cookiejar
import ipaddress
import os
import re
import socket
import ssl
import urllib.error
import urllib.request
from dataclasses import dataclass
from urllib.parse import urljoin, urlsplit

from manuscript_guard import __version__
from manuscript_guard.lookup.http import NoAnswer, Request, Response, Transport

#: The largest file kept: a long article with its figures is rarely over 20 MB, and a server
#: that sends more than this is sending something else.
MAX_BYTES = 64 * 1024 * 1024
#: doi.org, then the publisher's own two or three, then its storage host: eight is more than
#: any chain seen, and a loop is cut off at it.
MAX_HOPS = 8
TIMEOUT_SECONDS = 60.0
REDIRECTS = frozenset({301, 302, 303, 307, 308})
#: Set, to anything, no request is sent: the test suite sets it.
NO_NETWORK = "MANUSCRIPT_GUARD_NO_NETWORK"
#: Who is asking, without saying who runs it: no e-mail address goes to any of these hosts.
AGENT = f"manuscript-guard/{__version__} (+https://github.com/BasileChretien/manuscript-guard)"
#: Names that are this computer whatever the resolver says.
_THIS_COMPUTER = frozenset({"localhost", "localhost.localdomain", "ip6-localhost"})
_REFUSED = "an address of this computer's own network, which no link is followed to"
#: A host that may be an IPv4 address written as a number: digits, hexadecimal and points
#: only, so that the resolver's reading of a number is never asked of a name.
_NUMERIC = re.compile(r"[0-9a-fA-FxX.]+")
#: A link's authority, as `urllib` takes it: what follows `//` up to the path, query or
#: fragment.
_AUTHORITY = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:(?://([^/?#]*))?")
#: What an authority may not hold: a percent escape, a user's name before `@`, a backslash.
#: `urllib` reads each otherwise than `urlsplit`, which the check reads: it decodes
#: `%31%32%37.0.0.1` to 127.0.0.1 and asks that, through a proxy `no_proxy` leaves it out
#: of, or of the proxy (review of #595).
_UNREAD = re.compile(r"[%@\\]")
#: What no link may hold anywhere: a space or a control character. `urlsplit` strips them
#: from its start, where the check of the authority looks for the scheme, and drops a tab or
#: a line break inside, where `urllib` keeps it, so the two would read another link (round 2
#: of the review of #595); `http.client` refuses them in a request in any case.
_UNSPACED = re.compile(r"[\s\x00-\x1f\x7f]")
#: 6to4, which carries an IPv4 address and which some Pythons count as global.
_SIX_TO_FOUR = ipaddress.ip_network("2002::/16")
#: Where a proxy tool in fake-IP mode (Clash, sing-box) answers every name from.
_FAKE_IP = ipaddress.ip_network("198.18.0.0/15")
_FAKE_IP_SAID = (" (198.18.0.0/15, which a proxy tool in fake-IP mode gives every name: leave "
                 "the publishers' hosts out of its fake-IP range, or use it as an https proxy)")


class Offline(NoAnswer):
    """No request may leave this machine: nothing else is worth asking either."""


@dataclass(frozen=True)
class Fetched:
    """What came back at the end of the redirects: where, its status, its type, its bytes."""

    url: str
    status: int
    content_type: str
    body: bytes


def _parts(url: str):
    """The URL's parts and its host, or None where it cannot be read as a URL, or where it or
    its authority holds what `urllib` reads otherwise than `urlsplit` (`_UNSPACED`,
    `_UNREAD`)."""
    if _UNSPACED.search(url):
        return None
    authority = _AUTHORITY.match(url)
    if authority and _UNREAD.search(authority.group(1) or ""):
        return None
    try:
        parts = urlsplit(url)
        return parts, parts.hostname, parts.port
    except ValueError:
        return None


def _address(host: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    """The IP address a host is, or None for a name. An IPv4 address may be written as one
    number, in hexadecimal or octal, or in fewer than four parts, and the resolver reads each
    as the address (round 2 of #565: `2130706433`, which is 127.0.0.1, was taken for a name).
    A stop after it, `127.0.0.1.`, is the resolver's root and is no part of the address."""
    host = host.split("%", 1)[0].rstrip(".")
    try:
        return ipaddress.ip_address(host)
    except ValueError:
        pass
    if not _NUMERIC.fullmatch(host):
        return None
    try:
        return ipaddress.IPv4Address(socket.inet_aton(host))
    except (OSError, ValueError):
        return None


def own_network(address: str) -> bool:
    """Whether an IP address, or a host written as one, is this computer's or its network's,
    not the internet's: anything Python does not count as global, a multicast or reserved
    address, or an IPv6 site-local one, which it counts as global (round 2 of #565: it let
    through 100.64.0.0/10, carrier-grade NAT and Tailscale's, and fec0::/10)."""
    ip = _address(address)
    if ip is None:
        return False
    if isinstance(ip, ipaddress.IPv6Address):
        if ip.ipv4_mapped is not None:
            ip = ip.ipv4_mapped
        elif ip.is_site_local or ip in _SIX_TO_FOUR:
            return True
    return any((not ip.is_global, ip.is_private, ip.is_loopback, ip.is_link_local,
                ip.is_multicast, ip.is_reserved, ip.is_unspecified))  # fmt: skip


def allowed(url: str, *, local: bool = False) -> bool:
    """Whether a URL may be asked: https, to a host that is neither this computer nor an
    address of its network. `local` lets a test ask a server on this machine, over http."""
    read = _parts(url)
    if read is None:
        return False
    parts, host, _port = read
    if not host:
        return False
    if local:
        return parts.scheme in ("https", "http")
    if parts.scheme != "https" or host.lower().rstrip(".") in _THIS_COMPUTER:
        return False
    return not own_network(host)


def why_refused(url: str) -> str:
    read = _parts(url)
    if read is None or not read[1]:
        return "a link that cannot be read as a URL"
    parts, host, _port = read
    if parts.scheme != "https":
        return f"a link to {parts.scheme}://{host}, which is not https"
    return f"a link to {host}, {_REFUSED}"


def header(response: Response, name: str) -> str:
    """A header of an answer, whatever case the server wrote its name in."""
    wanted = name.lower()
    return next((v for k, v in response.headers.items() if k.lower() == wanted), "")


def get(url: str, transport: Transport, *, accept: str = "*/*", local: bool = False) -> Fetched:
    """GET `url`, following each redirect while it stays on https and off this computer's
    network. Raises NoAnswer, with a reason that quotes no secret, where no answer came or a
    link was refused."""
    for _hop in range(MAX_HOPS + 1):
        if not allowed(url, local=local):
            raise NoAnswer(f"refused to follow {why_refused(url)}")
        response = transport(Request(url, headers={"User-Agent": AGENT, "Accept": accept}),
                             TIMEOUT_SECONDS)  # fmt: skip
        if response.status not in REDIRECTS:
            kind = header(response, "Content-Type").split(";")[0].strip().lower()
            return Fetched(url, response.status, kind, response.body)
        location = header(response, "Location").strip()
        host = (_parts(url) or (None, "?", None))[1]
        if not location:
            raise NoAnswer(f"{host} redirected without saying where")
        try:
            url = urljoin(url, location)
        except ValueError:
            raise NoAnswer(f"{host} redirected to a link that cannot be read as a URL") from None
    raise NoAnswer(f"redirected more than {MAX_HOPS} times")


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """`get` follows redirects itself, so that each hop is held to the rules."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ARG002
        return None


def session(*, local: bool = False) -> Transport:
    """A transport for one run: one GET at a time, a cookie jar kept in memory only."""
    jar = http.cookiejar.CookieJar()

    def send(request: Request, timeout: float) -> Response:
        return default_transport(request, timeout, jar, local=local)

    return send


def _proxied(netloc: str) -> bool:
    """Whether `urllib` asks the https proxy the environment names, as its own
    `ProxyHandler` decides: one is named, and `no_proxy` does not leave the link's host out,
    asked with its port as `urllib` asks it. Where the two still disagree, `_Pinned` makes
    the connection that `urllib` makes without the proxy."""
    return (bool(urllib.request.getproxies().get("https"))
            and not urllib.request.proxy_bypass(netloc))  # fmt: skip


def _resolves_outside(host: str, port: int | None, *, proxied: bool) -> tuple[str, ...]:
    """The addresses a name resolves to here, none of them this computer's or its network's;
    a name any of whose addresses is one is refused. Where the name does not resolve here and
    a proxy is to be asked, it is left to the proxy, as a university's resolves names this
    computer cannot: () then."""
    try:
        found = socket.getaddrinfo(host, port or 443, proto=socket.IPPROTO_TCP)
    except (socket.gaierror, UnicodeError, OSError):
        if proxied:
            return ()
        raise NoAnswer(f"no connection to {host}: the name does not resolve") from None
    addresses = tuple(dict.fromkeys(str(entry[4][0]) for entry in found))
    refused = [one for one in addresses if own_network(one)]
    if refused:
        fake = all(_address(one) in _FAKE_IP for one in refused)
        raise NoAnswer(f"refused to ask {host}, {_REFUSED}{_FAKE_IP_SAID if fake else ''}")
    if not addresses:
        raise NoAnswer(f"no connection to {host}: the name does not resolve")
    return addresses


def _connect(addresses: tuple[str, ...], address: tuple[str, int], timeout: float,
             source_address: tuple[str, int] | None = None) -> socket.socket:  # fmt: skip
    """`socket.create_connection` to each address checked in turn, at the port asked, and
    never to the name `address` gives, which would be resolved again."""
    failed: OSError | None = None
    for one in addresses:
        try:
            return socket.create_connection((one, address[1]), timeout, source_address)
        except OSError as exc:
            failed = exc
    raise failed or OSError("no address of the name was checked")


class _Pinned(urllib.request.HTTPSHandler):
    """https to the addresses `_resolves_outside` checked, not to what the name resolves to
    when the connection is made: a resolver that answered the check with an address of the
    internet and the connection with this computer's (DNS rebinding) reached this computer
    (round 1 of #565). The certificate is still held to the name, as `urllib` holds it.
    Through a proxy, the connection is the proxy's, which the environment names; with no
    address checked, a connection made without the proxy is made to nothing."""

    def __init__(self, addresses: tuple[str, ...]) -> None:
        self._ssl = ssl.create_default_context()
        self._ssl.set_alpn_protocols(["http/1.1"])
        super().__init__(context=self._ssl)
        self._addresses = addresses

    def https_open(self, req: urllib.request.Request):
        return self.do_open(self._connection, req, context=self._ssl)

    def _connection(self, host: str, **kwargs) -> http.client.HTTPSConnection:
        made = http.client.HTTPSConnection(host, **kwargs)
        addresses = self._addresses

        def connect(address: tuple[str, int], timeout: float,
                    source: tuple[str, int] | None = None) -> socket.socket:  # fmt: skip
            if made._tunnel_host:  # through the proxy: `address` is the proxy's
                return socket.create_connection(address, timeout, source)
            return _connect(addresses, address, timeout, source)

        made._create_connection = connect  # the hook http.client keeps for this
        return made


def default_transport(
    request: Request,
    timeout: float,
    jar: http.cookiejar.CookieJar | None = None,
    *,
    local: bool = False,
) -> Response:
    """Send one GET with `urllib`, no redirect followed, at most `MAX_BYTES` read. A status
    that is not 2xx is an answer, not an error. The proxy the environment names is used, as a
    university network's may be the way to its access; with none, the connection is made to
    the addresses the name was checked at."""
    if os.environ.get(NO_NETWORK, "").strip():
        raise Offline(f"{NO_NETWORK} is set, so no request leaves this machine")
    url = request.url
    if not allowed(url, local=local):
        raise NoAnswer(f"refused to ask {why_refused(url)}")
    parts, host, port = _parts(url)
    handlers: list = [_NoRedirect, urllib.request.HTTPCookieProcessor(jar)]
    if local:
        handlers.append(urllib.request.ProxyHandler({}))
    else:
        proxied = _proxied(parts.netloc)
        addresses = _resolves_outside(host, port, proxied=proxied)
        if not proxied:
            handlers.append(urllib.request.ProxyHandler({}))
        # Whatever `urllib` decides of the proxy, a connection it makes without one goes to
        # the addresses checked (review of #595: a `no_proxy` entry with a port left it out
        # where `_proxied`, asked without the port, did not, and nothing was pinned).
        handlers.append(_Pinned(addresses))
    opener = urllib.request.build_opener(*handlers)
    outgoing = urllib.request.Request(url, headers=dict(request.headers), method="GET")
    try:
        try:
            with opener.open(outgoing, timeout=timeout) as answer:
                return Response(answer.status, dict(answer.headers.items()), _read(answer))
        except urllib.error.HTTPError as exc:
            headers = dict(exc.headers.items()) if exc.headers else {}
            return Response(exc.code, headers, exc.read(1 << 20))
    except http.client.HTTPException as exc:
        raise NoAnswer(f"the answer from {host} could not be read ({type(exc).__name__})") from None
    except ValueError:
        raise NoAnswer("the request could not be made as written") from None
    except (urllib.error.URLError, OSError) as exc:
        reason = getattr(exc, "reason", exc)
        if isinstance(reason, TimeoutError) or "timed out" in str(reason):
            raise NoAnswer(f"no answer from {host} within {timeout:g} s") from None
        raise NoAnswer(f"no connection to {host}") from None


def _read(answer) -> bytes:
    """The body, refused where it says or turns out to be larger than `MAX_BYTES`, or where it
    stops short of what it said it was."""
    declared = answer.headers.get("Content-Length", "")
    if declared.isdigit() and int(declared) > MAX_BYTES:
        raise NoAnswer(f"the file is {int(declared) >> 20} MB, over the {MAX_BYTES >> 20} MB "
                       "kept")  # fmt: skip
    body = answer.read(MAX_BYTES + 1)
    if len(body) > MAX_BYTES:
        raise NoAnswer(f"the file is over the {MAX_BYTES >> 20} MB kept")
    if declared.isdigit() and len(body) < int(declared):
        raise NoAnswer("the answer was cut off part way")
    return body


__all__ = [
    "AGENT",
    "MAX_BYTES",
    "MAX_HOPS",
    "NO_NETWORK",
    "Fetched",
    "Offline",
    "allowed",
    "default_transport",
    "get",
    "header",
    "own_network",
    "session",
    "why_refused",
]
