"""The audit page a journal's host serves on its own site (web/build.py --host,
docs/hosting-the-audit-page.md): the host folder read, and refused where anything in it is
wrong, the files the build adds for it, and the journal the page offers handed to the command
line as the command line is given it.

The built page in Node, Chrome and Firefox, held to `audit --journal` word for word for each
journal it offers, its code byte for byte the page's without a host, is CI's `web` job
(`web/test/check.py --hosted`).
"""

from __future__ import annotations

import importlib.util
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

import manuscript_guard

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web"
HOST = WEB / "test" / "host"
NODE = shutil.which("node")


def build_script():
    spec = importlib.util.spec_from_file_location("web_build_host", WEB / "build.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


build = build_script()


def test_a_host_folder_gives_the_page_its_name_logo_accent_contact_and_journals() -> None:
    """host.yaml's name, logo, accent and contact line, and each journals/<slug>.yaml held to
    the journal schema, listed by name, with how its review is blinded."""
    host = build.read_host(HOST)
    assert host["name"] == "Society of Invented Examples"
    assert host["logo"] == HOST / "logo.svg"
    assert host["accent"] == {"light": "#7a1f3d", "dark": "#e7a0b8"}
    assert host["contact"] == {"text": "Questions about our journals' requirements",
                               "link": "mailto:editorial@example.invalid",
                               "shown": "editorial@example.invalid"}
    assert [(one["slug"], one["name"], one["file"], one["blinding"]) for one in host["journals"]] \
        == [("blind-letters", "Blind Letters in Examples", "journals/blind-letters.yaml", "double"),
            ("examples", "Journal of Invented Examples", "journals/examples.yaml", "single")]


def test_the_build_adds_the_host_s_files_and_says_them_in_the_manifest(tmp_path: Path) -> None:
    """Each profile as the host gave it, byte for byte, the logo and the accent's style sheet,
    and what manifest.json tells the page of them; nothing of the folder's paths."""
    said = build.hosted(build.read_host(HOST), tmp_path)
    assert said == {
        "name": "Society of Invented Examples", "logo": "host/logo.svg", "style": "host/host.css",
        "contact": {"text": "Questions about our journals' requirements",
                    "link": "mailto:editorial@example.invalid",
                    "shown": "editorial@example.invalid"},
        "journals": [{"slug": "blind-letters", "name": "Blind Letters in Examples",
                      "file": "journals/blind-letters.yaml", "blinding": "double"},
                     {"slug": "examples", "name": "Journal of Invented Examples",
                      "file": "journals/examples.yaml", "blinding": "single"}],
    }
    for name in ("blind-letters", "examples"):
        assert (tmp_path / "journals" / f"{name}.yaml").read_bytes() \
            == (HOST / "journals" / f"{name}.yaml").read_bytes()
    assert (tmp_path / "host" / "logo.svg").read_bytes() == (HOST / "logo.svg").read_bytes()
    css = (tmp_path / "host" / "host.css").read_text(encoding="utf-8")
    assert re.findall(r"--teal: (#[0-9a-f]{6})", css) == ["#7a1f3d", "#e7a0b8"]
    assert "@media (prefers-color-scheme: dark)" in css


def _page_colours() -> dict[str, dict[str, str]]:
    """The page's own colours in web/style.css, light and dark."""
    css = (WEB / "style.css").read_text(encoding="utf-8")
    light = css[css.index(":root {"):css.index("}", css.index(":root {"))]
    start = css.index("@media (prefers-color-scheme: dark)")
    dark = css[start:css.index("}", start)]
    return {scheme: dict(re.findall(r"--([a-z-]+): (#[0-9a-f]{6})", block))
            for scheme, block in (("light", light), ("dark", dark))}


def test_an_accent_is_read_against_the_page_s_own_colours_which_pass_it() -> None:
    """The colours an accent is held to are the page's paper, card and button text in
    style.css, light and dark; and the page's own teal passes the contrast it asks of a host."""
    colours = _page_colours()
    for scheme in ("light", "dark"):
        assert build.AROUND[scheme] == tuple(colours[scheme][name]
                                             for name in ("paper", "card", "on-teal"))
        assert min(build.contrast(colours[scheme]["teal"], other)
                   for other in build.AROUND[scheme]) >= build.LEAST_CONTRAST
    assert round(build.contrast("#000000", "#ffffff"), 2) == 21.0
    assert build.contrast("#777777", "#777777") == 1.0


def _host(tmp_path: Path, host: str, journals: dict[str, str] | None = None,
          files: dict[str, bytes] | None = None) -> Path:
    """A host folder of host.yaml's text, its journals' profiles and other files."""
    (tmp_path / "host.yaml").write_text(host, encoding="utf-8")
    for name, text in (journals or {}).items():
        (tmp_path / "journals").mkdir(exist_ok=True)
        (tmp_path / "journals" / name).write_text(text, encoding="utf-8")
    for name, data in (files or {}).items():
        (tmp_path / name).write_bytes(data)
    return tmp_path


HEAD = "schema: manuscript-guard/host/1\nname: A Society\n"
PROFILE = ("schema: manuscript-guard/journal/1\nname: {name}\n"
           "source_url: https://example.invalid/x\nretrieved_on: 2026-11-25\n")


@pytest.mark.parametrize(("host", "journals", "files", "said"), [
    ("name: A Society\n", None, None, "must start `schema: manuscript-guard/host/1`"),
    (HEAD + "footer: our words\n", None, None, "footer is not a key a host may set"),
    ("schema: manuscript-guard/host/1\n", None, None, "host.yaml: name must be text"),
    ("schema: manuscript-guard/host/1\nname: \"A\\nSociety\"\n", None, None,
     "name must be one line"),
    (HEAD + "logo: ../outside.svg\n", None, None, "is not a file in the host folder"),
    (HEAD + "logo: logo.gif\n", None, {"logo.gif": b"GIF89a"}, "not an .svg, a .png or a .webp"),
    (HEAD + "logo: logo.png\n", None, {"logo.png": b"<svg/>"}, "not the picture its extension"),
    (HEAD + "logo: logo.svg\n", None, {"logo.svg": b"<svg/>" + b" " * 600_000}, "over 512 KB"),
    (HEAD + "accent:\n  light: '#7a1f3d'\n", None, None, "accent must give `light` and `dark`"),
    (HEAD + "accent: {light: red, dark: '#e7a0b8'}\n", None, None, "light must be written #rrggbb"),
    (HEAD + "accent: {light: '#cccccc', dark: '#e7a0b8'}\n", None, None,
     "accent light #cccccc has a contrast of"),
    (HEAD + "accent: {light: '#7a1f3d', dark: '#203040'}\n", None, None,
     "accent dark #203040 has a contrast of"),
    (HEAD + "contact: {text: Ask us, link: 'javascript:alert(1)'}\n", None, None,
     "neither mailto:<address> nor https://"),
    (HEAD + "contact: {text: Ask us, link: 'http://example.invalid'}\n", None, None,
     "neither mailto:<address> nor https://"),
    (HEAD + "contact: {text: Ask us, link: 'mailto:nobody'}\n", None, None,
     "neither mailto:<address> nor https://"),
    (HEAD + "contact: {text: Ask us, link: 'https://example.invalid/a b'}\n", None, None,
     "must be one address"),
    (HEAD + "contact: {text: \"Ask\\nus\", link: 'mailto:a@example.invalid'}\n", None, None,
     "contact text must be one line"),
    (HEAD, {"Journal.yaml": PROFILE.format(name="J")}, None, "journals/Journal.yaml: each journal"),
    (HEAD, {"j.yml": PROFILE.format(name="J")}, None, "journals/j.yml: each journal"),
    (HEAD, {"j.yaml": "schema: manuscript-guard/journal/1\nname: J\n"}, None,
     "journals/j.yaml is not a journal profile"),
    (HEAD, {"a.yaml": PROFILE.format(name="Same"), "b.yaml": PROFILE.format(name="same")}, None,
     "two profiles are named"),
    # The value of the list's "Another journal", which would choose this profile in its place
    # (round 1 of #791).
    (HEAD, {"other.yaml": PROFILE.format(name="Other Letters")}, None,
     "journals/other.yaml: other is what the page's list calls another journal"),
])
def test_a_host_folder_with_anything_wrong_is_refused_and_says_what(
        tmp_path: Path, host: str, journals: dict | None, files: dict | None, said: str) -> None:
    """Nothing a host gives is passed over or guessed at: a key the page does not take, a
    logo that is not the picture it says, an accent the page's text would not read against, a
    contact link that is neither an address nor https, a journal's file not named by a slug
    or not a profile the command line reads, and two journals the list could not tell apart."""
    folder = _host(tmp_path, host, journals, files)
    with pytest.raises(build.HostError, match=re.escape(said)):
        build.read_host(folder)


def test_the_files_a_computer_leaves_in_journals_and_its_folders_are_passed_over(
        tmp_path: Path) -> None:
    """What Finder, Explorer or an editor leaves beside the profiles, a hidden file, Thumbs.db
    or desktop.ini, and a folder such as the stored instructions pages the journal-profile
    skill keeps in sources/, are not journals, and do not stop the build (round 1 of #791)."""
    folder = _host(tmp_path, HEAD, {"j.yaml": PROFILE.format(name="J"), ".DS_Store": "",
                                    "Thumbs.db": "", "desktop.ini": "", ".j.yaml.swp": ""})
    (folder / "journals" / "sources").mkdir()
    (folder / "journals" / "sources" / "j.txt").write_text("the page", encoding="utf-8")
    assert [journal["slug"] for journal in build.read_host(folder)["journals"]] == ["j"]


@pytest.mark.parametrize("where", ["the host folder", "a folder that holds it", "one in it"])
def test_the_page_is_never_built_over_the_host_folder(tmp_path: Path, where: str) -> None:
    """`--out` is emptied first: one that is the host folder, holds it, or is in it would delete
    the host's profiles, so it is refused before anything is touched (round 1 of #791)."""
    host = tmp_path / "site" / "ours"
    shutil.copytree(HOST, host)
    out = {"the host folder": host, "a folder that holds it": tmp_path / "site",
           "one in it": host / "journals"}[where]
    wheel = tmp_path / f"manuscript_guard-{manuscript_guard.__version__}-py3-none-any.whl"
    wheel.write_bytes(b"")
    with pytest.raises(SystemExit) as stopped:
        build.main(["--wheel", str(wheel), "--host", str(host), "--out", str(out)])
    assert stopped.value.code != 0
    assert (host / "host.yaml").is_file() and (host / "journals" / "examples.yaml").is_file()


def test_a_host_folder_without_host_yaml_is_refused(tmp_path: Path) -> None:
    with pytest.raises(build.HostError, match="has no host.yaml"):
        build.read_host(tmp_path)


def test_a_host_folder_is_read_by_the_release_the_page_runs() -> None:
    """The profiles are held to the schema of the manuscript-guard installed, which must be the
    wheel's, or the page would refuse a profile the build passed; and the project's landing
    page is no host's."""
    said = build.host_for(HOST, "0.0.1")
    assert isinstance(said, str)
    assert f"manuscript-guard {manuscript_guard.__version__} is installed here" in said
    assert "pip install manuscript-guard==0.0.1" in said
    read = build.host_for(HOST, manuscript_guard.__version__)
    assert read["name"] == "Society of Invented Examples"
    with pytest.raises(SystemExit):
        build.main(["--landing", "--host", str(HOST), "--out", "nowhere"])


@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_the_worker_hands_the_audit_the_journal_the_page_offers() -> None:
    """worker.js, run in Node with a stand-in for Pyodide (web/test/names.mjs): a journal the
    page offers, chosen, written under journals/ and given as `--journal journals/<slug>.yaml`,
    as the command line is given it from the host's folder, the form then making no profile;
    a file chosen named as that folder, or a profile's name that is not a slug's, refused
    before anything is written."""
    form = {"name": "Journal of Tests", "date": "2026-11-25"}
    cases = [
        {"paper": "paper.docx", "against": [], "offered": "journals/examples.yaml",
         "journal": form, "authors": {"authors": [{"given": "Ada", "family": "Example"}]}},
        {"paper": "paper.docx", "against": ["journals"], "offered": "journals/examples.yaml"},
        {"paper": "journals.zip", "against": [], "offered": "journals/examples.yaml"},
        {"paper": "paper.docx", "against": [], "offered": "../examples.yaml"},
        {"paper": "paper.docx", "against": ["journals"]},
    ]
    done = subprocess.run([NODE, str(WEB / "test" / "names.mjs")], input=json.dumps(cases),
                          capture_output=True, text=True, encoding="utf-8", timeout=60,
                          check=False)  # fmt: skip
    assert done.returncode == 0, done.stderr
    offered, clash, archived, outside, beside = json.loads(done.stdout)
    assert offered["args"] == ["audit", "paper.docx", "--journal", "journals/examples.yaml",
                               "--authors", "authors.yaml"]
    assert offered["written"] == ["/work/paper.docx", "/work/authors.yaml",
                                  "/work/journals/examples.yaml"]
    assert offered["made"] == {"authors.yaml": "authors\n"}
    assert "a file chosen is named journals, the folder the page puts" in clash["error"]
    assert "a file chosen is named journals, the folder the page puts" in archived["error"]
    assert "offers no journal's profile named ../examples.yaml" in outside["error"]
    assert clash["written"] == archived["written"] == outside["written"] == []
    # An output named journals is no clash where no journal the page offers is chosen.
    assert beside["args"] == ["audit", "paper.docx", "--against", "journals"]


def test_the_page_reads_one_thing_of_its_address_and_writes_nothing_to_it() -> None:
    """A link may choose a journal, ?journal=<slug>, and the page reads nothing else of its
    address, writes nothing to it, and sets what a host gives as text, never as markup."""
    app = (WEB / "app.js").read_text(encoding="utf-8")
    assert app.count("location.search") == 1
    assert 'new URLSearchParams(location.search).get("journal")' in app
    for never in ("location.hash", "history.", "location.href =", "location.assign",
                  "location.replace", "innerHTML", "outerHTML", "insertAdjacentHTML"):
        assert never not in app, never


def test_each_box_the_host_s_page_fills_is_on_the_page() -> None:
    """The ids app.js fills for a host are elements of index.html, hidden until it does."""
    page = (WEB / "index.html").read_text(encoding="utf-8")
    for name in ("hostlogo", "journalpick", "journalrules", "journalnote", "contact"):
        assert re.search(rf'id="{name}"[^>]*\bhidden\b', page), name
    for name in ("kicker", "journal", "journaltext"):
        assert f'id="{name}"' in page, name
    # "Another journal" is the value no slug may be (`build.ANOTHER`).
    assert f'<option value="{build.ANOTHER}">' in page
    assert f'$("journal").value === "{build.ANOTHER}"' in (WEB / "app.js").read_text("utf-8")
