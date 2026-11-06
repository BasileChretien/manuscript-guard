"""The landing page at the root of the site (web/landing/): what its policy lets it load, that
each of its links leads somewhere once the site is built, that each picture has its words, and
that where it repeats the README or the brand it says what they say.

The page in a real browser, loading under its own policy and asking no other host, is held by
CI's `web` job (`web/test/browser.mjs`).
"""

from __future__ import annotations

import html
import importlib.util
import re
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web"
PAGE = WEB / "landing" / "index.html"
REPOSITORY = "https://github.com/BasileChretien/manuscript-guard"


def script(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def build_script():
    return script("web_build", WEB / "build.py")


def page() -> str:
    return PAGE.read_text(encoding="utf-8")


def test_the_landing_page_may_load_its_own_files_and_do_nothing_else() -> None:
    """It runs no script and sends nothing. A style written into the page, as an attribute or
    an element, would be refused by its own policy and the page would show unstyled, so there
    is none; and the policy comes before the first thing the page loads."""
    text = page()
    policy = re.search(r'http-equiv="Content-Security-Policy" content="([^"]+)"', text).group(1)
    rules = {rule.split()[0]: rule.split()[1:] for rule in policy.split(";") if rule.strip()}
    assert rules == {
        "default-src": ["'none'"], "img-src": ["'self'"], "style-src": ["'self'"],
        "media-src": ["'self'"], "base-uri": ["'none'"], "form-action": ["'none'"],
    }
    assert text.index("Content-Security-Policy") < text.index("<link")
    assert "<script" not in text.lower()
    assert not re.search(r"<style|\sstyle=", text, re.IGNORECASE)


def test_each_link_of_the_landing_page_leads_somewhere_once_the_site_is_built(
    tmp_path: Path,
) -> None:
    """A relative address names a file of the built site, or the audit page's folder; a
    fragment, an id of the page; a link into the repository, a file there; and an address on
    the site itself, such as the social preview a card is drawn from, a file built."""
    build = build_script()
    shown = build.landing(tmp_path)
    assert shown, "the landing page shows no picture"
    text = page()
    # A picture from anywhere else would be refused by the page's policy. Headless browsers
    # draw the light scheme, so a dark <source> is never loaded by browser.mjs: it is held
    # here (round 1 of #559).
    named = re.findall(r"""(?:src|srcset|poster)\s*=\s*(?:"([^"]*)"|'([^']*)')""", text, re.I)
    for value in ("".join(pair) for pair in named):
        for candidate in filter(None, (part.split()[:1] for part in value.split(","))):
            picture = candidate[0]
            assert not re.match(r"[a-z][a-z0-9+.-]*:|//", picture, re.I), (
                f"{picture}: a picture from elsewhere"
            )
    ids = set(re.findall(r'\sid="([^"]+)"', text))
    addresses = [*re.findall(r'(?:href|src|srcset)="([^"]+)"', text),
                 *re.findall(rf'content="({re.escape(build.SITE)}[^"]*)"', text)]
    checked = 0
    for address in addresses:
        if address.startswith(build.SITE):
            address = address.removeprefix(build.SITE) or "index.html"
        elif address.startswith(REPOSITORY + "/blob/main/"):
            path = address.removeprefix(REPOSITORY + "/blob/main/").split("#")[0]
            assert (ROOT / path).is_file(), f"{address}: no {path} in the repository"
            checked += 1
            continue
        elif re.match(r"[a-z]+:|//", address):
            continue  # another site
        if address.startswith("#"):
            assert address[1:] in ids, f"{address}: no such id on the page"
        elif address == f"{build.AUDIT}/":
            assert (WEB / "index.html").is_file()  # the audit page, built in that folder
        elif address == "./":
            pass
        else:
            assert (tmp_path / address).is_file(), f"{address} is not in the built site"
        checked += 1
    assert checked >= len(shown) + 5


@pytest.mark.parametrize(
    "named",
    ["img/nothing-here.svg", "img/../../pyproject.toml", "media/nothing.mp4",
     "media/../../build.py"],
)
def test_a_picture_the_landing_page_names_that_docs_img_lacks_stops_the_build(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, named: str
) -> None:
    build = build_script()
    landing = tmp_path / "landing"
    landing.mkdir()
    (landing / "index.html").write_text(f'<img src="{named}" alt="">', encoding="utf-8")
    (landing / "style.css").write_text("", encoding="utf-8")
    monkeypatch.setattr(build, "LANDING", landing)
    with pytest.raises(SystemExit, match="nothing was built"):
        build.landing(tmp_path / "site")
    assert not (tmp_path / "site").exists(), "the build stopped after copying"


def test_the_landing_pages_example_of_a_convention_is_one_the_tool_has_built_in() -> None:
    """A convention the shipped list has needs no entry in paper.yaml, so an example of one
    the author must justify there would send a new user to write one (round 1 of #559)."""
    card = re.search(r"<h3>A convention of writing</h3>\s*<p>(.*?)</p>", page(), re.DOTALL)
    words = " ".join(card.group(1).split())
    assert "built in" in words and "paper.yaml" in words
    number, example = re.search(r"such as the ([\d.]*\d) of an? (.+?)\.(?:\s|$)", words).groups()
    assert re.search(rf"(?<![\d.]){re.escape(number)}(?![\d.])", example), (number, example)
    shipped = yaml.safe_load((ROOT / "src" / "manuscript_guard" / "data" / "conventions.yaml")
                             .read_text(encoding="utf-8"))["conventions"]  # fmt: skip
    assert any(re.search(rule["pattern"], example) for rule in shipped), (
        f"{example!r} is not on the shipped list of conventions"
    )


def alt(text: str, source: str) -> str:
    found = re.search(rf'<img\b[^>]*\ssrc="{re.escape(source)}"[^>]*?\salt="([^"]*)"', text)
    assert found, f"no picture {source} with alternative text"
    return " ".join(html.unescape(found.group(1)).split())


def test_each_picture_on_the_landing_page_has_its_words() -> None:
    """Every picture has alternative text, empty for a drawing whose name is written beside
    it, and the banner's is the character sheet's."""
    text = page()
    pictures = re.findall(r"<img\b[^>]*>", text)
    assert pictures and all(re.search(r'\salt="', picture) for picture in pictures)
    sheet = (ROOT / "brand" / "README.md").read_text(encoding="utf-8")
    assert alt(text, "img/brand/banner-light.svg") == alt(
        sheet, "../docs/img/brand/banner-light.svg"
    )


def video() -> tuple[str, str]:
    """The page's one video: its opening tag, and the whole element."""
    (whole,) = re.findall(r"<video\b[^>]*>.*?</video>", page(), re.DOTALL)
    return re.match(r"<video\b[^>]*>", whole).group(), whole


def test_the_video_plays_muted_with_controls_and_its_captions_and_still_frame(
    tmp_path: Path,
) -> None:
    """It plays muted and loops, as Basile chose, with controls to pause it. Its captions are
    in a WebVTT track as well as on screen, and its still frame takes its place for a reader
    who asks for less motion, by a rule of the style, since the page runs no script."""
    opening, whole = video()
    for attribute in ("autoplay", "muted", "loop", "playsinline", "controls"):
        assert re.search(rf"\s{attribute}[\s>]", opening), f"the video is not {attribute}"
    poster = re.search(r'\sposter="([^"]+)"', opening).group(1)
    track = re.search(r'<track\b[^>]*\skind="captions"[^>]*>', whole).group()
    captions = re.search(r'\ssrc="([^"]+)"', track).group(1)
    film = re.search(r'<source\b[^>]*\ssrc="([^"]+)"[^>]*\stype="video/mp4"', whole).group(1)
    build_script().landing(tmp_path)
    for name in (poster, captions, film):
        assert (tmp_path / name).is_file(), f"{name} is not in the built site"
    assert (tmp_path / film).stat().st_size < 4_000_000, "the video is 4 MB or more"
    assert (tmp_path / captions).read_text(encoding="utf-8").startswith("WEBVTT\n")
    assert alt(page(), poster), "the still frame has no words"
    css = (WEB / "landing" / "style.css").read_text(encoding="utf-8")
    assert re.search(r"\.film \.still \{ display: none; \}\s*@media \(prefers-reduced-motion: "
                     r"reduce\) \{\s*\.film video \{ display: none; \}\s*\.film \.still \{ "
                     r"display: block; \}\s*\}", css), "the still does not replace the video"


def cues(vtt: str) -> list[tuple[str, str, str]]:
    """Each cue of a WebVTT file: its start, its end and its words."""
    found = []
    for block in vtt.strip().split("\n\n")[1:]:
        lines = block.splitlines()
        start, end = lines[1].split(" --> ")
        found.append((start, end, " ".join(lines[2:])))
    return found


def stamp(seconds: float) -> str:
    ms = round(seconds * 1000)
    return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d}.{ms % 1000:03d}"


def test_the_captions_file_says_what_the_video_shows_and_the_page_lists_it() -> None:
    """The WebVTT file has the words and times of the captions the composition burns in
    (media/video/index.html), and the page's list of the video's words is the file's."""
    composed = (ROOT / "media" / "video" / "index.html").read_text(encoding="utf-8")
    burned = [(stamp(float(start)), stamp(float(start) + float(length)),
               html.unescape(re.sub(r"<[^>]+>", "", words)))
              for start, length, words in re.findall(
                  r'<div id="cap-\d+" class="cap clip" data-start="([\d.]+)" '
                  r'data-duration="([\d.]+)"[^>]*><span>(.+?)</span></div>$', composed,
                  re.MULTILINE)]  # fmt: skip
    assert burned and len(burned) == composed.count('class="cap clip"')
    vtt = (WEB / "landing" / "media" / "vord.en.vtt").read_text(encoding="utf-8")
    assert cues(vtt) == burned
    listed = re.search(r'<ol class="words">(.*?)</ol>', page(), re.DOTALL).group(1)
    items = [" ".join(html.unescape(re.sub(r"<[^>]+>", "", item)).split())
             for item in re.findall(r"<li>(.*?)</li>", listed, re.DOTALL)]  # fmt: skip
    assert items == [words for _, _, words in burned]


def test_the_videos_terminal_prints_what_check_prints() -> None:
    """The composition copies the lines of the README's demo, which tests/test_docs.py holds
    to what `check` prints on the worked example; a copy changed in one place only would show
    readers a finding the tool does not give."""
    figures = script("readme_figures", ROOT / "tools" / "readme_figures.py")
    composed = (ROOT / "media" / "video" / "index.html").read_text(encoding="utf-8")

    def lines(name: str) -> list[tuple[str, str]]:
        body = re.search(rf"const {name} = \[\n(.*?)\n\s*\];", composed, re.DOTALL).group(1)
        return re.findall(r'\["(\w+)", "((?:[^"\\]|\\.)*)"\]', body)

    def value(name: str) -> str:
        return re.search(rf'const {name} = "([^"]*)";', composed).group(1)

    assert [("prompt", value("COMMAND")), *lines("CARD")] == figures.CARD
    assert lines("CLEAN") == figures.CLEAN
    assert value("BINDING") == figures.BINDING


def test_each_villain_on_the_landing_page_is_named_with_the_gate_the_banner_gives_it() -> None:
    brand = script("brand_assets", ROOT / "tools" / "brand_assets.py")
    cards = re.findall(r'<li class="foe">(.*?)</li>', page(), re.DOTALL)
    shown = {
        re.search(r"img/brand/([a-z-]+)-light\.svg", card).group(1):
            re.search(r'<span class="gate">(G\d+)</span>', card).group(1)
        for card in cards
    }  # fmt: skip
    assert shown == dict(brand.CAST)


def test_the_status_on_the_landing_page_has_the_readmes_numbers() -> None:
    """Each number of the page's status is one the README's box of evidence gives. A number
    changed in the README and not here fails; a sentence changed around the same number does
    not, which a reader of the diff has to see."""
    status = page().split('<section id="status">', 1)[1].split("</section>", 1)[0]
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    box = readme.split("> **What it rests on so far.**", 1)[1].split("[Status](#status)", 1)[0]
    numbers = re.findall(r"\d[\d,.]*\d|\d", re.sub(r"<[^>]+>", " ", status))
    assert numbers
    scope = "740 references of 16 published open-access pharmacology and epidemiology papers"
    flat = " ".join(re.sub(r"<[^>]+>", " ", status).split())
    assert scope in " ".join(box.replace(">", " ").split()) and scope in flat, scope
    for number in numbers:
        assert re.search(rf"(?<![\d,.]){re.escape(number)}(?![\d,]|\.\d)", box), (
            f"the landing page's status says {number}; the README's box does not"
        )


def test_the_commands_on_the_landing_page_are_the_readmes() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    fenced = {block.strip() for block in re.findall(r"```bash\n(.*?)```", readme, re.DOTALL)}
    blocks = re.findall(r"<pre><code>(.*?)</code></pre>", page(), re.DOTALL)
    assert blocks
    for block in blocks:
        assert html.unescape(block).strip() in fenced, f"not a command of the README: {block}"


def test_the_checks_of_the_site_open_the_audit_page_where_the_build_puts_it() -> None:
    build = build_script()
    check = script("web_check", WEB / "test" / "check.py")
    assert check.AUDIT == build.AUDIT
    browser = (WEB / "test" / "browser.mjs").read_text(encoding="utf-8")
    assert f'const AUDIT = "/{build.AUDIT}/";' in browser
