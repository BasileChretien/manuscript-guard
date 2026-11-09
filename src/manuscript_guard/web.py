"""What the in-browser audit page needs from the package, and what nothing else uses.

The page (`web/` in the repository) runs `audit` in Pyodide, in a Web Worker, under a
Content-Security-Policy that lets it reach only the registries `--lookup` asks. It has no
program to start and no sockets, so:

* `runner_for` makes `from_word.runner` out of pandoc.wasm's `convert`, which takes a
  defaults-file object rather than a command line. The flags `from_word` passes are
  translated (`pandoc_options`), and any other flag is refused rather than dropped, so that
  the page never converts a paper otherwise than the command line does without saying so.
* `xhr_transport` is `lookup.http.default_transport` in a page: one synchronous
  XMLHttpRequest, which a worker may make. `default_transport` hands over to it under Pyodide.
* `run` runs one command and returns what it printed, for the page to show.

Nothing here starts a process or opens a socket, and only `install` and the transport's
default touch `js`, which exists only in Pyodide.
"""

from __future__ import annotations

import contextlib
import io
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

from manuscript_guard.contracts._schema import ContractError
from manuscript_guard.lookup.http import MAX_BYTES, NoAnswer, Request, Response

#: The headers a page may not set (the Fetch standard's forbidden names that a request here
#: carries): the browser sends its own, and setting one only logs a refusal.
FORBIDDEN = frozenset({"user-agent", "accept-encoding", "connection", "host", "referer"})

#: pandoc.wasm's `convert`, as Python sees it: the options, the standard input and the input
#: files by name, to what pandoc printed, what it said on stderr, and each file it wrote.
Convert = Callable[[dict, str | None, Mapping[str, bytes]], tuple[str, str, Mapping[str, bytes]]]
Runner = Callable[[list[str], str | None, Path], str]


@dataclass(frozen=True)
class PandocCall:
    """One run of pandoc as pandoc.wasm takes it."""

    options: dict = field(default_factory=dict)
    #: The file pandoc reads, where it reads one rather than its standard input.
    source: Path | None = None
    #: Where `--extract-media` asked for the pictures to be saved.
    media: Path | None = None


def pandoc_options(arguments: list[str]) -> PandocCall:
    """`from_word`'s command line for pandoc as a defaults-file object. Raises ContractError on
    a flag it does not translate."""
    options: dict = {}
    source = media = None
    given = iter(arguments)
    for argument in given:
        if argument in ("-f", "-t"):
            value = next(given, None)
            if value is None:
                raise ContractError(f"pandoc.wasm: {argument} names no format")
            options["from" if argument == "-f" else "to"] = value
        elif argument.startswith("--wrap="):
            options["wrap"] = argument.split("=", 1)[1]
        elif argument.startswith("--columns="):
            options["columns"] = int(argument.split("=", 1)[1])
        elif argument.startswith("--extract-media="):
            # The folder's own path, which pandoc writes into each image's path in the tree,
            # and `from_word` then reads back: any other would change the text converted.
            media = Path(argument.split("=", 1)[1])
            options["extract-media"] = media.as_posix()
        elif argument.startswith("-"):
            raise ContractError(f"pandoc.wasm: the flag {argument} is not translated, so the "
                                "paper was not converted")  # fmt: skip
        elif source is not None:
            raise ContractError("pandoc.wasm: more than one input file")
        else:
            source = Path(argument)
            options["input-files"] = ["input" + source.suffix.lower()]
    return PandocCall(options, source, media)


def runner_for(convert: Convert) -> Runner:
    """A `from_word.runner` that runs pandoc through `convert`."""

    def run_pandoc(arguments: list[str], given: str | None, path: Path) -> str:
        call = pandoc_options(arguments)
        files = {} if call.source is None else {
            call.options["input-files"][0]: call.source.read_bytes()}  # fmt: skip
        try:
            stdout, stderr, made = convert(call.options, given, files)
        except Exception as exc:  # noqa: BLE001 - a trap or an exit in the wasm, said as pandoc's
            raise ContractError(f"pandoc.wasm could not convert {path.name}, so nothing was "
                                f"made ({type(exc).__name__})") from None  # fmt: skip
        if not stdout and stderr.strip():
            raise ContractError(f"pandoc could not convert {path.name}, so nothing was made: "
                                f"{stderr.strip()}")  # fmt: skip
        if call.media is not None:
            _save_media(made, call.media)
        return stdout

    return run_pandoc


def _save_media(made: Mapping[str, bytes], folder: Path) -> None:
    """Each picture pandoc.wasm extracted into `folder` in its own file system, saved at the
    same place in this one, as pandoc saves them where `--extract-media` says. pandoc.wasm's
    file system has `/` as its root, so it names a file below `/tmp/x` `tmp/x/...`. A name
    that would leave `folder` is not saved."""
    root = folder.resolve()
    prefix = folder.as_posix().lstrip("/") + "/"
    for name, data in made.items():
        if not name.startswith(prefix):
            continue
        target = (root / name[len(prefix):]).resolve()
        if not target.is_relative_to(root):
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(bytes(data))


def _js_convert(pandoc_js) -> Convert:
    """`Convert` over the page's pandoc.wasm, whose `convertSync` takes and returns JS values."""
    import js
    from pyodide.ffi import to_js

    def as_js(data: bytes):
        array = js.Uint8Array.new(len(data))
        array.assign(data)
        return array

    def convert(options: dict, stdin: str | None, files: Mapping[str, bytes]):
        result = pandoc_js.convertSync(
            to_js(options, dict_converter=js.Object.fromEntries), stdin,
            to_js({name: as_js(data) for name, data in files.items()},
                  dict_converter=js.Object.fromEntries),
        )  # fmt: skip
        made = {str(name): data.to_bytes() for name, data in js.Object.entries(result.files)}
        return str(result.stdout), str(result.stderr), made

    return convert


def install(pandoc_js) -> str:
    """Run `from_word`'s pandoc through the page's pandoc.wasm; its version."""
    from manuscript_guard import from_word

    from_word.runner = runner_for(_js_convert(pandoc_js))
    return str(pandoc_js.version)


def _new_xhr():
    import js

    return js.XMLHttpRequest.new()


def _title(name: str) -> str:
    """A header's name as `urllib` gives it, which the readers ask for (`Retry-After`): a
    browser gives every name in lower case."""
    return "-".join(word.capitalize() for word in name.split("-"))


def xhr_transport(request: Request, timeout: float, new_xhr: Callable | None = None) -> Response:
    """One GET as one synchronous XMLHttpRequest. As `default_transport`: a status that is
    not 2xx is an answer, and no message quotes the URL sent.

    Where a page differs: it cannot set the User-Agent, which is left out; the browser follows
    a redirect itself, to a host the page's policy allows or not at all; and a request the
    browser refuses, for CORS or for the policy, comes back as status 0, said as no answer."""
    parts = urlsplit(request.base)
    if parts.scheme != "https":
        raise NoAnswer(f"refused to send a request to {parts.scheme}://{parts.hostname}")
    xhr = (new_xhr or _new_xhr)()
    xhr.open("GET", request.url, False)
    xhr.timeout = int(timeout * 1000)
    for name, value in request.headers.items():
        if name.lower() not in FORBIDDEN:
            xhr.setRequestHeader(name, value)
    try:
        xhr.send()
    except Exception as exc:  # noqa: BLE001 - the browser's error, said without the URL
        if "timeout" in f"{type(exc).__name__} {exc}".lower():
            raise NoAnswer(f"no answer within {timeout:g} s") from None
        raise NoAnswer(f"no connection to {parts.hostname}") from None
    if not xhr.status:
        raise NoAnswer(f"no connection to {parts.hostname}")
    headers = {}
    for line in str(xhr.getAllResponseHeaders()).splitlines():
        name, colon, value = line.partition(":")
        if colon and name.strip():
            headers[_title(name.strip())] = value.strip()
    body = str(xhr.responseText).encode("utf-8")[: MAX_BYTES + 1]
    return Response(int(xhr.status), headers, body)


def run(arguments: list[str]) -> dict:
    """One command, as the command line runs it: its exit code, and what it printed."""
    from manuscript_guard.cli import main

    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            code = main(list(arguments))
        except SystemExit as exc:
            code = 0 if exc.code is None else exc.code if isinstance(exc.code, int) else 1
    return {"code": code, "out": out.getvalue(), "err": err.getvalue()}


def view(arguments: list[str]) -> dict:
    """`run`, and for an audit the report as the page draws it (`auditing.report.view`),
    taken from the very audit whose text `run` returns (`cli.AUDITED`), every section with
    `--details`: None for any other command, an audit that printed no report, or one asked
    for as JSON. A view that could not be drawn is None too, its failure recorded as a crash
    is, and the text is still returned: the page shows the text where it cannot draw. Under
    MANUSCRIPT_GUARD_DEBUG the failure is raised, as `cli.main` raises it."""
    from manuscript_guard import cli
    from manuscript_guard.auditing.report import view as drawn
    from manuscript_guard.diagnostics import crashes

    made: list[dict] = []
    details = "--details" in arguments

    def told(report, discrimination) -> None:
        try:
            made.append(drawn(report, discrimination, Path.cwd(), details=details))
        except Exception as exc:  # noqa: BLE001 - the text is printed whatever the view does
            if crashes.debugging():
                raise
            crashes.record(exc, kind=crashes.GATE, name="the page's view of the report")

    cli.AUDITED = told
    try:
        result = run(arguments)
    finally:
        cli.AUDITED = None
    shown = made[-1] if made and "--json" not in arguments else None
    return {**result, "view": shown}


__all__ = ["PandocCall", "install", "pandoc_options", "run", "runner_for", "view",
           "xhr_transport"]  # fmt: skip
