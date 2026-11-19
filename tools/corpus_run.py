"""Install manuscript-guard at a commit and run its reports on every paper of a corpus.

The half of `tools/corpus.py` that runs things; that file says what the rest does, and
docs/corpus.md how a corpus is laid out. The papers are downloaded files: every command here
has a time limit, none runs with its working folder inside `corpus/`, and the build reads
the papers under `python -I`, which imports nothing from a working folder or `PYTHONPATH`.
"""

from __future__ import annotations

import io
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tarfile
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

#: Seconds a step on one paper may take, and a git, venv or install command.
LIMIT = 600
#: A paper's slug, which names its folders under corpus/ and runs/<run>/.
SLUG = re.compile(r"[A-Za-z0-9._-]+")


class CorpusError(Exception):
    """The corpus, a run or the ledger is not as the tool needs it; said in one line."""


def load_json(path: Path) -> object | None:
    try:
        return json.loads(path.read_text("utf-8"))
    except (OSError, ValueError):
        return None


def quiet(cmd: list[str], cwd: Path | None = None) -> bytes:
    """Run a command that is not a step on a paper, with the time limit, and say its error."""
    try:
        done = subprocess.run(cmd, cwd=cwd, capture_output=True, timeout=LIMIT)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise CorpusError(f"{Path(cmd[0]).name}: {exc}") from None
    if done.returncode:
        tail = done.stderr.decode("utf-8", "replace").strip()[-800:]
        raise CorpusError(f"{' '.join(map(str, cmd[:4]))} failed: {tail}")
    return done.stdout


def _kill(proc: subprocess.Popen) -> None:
    if os.name == "nt":
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)], capture_output=True,
                       timeout=60)  # fmt: skip
    else:
        os.killpg(proc.pid, signal.SIGKILL)


def call(cmd: list[str], cwd: Path, out: Path, env: dict) -> dict:
    """One step on one paper: its output to a file, killed with its children past the limit."""
    started = time.monotonic()
    flags = {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == "nt" \
        else {"start_new_session": True}  # fmt: skip
    with out.open("wb") as sink:
        proc = subprocess.Popen(cmd, cwd=cwd, stdout=sink, stderr=subprocess.PIPE, env=env, **flags)
        try:
            _, err = proc.communicate(timeout=LIMIT)
            code: object = proc.returncode
        except subprocess.TimeoutExpired:
            _kill(proc)
            _, err = proc.communicate(timeout=60)
            code = "timeout"
    shown = ["manuscript-guard", *cmd[cmd.index(ENTRY) + 1:]] if ENTRY in cmd else cmd
    return {"cmd": shown, "exit": code,
            "seconds": round(time.monotonic() - started, 2),
            "stderr": err.decode("utf-8", "replace")[-3000:]}  # fmt: skip


def resolve(repo: Path, commit: str) -> str:
    if commit.startswith("-"):
        raise CorpusError(f"{commit!r} is no commit: it would reach git as an option")
    try:
        return quiet(["git", "-C", str(repo), "rev-parse", "--verify", f"{commit}^{{commit}}"]
                     ).decode().strip()  # fmt: skip
    except CorpusError:
        quiet(["git", "-C", str(repo), "fetch", "-q", "origin", commit])
        fetched = quiet(["git", "-C", str(repo), "rev-parse", "--verify", "FETCH_HEAD"])
        return fetched.decode().strip()


def venv_python(venv: Path) -> Path:
    return venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def install(builds: Path, repo: Path, sha: str) -> Path:
    """A venv under builds/<sha9>/ with manuscript-guard installed from that commit, not
    editable, so nothing else on the machine is pointed at it. Reused when already there."""
    venv = builds / sha[:9]
    python = venv_python(venv)
    marker = venv / "installed.txt"
    if marker.is_file() and marker.read_text("utf-8") == sha and python.is_file():
        return python
    source = builds / f"src-{sha[:9]}"
    if source.exists():
        shutil.rmtree(source)
    source.mkdir(parents=True)
    archive = quiet(["git", "-C", str(repo), "archive", "--format=tar", sha])
    with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
        extra = {"filter": "data"} if hasattr(tarfile, "data_filter") else {}
        tar.extractall(source, **extra)
    if shutil.which("uv"):
        quiet(["uv", "venv", "-q", "--python", sys.executable, str(venv)])
        quiet(["uv", "pip", "install", "-q", "--python", str(python), str(source)])
    else:
        quiet([sys.executable, "-m", "venv", str(venv)])
        quiet([str(python), "-m", "pip", "install", "-q", str(source)])
    if not python.is_file():
        raise CorpusError(f"the install at {sha[:9]} left no {python}")
    (venv / "installed.txt").write_text(sha, "utf-8")
    return python


#: The build, run under `python -I` so that nothing in a working folder or PYTHONPATH is
#: imported, with UTF-8 output, which -I's ignoring PYTHONIOENCODING would otherwise lose.
ENTRY = ("import sys; sys.argv[0] = 'manuscript-guard'; "
         "from manuscript_guard.cli import main; sys.exit(main(sys.argv[1:]))")


def papers(root: Path) -> list[dict]:
    found = []
    for meta in sorted((root / "corpus").glob("*/meta.json")):
        data = load_json(meta)
        if not isinstance(data, dict) or not {"slug", "format", "main"} <= set(data):
            raise CorpusError(f"{meta}: a paper's meta.json names its slug, format and main file")
        slug = str(data["slug"])
        if slug != meta.parent.name or not SLUG.fullmatch(slug) or ".." in slug:
            raise CorpusError(f"{meta}: its slug {slug!r} is not its folder's name, in letters, "
                              "digits, '.', '_' and '-'")  # fmt: skip
        found.append(data)
    if not found:
        raise CorpusError(f"{root / 'corpus'} holds no corpus/<slug>/meta.json")
    return found


def _latex_project(mg: list[str], files: Path, main: str, project: Path, env: dict) -> dict:
    step = call([*mg, "init", "--latex", str(project)], project.parent,
                project.parent / "init.out", env)  # fmt: skip
    if step["exit"] != 0:
        return step
    manuscript, source = project / "manuscript", (files / main).parent
    (manuscript / "main.tex").unlink(missing_ok=True)
    if Path(main).name != "main.tex" and (source / "main.tex").exists():
        return {**step, "exit": "skipped", "note": "main.tex is another file of the source"}
    shutil.copytree(source, manuscript, dirs_exist_ok=True)
    if Path(main).name != "main.tex":
        (manuscript / Path(main).name).rename(manuscript / "main.tex")
    bibs = list(manuscript.rglob("*.bib"))
    if len(bibs) == 1:
        (project / "literature").mkdir(exist_ok=True)
        shutil.copy(bibs[0], project / "literature" / "references.bib")
    return {**step, "note": f"{len(bibs)} .bib file(s) in the source"}


def _claim(out_root: Path, sha: str) -> None:
    """Refuse a run folder that holds another commit's reports: its steps would be kept, and
    the gate would read a commit it never ran."""
    made = load_json(out_root / "run.json")
    if isinstance(made, dict) and made.get("sha") not in (None, sha):
        raise CorpusError(f"{out_root} holds a run of {str(made['sha'])[:9]}, not of {sha[:9]}: "
                          "name the run otherwise, or delete that folder")  # fmt: skip
    for steps in out_root.glob("*/steps.json"):
        held = load_json(steps)
        if not isinstance(held, dict) or held.get("sha") != sha:
            raise CorpusError(f"{steps} was written for another commit than {sha[:9]}: name the "
                              "run otherwise, or delete its folder")  # fmt: skip


def run_paper(python: Path, meta: dict, root: Path, out_root: Path, env: dict,
              sha: str) -> dict:  # fmt: skip
    """The four reports on one paper, each step once: a step already run for the same commit
    is kept, and a folder of another commit's steps is refused."""
    mg = [str(python), "-I", "-X", "utf8", "-c", ENTRY]
    files = root / "corpus" / meta["slug"] / "files"
    out = out_root / meta["slug"]
    out.mkdir(parents=True, exist_ok=True)
    steps_file = out / "steps.json"
    held = load_json(steps_file) or {"sha": sha, "steps": {}}
    if not isinstance(held, dict) or held.get("sha") != sha:
        raise CorpusError(f"{steps_file} was written for another commit than {sha[:9]}")
    steps = held["steps"]
    main = files / meta["main"]

    def step(name: str, args: list[str], cwd: Path = out) -> None:
        if name not in steps:
            steps[name] = call([*mg, *args], cwd, out / f"{name}.json", env)

    step("audit", ["audit", "--json", str(main)])
    if meta.get("pdf"):
        step("audit-pdf", ["audit", "--json", str(files / meta["pdf"])])
    if meta.get("v1"):
        step("compare", ["compare", "--json", str(files / meta["v1"]), str(main)])
    if meta["format"] in ("docx", "latex") and "check" not in steps:
        project = out / "project"
        if project.exists():
            shutil.rmtree(project)
        if meta["format"] == "docx":
            steps["init"] = call([*mg, "init", "--from", str(main), str(project)], out,
                                 out / "init.out", env)  # fmt: skip
        else:
            steps["init"] = _latex_project(mg, files, meta["main"], project, env)
        if steps["init"]["exit"] == 0:
            step("check", ["check", "--json"], cwd=project)
    steps_file.write_text(json.dumps({"sha": sha, "steps": steps}, indent=1), "utf-8")
    return steps


def run(root: Path, commit: str, name: str | None, repo: Path, jobs: int,
        only: list[str] | None) -> dict:  # fmt: skip
    sha = resolve(repo, commit)
    python = install(root / "builds", repo, sha)
    version = quiet([str(python), "-I", "-c",
                     "import manuscript_guard; print(manuscript_guard.__version__)"],
                    cwd=root).decode().strip()  # fmt: skip
    out_root = root / "runs" / (name or sha[:9])
    out_root.mkdir(parents=True, exist_ok=True)
    _claim(out_root, sha)
    chosen = [m for m in papers(root) if not only or m["slug"] in only]
    env = {**os.environ, "MANUSCRIPT_GUARD_USER_SKILLS": str(root / "no-user-skills"),
           "MANUSCRIPT_GUARD_NO_REPORTS": "1"}  # fmt: skip
    env.pop("MANUSCRIPT_GUARD_DEBUG", None)
    record = {"commit": commit, "sha": sha, "version": version, "papers": len(chosen)}
    (out_root / "run.json").write_text(json.dumps(record, indent=1), "utf-8")

    def one(meta: dict) -> tuple[str, object]:
        try:
            steps = run_paper(python, meta, root, out_root, env, sha)
        except (OSError, subprocess.SubprocessError, CorpusError) as exc:
            return meta["slug"], f"runner error: {exc}"
        bad = {k: v["exit"] for k, v in steps.items() if v["exit"] not in (0, 1, "skipped")}
        return meta["slug"], bad or "ok"

    with ThreadPoolExecutor(max(1, jobs)) as pool:
        for slug, said in pool.map(one, chosen):
            print(f"{out_root.name} {slug}: {said}", flush=True)
    return record
