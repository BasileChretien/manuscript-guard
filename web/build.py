"""Build the in-browser audit page: every file it loads, in one folder, served from one origin.

    cd web && npm ci && cd ..
    pip wheel . --no-deps --wheel-dir dist
    python web/build.py --wheel dist/manuscript_guard-<version>-py3-none-any.whl --out _site

What the page loads is all here, so that its Content-Security-Policy can name no host but
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
import shutil
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path

WEB = Path(__file__).resolve().parent
PAGE = ("index.html", "style.css", "app.js", "worker.js", "probe.js")
PYODIDE_CORE = ("pyodide.mjs", "pyodide.asm.mjs", "pyodide.asm.wasm", "python_stdlib.zip",
                "pyodide-lock.json")  # fmt: skip
SHIM_LICENCES = ("LICENSE-MIT", "LICENSE-APACHE")


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


def build(wheel: Path, out: Path, cache: Path) -> dict:
    pins = json.loads((WEB / "pins.json").read_text(encoding="utf-8"))
    modules = WEB / "node_modules"
    if not (modules / "pyodide").is_dir():
        raise SystemExit("web/node_modules is missing: run `npm ci` in web/ first")
    pyodide = json.loads((modules / "pyodide" / "package.json").read_text("utf-8"))["version"]
    if out.exists():
        shutil.rmtree(out)
    (out / "pyodide").mkdir(parents=True)
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

    manifest = {
        "manuscript_guard": version,
        "wheel": f"wheels/{wheel.name}",
        "pyodide": pyodide,
        "load": pins["pyodide"]["load"],
        "pandoc": pandoc["version"],
        "sources": {
            "manuscript-guard":
                f"https://github.com/BasileChretien/manuscript-guard/tree/v{version}",
            "pandoc": pandoc["source"],
            "pyodide": pins["pyodide"]["source"].format(version=pyodide),
        },
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    listed = sorted(p for p in out.rglob("*") if p.is_file())
    (out / "files.sha256").write_text(
        "".join(f"{sha256(p.read_bytes())}  {p.relative_to(out).as_posix()}\n" for p in listed),
        encoding="utf-8", newline="\n")  # fmt: skip
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--wheel", type=Path, required=True, help="the manuscript-guard wheel")
    parser.add_argument("--out", type=Path, required=True, help="the folder to build the site in")
    parser.add_argument("--cache", type=Path, default=WEB / ".cache",
                        help="where downloads are kept (default web/.cache)")  # fmt: skip
    args = parser.parse_args(argv)
    if not args.wheel.is_file() or not args.wheel.name.startswith("manuscript_guard-"):
        parser.error(f"--wheel {args.wheel}: not a manuscript-guard wheel")
    # Absolute, since esbuild runs in web/: a relative --out put the bundle in web/_site.
    args.out, args.cache = args.out.resolve(), args.cache.resolve()
    manifest = build(args.wheel.resolve(), args.out, args.cache)
    size = sum(p.stat().st_size for p in args.out.rglob("*") if p.is_file())
    print(f"built {args.out} ({size / 1e6:.1f} MB): manuscript-guard "
          f"{manifest['manuscript_guard']}, Pyodide {manifest['pyodide']}, "
          f"pandoc {manifest['pandoc']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
