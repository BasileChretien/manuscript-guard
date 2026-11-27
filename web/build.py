"""Build the site: the landing page at its root, and the in-browser audit page under audit/.

    cd web && npm ci && cd ..
    pip wheel . --no-deps --wheel-dir dist
    python web/build.py --wheel dist/manuscript_guard-<version>-py3-none-any.whl --out _site

    python web/build.py --landing --out _site    # the landing page alone, to look at it

    python web/build.py --wheel <the wheel> --host <folder> --out check   # a journal's own

The landing page (web/landing/) is static: its HTML, its style, and each picture it names as
img/<path>, copied from docs/img/<path>, so that the drawings have one home.

With `--host`, the audit page alone is built in `--out`, for a publisher or a society to
serve on its own site (docs/hosting-the-audit-page.md): its journals' profiles, which the
page offers to hold a paper to, and its name, logo, colours and contact line, all read from
the folder named (`read_host`) and refused, before anything is built, where any is wrong.
They go in as data: the page's code is byte for byte the code of the page built without them,
so that anyone can compare a host's page with the release's.

What the audit page loads is all here, so that its Content-Security-Policy can name no host but
its own and the registries: Pyodide's runtime (from npm, held by package-lock.json), the
Python packages `audit` imports (from Pyodide's own release, each held to the SHA-256 its
pyodide-lock.json gives), pandoc.wasm (from the pandoc release CI pins, held to pins.json),
the shim that runs it, bundled, and the wheel given. Each licence goes beside them, and
`files.sha256` lists every file with its hash, which the page links to.

Downloads are kept in web/.cache and checked again each time they are read. Nothing here
runs on the reader's computer: this is the maintainer's build, and CI's.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import re
import shutil
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path

WEB = Path(__file__).resolve().parent
PAGE = ("index.html", "style.css", "app.js", "worker.js", "probe.js", "example-paper.md")
PYODIDE_CORE = ("pyodide.mjs", "pyodide.asm.mjs", "pyodide.asm.wasm", "python_stdlib.zip",
                "pyodide-lock.json")  # fmt: skip
#: Pyodide's files the worker imports as modules rather than fetches: the bar that counts
#: what the worker fetches while it starts leaves them out (manifest `bytes`).
IMPORTED = ("pyodide.mjs", "pyodide.asm.mjs")
SHIM_LICENCES = ("LICENSE-MIT", "LICENSE-APACHE")
LANDING = WEB / "landing"
LANDING_PAGE = ("index.html", "style.css")
#: The folder of the site the audit page is built in.
AUDIT = "audit"
IMAGES = WEB.parent / "docs" / "img"
#: Where the site is served. The landing page names its social preview there, since a card
#: is drawn by a site that reads the page, from an address it can fetch alone.
SITE = "https://basilechretien.github.io/manuscript-guard/"
#: The landing page's own files, the video and its parts, which it names as media/<name>.
MEDIA = LANDING / "media"
OWN = re.compile(r'(?:src|poster)="media/([^"\s]+)"')
#: A picture the landing page names: img/<its path under docs/img>.
PICTURE = re.compile(rf'(?:src|srcset|href|poster|content)="(?:{re.escape(SITE)})?img/([^"\s]+)"')


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def fetched(url: str, digest: str, cache: Path) -> bytes:
    """The file at `url`, from the cache where it is there, refused unless its SHA-256 is
    `digest`."""
    kept = cache / digest
    if kept.is_file():
        data = kept.read_bytes()
    else:
        with urllib.request.urlopen(url, timeout=300) as answer:  # noqa: S310 - pinned https
            data = answer.read()
    if sha256(data) != digest:
        raise SystemExit(f"{url}: SHA-256 {sha256(data)}, pinned {digest}; nothing was built")
    cache.mkdir(parents=True, exist_ok=True)
    kept.write_bytes(data)
    return data


def needed(lock: dict, names: list[str]) -> list[str]:
    """`names` and every package they depend on, by Pyodide's lock file."""
    packages, wanted, found = lock["packages"], list(names), []
    while wanted:
        name = wanted.pop().lower().replace("_", "-")
        if name not in found:
            found.append(name)
            wanted += packages[name]["depends"]
    return sorted(found)


def pictures(page: str) -> list[str]:
    """The pictures `page` names, each a path under docs/img."""
    return sorted(set(PICTURE.findall(page)))


def landing(out: Path) -> list[str]:
    """Put the landing page in `out`, with each picture it names and each file of its own
    (media/); return the pictures. Every file is found before anything is copied."""
    text = (LANDING / "index.html").read_text(encoding="utf-8")
    shown, own = pictures(text), sorted(set(OWN.findall(text)))
    found = ((IMAGES, shown, "img", "docs/img"), (MEDIA, own, "media", "web/landing/media"))
    for folder, names, where, home in found:
        for name in names:
            source = (folder / name).resolve()
            if not source.is_relative_to(folder.resolve()) or not source.is_file():
                raise SystemExit(f"web/landing/index.html shows {where}/{name}, which is not a "
                                 f"file in {home}; nothing was built")  # fmt: skip
    out.mkdir(parents=True, exist_ok=True)
    for name in LANDING_PAGE:
        shutil.copyfile(LANDING / name, out / name)
    for folder, names, where, _ in found:
        for name in names:
            (out / where / name).parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(folder / name, out / where / name)
    return shown


#: What a host folder's host.yaml is (docs/hosting-the-audit-page.md), and what it may hold.
HOST_SCHEMA = "manuscript-guard/host/1"
HOST_KEYS = ("schema", "name", "logo", "accent", "contact")
#: A journal's slug, its profile's file name and what `?journal=` names it by.
SLUG = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,62}[a-z0-9])?")
#: The value of "Another journal" in the page's list (index.html), which no slug may be.
ANOTHER = "other"
#: What a computer leaves beside the profiles, passed over as hidden files and folders are:
#: Windows' pictures' cache and a folder's settings (macOS's .DS_Store is a hidden file).
LEFT_BESIDE = ("thumbs.db", "desktop.ini")
#: A logo the page shows beside the host's name, by its extension, with how its file starts.
LOGOS = {".svg": None, ".png": (b"\x89PNG\r\n\x1a\n",), ".webp": (b"RIFF",)}
LOGO_MAX_BYTES = 512 * 1024
NAME_MAX, CONTACT_MAX, LINK_MAX = 80, 160, 300
HEX = re.compile(r"#[0-9a-fA-F]{6}")
#: The page's own colours an accent is read against (web/style.css), light and dark: the
#: paper, the cards, and the text a button writes on the accent. Each must be 4.5:1 or more,
#: the contrast WCAG asks of text.
AROUND = {"light": ("#f6f4ee", "#fffdf8", "#ffffff"), "dark": ("#0f1728", "#16213a", "#0f1728")}
LEAST_CONTRAST = 4.5
#: How much of the accent the soft tint of the drop box and the loading bar's box takes,
#: mixed into the card.
SOFT_SHARE = 0.15
EMAIL = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")
CONTROL = re.compile(r"[\x00-\x1f\x7f]")


class HostError(ValueError):
    """What is wrong with a host folder: the message says which file and why."""


def luminance(colour: str) -> float:
    """The relative luminance of a colour written #rrggbb, as WCAG 2 reckons it."""
    def channel(value: int) -> float:
        share = value / 255
        return share / 12.92 if share <= 0.04045 else ((share + 0.055) / 1.055) ** 2.4

    red, green, blue = (channel(int(colour[at:at + 2], 16)) for at in (1, 3, 5))
    return 0.2126 * red + 0.7152 * green + 0.0722 * blue


def contrast(one: str, other: str) -> float:
    """The contrast ratio of two colours, from 1 to 21, as WCAG 2 reckons it."""
    lighter, darker = sorted((luminance(one), luminance(other)), reverse=True)
    return (lighter + 0.05) / (darker + 0.05)


def mixed(colour: str, into: str, share: float) -> str:
    """`share` of `colour` mixed into `into`, both #rrggbb."""
    return "#" + "".join(
        f"{round(int(colour[at:at + 2], 16) * share + int(into[at:at + 2], 16) * (1 - share)):02x}"
        for at in (1, 3, 5))


def _text(value: object, what: str, most: int) -> str:
    """`value` as one line of plain text, of at most `most` characters, or why not."""
    if not isinstance(value, str) or not value.strip():
        raise HostError(f"{what} must be text")
    if CONTROL.search(value) or len(value.strip()) > most:
        raise HostError(f"{what} must be one line of at most {most} characters")
    return value.strip()


def _logo(folder: Path, given: object) -> Path:
    """The logo file host.yaml names, in the host folder, or why it cannot be shown."""
    if not isinstance(given, str) or not given.strip():
        raise HostError("host.yaml: logo must name a file in the host folder")
    path = (folder / given).resolve()
    if not path.is_relative_to(folder.resolve()) or not path.is_file():
        raise HostError(f"host.yaml: logo {given} is not a file in the host folder")
    if path.suffix.lower() not in LOGOS:
        raise HostError(f"host.yaml: logo {given} is not an .svg, a .png or a .webp")
    data = path.read_bytes()
    if len(data) > LOGO_MAX_BYTES:
        raise HostError(f"host.yaml: logo {given} is over {LOGO_MAX_BYTES // 1024} KB")
    starts = LOGOS[path.suffix.lower()]
    shaped = (b"<svg" in data[:4096] if starts is None else data.startswith(starts[0])
              and (path.suffix.lower() != ".webp" or data[8:12] == b"WEBP"))  # fmt: skip
    if not shaped:
        raise HostError(f"host.yaml: logo {given} is not the picture its extension says")
    return path


def _accent(given: object) -> dict[str, str]:
    """The accent host.yaml gives, light and dark, each held to the page's own colours."""
    if not isinstance(given, dict) or set(given) != {"light", "dark"}:
        raise HostError("host.yaml: accent must give `light` and `dark`, each #rrggbb")
    accent = {}
    for scheme in ("light", "dark"):
        colour = given[scheme]
        if not isinstance(colour, str) or not HEX.fullmatch(colour):
            raise HostError(f"host.yaml: accent {scheme} must be written #rrggbb")
        least = min(contrast(colour, other) for other in AROUND[scheme])
        if least < LEAST_CONTRAST:
            raise HostError(f"host.yaml: accent {scheme} {colour} has a contrast of "
                            f"{least:.2f}:1 with the page's {scheme} colours, under "
                            f"{LEAST_CONTRAST}:1")  # fmt: skip
        accent[scheme] = colour.lower()
    return accent


def _contact(given: object) -> dict[str, str]:
    """The host's contact line, its text and its one link, mailto: or https:."""
    if not isinstance(given, dict) or set(given) != {"text", "link"}:
        raise HostError("host.yaml: contact must give `text` and `link`")
    text = _text(given["text"], "host.yaml: contact text", CONTACT_MAX)
    link = given["link"]
    if not isinstance(link, str) or len(link) > LINK_MAX or re.search(r"[\s\x00-\x1f\x7f]", link):
        raise HostError(f"host.yaml: contact link must be one address of at most {LINK_MAX} "
                        "characters")  # fmt: skip
    from urllib.parse import urlsplit

    parts = urlsplit(link)
    if parts.scheme == "mailto" and EMAIL.fullmatch(parts.path) and not parts.query:
        shown = parts.path
    elif parts.scheme == "https" and parts.hostname:
        shown = link
    else:
        raise HostError(f"host.yaml: contact link {link} is neither mailto:<address> nor "
                        "https://")  # fmt: skip
    return {"text": text, "link": link, "shown": shown}


def _journals(folder: Path) -> list[dict]:
    """The journals the host folder's journals/ holds, each profile held to the journal
    schema by the package the page runs (`auditing.journal.read_profile`), sorted by name."""
    from manuscript_guard.auditing.journal import read_profile

    where = folder / "journals"
    if not where.is_dir():
        return []
    journals = []
    for path in sorted(where.iterdir()):
        if path.is_dir() or path.name.startswith(".") or path.name.lower() in LEFT_BESIDE:
            continue
        if not path.is_file() or path.suffix != ".yaml" or not SLUG.fullmatch(path.stem):
            raise HostError(f"journals/{path.name}: each journal is a file journals/<slug>.yaml, "
                            "the slug in lower-case letters, digits and hyphens")  # fmt: skip
        if path.stem == ANOTHER:
            raise HostError(f"journals/{path.name}: {ANOTHER} is what the page's list calls "
                            "another journal, whose rules the reader types: name it otherwise")
        profile, errors = read_profile(path)
        if errors:
            raise HostError(f"journals/{path.name} is not a journal profile: "
                            + "; ".join(errors))  # fmt: skip
        journals.append({"slug": path.stem, "name": _text(profile.get("name"), f"journals/"
                         f"{path.name}: its name", NAME_MAX), "file": f"journals/{path.name}",
                         "blinding": profile.get("blinding") or "", "path": path})  # fmt: skip
    names = [journal["name"].casefold() for journal in journals]
    twice = next((journal for journal in journals
                  if names.count(journal["name"].casefold()) > 1), None)  # fmt: skip
    if twice:
        raise HostError(f"two profiles are named {twice['name']}: the page could not tell "
                        "their journals apart")  # fmt: skip
    return sorted(journals, key=lambda journal: journal["name"].casefold())


def read_host(folder: Path) -> dict:
    """What a host folder gives the page: host.yaml's name, logo, accent and contact, and
    the journals of journals/<slug>.yaml. Refused, with which file and why, where anything is
    not as docs/hosting-the-audit-page.md says."""
    import yaml

    if not (folder / "host.yaml").is_file():
        raise HostError(f"{folder} has no host.yaml")
    try:
        given = yaml.safe_load((folder / "host.yaml").read_text(encoding="utf-8"))
    except (UnicodeDecodeError, yaml.YAMLError) as exc:
        raise HostError(f"host.yaml cannot be read: {exc}") from exc
    if not isinstance(given, dict) or given.get("schema") != HOST_SCHEMA:
        raise HostError(f"host.yaml must start `schema: {HOST_SCHEMA}`")
    unknown = sorted(set(map(str, given)) - set(HOST_KEYS))
    if unknown:
        raise HostError(f"host.yaml: {', '.join(unknown)} is not a key a host may set "
                        f"(only {', '.join(HOST_KEYS[1:])})")  # fmt: skip
    return {
        "name": _text(given.get("name"), "host.yaml: name", NAME_MAX),
        "logo": _logo(folder, given["logo"]) if "logo" in given else None,
        "accent": _accent(given["accent"]) if "accent" in given else None,
        "contact": _contact(given["contact"]) if "contact" in given else None,
        "journals": _journals(folder),
    }


def host_css(accent: dict[str, str]) -> str:
    """The style sheet of a host's accent: the page's teal, and its soft tint, in light and
    dark (web/style.css), from colours `_accent` held to the page's own."""
    soft = {scheme: mixed(accent[scheme], AROUND[scheme][1], SOFT_SHARE)
            for scheme in ("light", "dark")}  # fmt: skip
    return ("/* The host's accent (host.yaml), checked for contrast by web/build.py. */\n"
            f":root {{ --teal: {accent['light']}; --teal-soft: {soft['light']}; }}\n"
            "@media (prefers-color-scheme: dark) {\n"
            f"  :root {{ --teal: {accent['dark']}; --teal-soft: {soft['dark']}; }}\n}}\n")


def hosted(host: dict, out: Path) -> dict:
    """Put the host's files in the page's folder `out`: each journal's profile as it is, the
    logo, and the accent's style sheet; return what manifest.json says of the host."""
    (out / "journals").mkdir()
    for journal in host["journals"]:
        shutil.copyfile(journal["path"], out / journal["file"])
    said = {"name": host["name"], "logo": None, "style": None, "contact": host["contact"],
            "journals": [{key: journal[key] for key in ("slug", "name", "file", "blinding")}
                         for journal in host["journals"]]}  # fmt: skip
    if host["logo"] or host["accent"]:
        (out / "host").mkdir()
    if host["logo"]:
        said["logo"] = f"host/logo{host['logo'].suffix.lower()}"
        shutil.copyfile(host["logo"], out / said["logo"])
    if host["accent"]:
        said["style"] = "host/host.css"
        (out / said["style"]).write_text(host_css(host["accent"]), encoding="utf-8",
                                         newline="\n")  # fmt: skip
    return said


def build(wheel: Path, site: Path, cache: Path, host: dict | None = None) -> dict:
    """Build the landing page in `site` and the audit page in its folder AUDIT; or for a
    host (`read_host`), the audit page alone, in `site` itself, with the host's files."""
    if site.exists():
        shutil.rmtree(site)
    if host is None:
        landing(site)
    out = site / AUDIT if host is None else site
    pins = json.loads((WEB / "pins.json").read_text(encoding="utf-8"))
    modules = WEB / "node_modules"
    if not (modules / "pyodide").is_dir():
        raise SystemExit("web/node_modules is missing: run `npm ci` in web/ first")
    pyodide = json.loads((modules / "pyodide" / "package.json").read_text("utf-8"))["version"]
    out.mkdir(parents=True, exist_ok=True)
    (out / "pyodide").mkdir()
    (out / "pandoc").mkdir()
    (out / "wheels").mkdir()
    (out / "licences").mkdir()

    for name in PAGE:
        shutil.copyfile(WEB / name, out / name)
    for name in PYODIDE_CORE:
        shutil.copyfile(modules / "pyodide" / name, out / "pyodide" / name)
    lock = json.loads((out / "pyodide" / "pyodide-lock.json").read_text(encoding="utf-8"))
    packages = pins["pyodide"]["packages"].format(version=pyodide)
    for name in needed(lock, pins["pyodide"]["load"]):
        entry = lock["packages"][name]
        data = fetched(packages + entry["file_name"], entry["sha256"], cache)
        (out / "pyodide" / entry["file_name"]).write_bytes(data)

    pandoc = pins["pandoc"]
    with zipfile.ZipFile(io.BytesIO(fetched(pandoc["wasm"]["url"], pandoc["wasm"]["sha256"],
                                             cache))) as archive:  # fmt: skip
        (out / "pandoc" / "pandoc.wasm").write_bytes(archive.read("pandoc.wasm"))
    esbuild = modules / ".bin" / ("esbuild.cmd" if sys.platform == "win32" else "esbuild")
    subprocess.run([str(esbuild), str(WEB / "pandoc.mjs"), "--bundle", "--format=esm",
                    "--minify", "--legal-comments=eof",
                    f"--outfile={out / 'pandoc' / 'pandoc.mjs'}"],
                   check=True, timeout=300, cwd=WEB)  # fmt: skip

    shutil.copyfile(wheel, out / "wheels" / wheel.name)
    version = wheel.name.split("-")[1]

    licences = out / "licences"
    shutil.copyfile(WEB.parent / "LICENSE", licences / "manuscript-guard-MIT.txt")
    (licences / "pandoc-GPL-2.0.txt").write_bytes(
        fetched(pandoc["licence"]["url"], pandoc["licence"]["sha256"], cache))
    (licences / "pyodide-MPL-2.0.txt").write_bytes(fetched(
        pins["pyodide"]["licence"]["url"].format(version=pyodide),
        pins["pyodide"]["licence"]["sha256"], cache))  # fmt: skip
    for name in SHIM_LICENCES:
        shutil.copyfile(modules / "@bjorn3" / "browser_wasi_shim" / name,
                        licences / f"browser_wasi_shim-{name}.txt")  # fmt: skip

    # What the worker fetches while it starts, for the page's bar: Pyodide's files but those
    # it imports, the packages it loads, the wheel and pandoc.wasm (worker.js `counted`).
    fetching = [*(path for path in (out / "pyodide").iterdir() if path.name not in IMPORTED),
                out / "wheels" / wheel.name, out / "pandoc" / "pandoc.wasm"]  # fmt: skip
    manifest = {
        "manuscript_guard": version,
        "wheel": f"wheels/{wheel.name}",
        "pyodide": pyodide,
        "load": pins["pyodide"]["load"],
        "bytes": sum(path.stat().st_size for path in fetching),
        "pandoc": pandoc["version"],
        "sources": {
            "manuscript-guard":
                f"https://github.com/BasileChretien/manuscript-guard/tree/v{version}",
            "pandoc": pandoc["source"],
            "pyodide": pins["pyodide"]["source"].format(version=pyodide),
        },
    }
    if host is not None:
        manifest["host"] = hosted(host, out)
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    listed = sorted(p for p in out.rglob("*") if p.is_file())
    (out / "files.sha256").write_text(
        "".join(f"{sha256(p.read_bytes())}  {p.relative_to(out).as_posix()}\n" for p in listed),
        encoding="utf-8", newline="\n")  # fmt: skip
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--wheel", type=Path, help="the manuscript-guard wheel")
    parser.add_argument("--landing", action="store_true",
                        help="build the landing page alone, with no audit page")  # fmt: skip
    parser.add_argument("--host", type=Path,
                        help="a host folder (host.yaml, journals/): build the audit page alone, "
                             "with its journals and its name")  # fmt: skip
    parser.add_argument("--out", type=Path, required=True,
                        help="the folder to build the site in, emptied first")  # fmt: skip
    parser.add_argument("--cache", type=Path, default=WEB / ".cache",
                        help="where downloads are kept (default web/.cache)")  # fmt: skip
    args = parser.parse_args(argv)
    if args.landing and args.host:
        parser.error("--landing builds the project's landing page, which a host's has not")
    if args.landing:
        if args.out.exists():
            shutil.rmtree(args.out)
        shown = landing(args.out)
        print(f"built {args.out}: the landing page and {len(shown)} pictures, no audit page")
        return 0
    if args.wheel is None:
        parser.error("--wheel is required, unless --landing")
    if not args.wheel.is_file() or not args.wheel.name.startswith("manuscript_guard-"):
        parser.error(f"--wheel {args.wheel}: not a manuscript-guard wheel")
    host = None
    if args.host:
        # `--out` is emptied first: never the host folder, one that holds it, or one in it.
        out, given = args.out.resolve(), args.host.resolve()
        if out == given or out.is_relative_to(given) or given.is_relative_to(out):
            parser.error(f"--out {args.out} is the host folder, holds it or is in it, and is "
                         "emptied first: build the page outside the host folder")
        host = host_for(args.host, args.wheel.name.split("-")[1])
        if isinstance(host, str):
            print(host, file=sys.stderr)
            return 1
    # Absolute, since esbuild runs in web/: a relative --out put the bundle in web/_site.
    args.out, args.cache = args.out.resolve(), args.cache.resolve()
    manifest = build(args.wheel.resolve(), args.out, args.cache, host)
    size = sum(p.stat().st_size for p in args.out.rglob("*") if p.is_file())
    print(f"built {args.out} ({size / 1e6:.1f} MB): manuscript-guard "
          f"{manifest['manuscript_guard']}, Pyodide {manifest['pyodide']}, "
          f"pandoc {manifest['pandoc']}"
          + (f"; the audit page alone, for {host['name']}, with {len(host['journals'])} "
             "journals" if host else ""))  # fmt: skip
    return 0


def host_for(folder: Path, version: str) -> dict | str:
    """The host folder read (`read_host`), by the manuscript-guard the wheel is, which holds
    each profile to its schema as the page will; or why nothing is built."""
    try:
        from manuscript_guard import __version__
    except ImportError:
        return ("--host: manuscript-guard is not installed here, and it holds each journal's "
                f"profile to its schema: pip install manuscript-guard=={version}")
    if __version__ != version:
        return (f"--host: manuscript-guard {__version__} is installed here and the wheel is "
                f"{version}: the profiles would be held to another release's schema than the "
                f"page's. pip install manuscript-guard=={version}")
    try:
        return read_host(folder.resolve())
    except HostError as exc:
        return f"--host {folder}: {exc}; nothing was built"


if __name__ == "__main__":
    sys.exit(main())
