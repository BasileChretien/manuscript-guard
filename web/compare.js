// "Compare a revision": the version a referee or an editor read first and the revision set
// side by side, as `manuscript-guard compare` sets them, with the authors' response letter
// and the reader's own comments where given (Basile, 2026-11-28: a second choice on the
// page, every option of compare's, its report as text). The report is the text the command
// line prints, shown in the page and saved as text; the start of the reader's report, where
// asked for, is the Markdown the command line's `--report-draft` writes. Nothing is sent.

// What a comparison under way says: each step it says as it starts
// (`auditing.progress.COMPARE_STEPS`), and how long each usually takes, in seconds.
export const COMPARE_STEPS = {
  versions: ["Reading both versions", 8],
  differences: ["Setting them side by side", 1],
  before: ["Checking the version before", 12],
  after: ["Checking the revision", 12],
  letter: ["Holding the letter to both versions", 1],
  comments: ["Matching your comments to the revision", 1],
  written: ["Writing your report", 1],
};

// The files a version can be, as `compare` reads them on the page: LaTeX is the command
// line's.
const VERSION = /\.(docx|md|pdf)$/i;
// The example revision that ships with the page: the example paper and an earlier version
// of it, and a letter that answers invented reviewers.
const EXAMPLE = ["example-before.md", "example-paper.md", "example-letter.md"];

const carriesFiles = (event) => [...(event.dataTransfer?.types || [])].includes("Files");

// The page's own functions it needs (app.js): `$`, `ask`, `read`, `megabytes`, `say`,
// `stepsShown`, `runEnded`, `clearReport`, `scrolling`, `listRequests` and `notLoaded`.
export function comparing(page) {
  const { $ } = page;
  const on = () => $("modecompare").checked;
  let draft = null;

  // Each choice shows its own boxes, and the buttons say what they do.
  function modeShown() {
    const comparing = on();
    $("checkparts").hidden = comparing;
    $("compareparts").hidden = !comparing;
    $("paper").required = !comparing;
    $("before").required = comparing;
    $("after").required = comparing;
    $("run").textContent = comparing ? "Compare the versions" : "Check my paper";
    $("example").textContent = comparing ? "Or try it with an example revision"
      : "Or try it with an example paper";
  }
  for (const id of ["modecheck", "modecompare"]) $(id).addEventListener("change", modeShown);
  // The boxes of the choice the page starts with, whatever a browser restored of the last
  // visit's form (round 1 of #854).
  modeShown();

  // Each version chosen, said in its box; or dropped on it, as the paper is on its own.
  for (const [id, said] of [["before", "beforechosen"], ["after", "afterchosen"]]) {
    const box = $(id);
    const label = box.closest("label");
    box.addEventListener("change", () => {
      const [file] = box.files;
      $(said).hidden = !file;
      $(said).textContent = file ? `${file.name} (${page.megabytes(file.size)})` : "";
    });
    for (const name of ["dragenter", "dragover"]) {
      label.addEventListener(name, (event) => {
        if (!carriesFiles(event)) return;
        event.preventDefault();
        if (!box.disabled) label.classList.add("dropping");
      });
    }
    label.addEventListener("dragleave", (event) => {
      if (!label.contains(event.relatedTarget)) label.classList.remove("dropping");
    });
    label.addEventListener("drop", (event) => {
      label.classList.remove("dropping");
      if (!carriesFiles(event)) return;
      event.preventDefault();
      if (box.disabled) {
        page.say("The checker is still loading: drop the version again once the page says Ready.");
        return;
      }
      const [file] = event.dataTransfer.files;
      if (!file) return;
      if (!VERSION.test(file.name)) {
        page.say(`${file.name} is not a .docx, a .md or a .pdf: drop or choose the version `
          + "itself.");
        return;
      }
      const chosen = new DataTransfer();
      chosen.items.add(file);
      box.files = chosen.files;
      box.dispatchEvent(new Event("change", { bubbles: true }));
    });
  }

  // The comparison's report, as the command line prints it, and what it said on stderr.
  function shown(result, title) {
    $("result").hidden = false;
    $("notes").hidden = !result.err;
    $("notes").textContent = result.err;
    $("astext").hidden = false;
    $("report").textContent = result.out || "";
    $("save").dataset.name = "comparison-report.txt";
    $("again").textContent = "Compare another revision";
    if (result.draft) {
      draft = result.draft;
      $("savedraft").hidden = false;
      $("savedraft").title = draft.name;
    }
    $("done").textContent = `Compared ${title} in ${(result.ms / 1000).toFixed(1)} s. Each line `
      + "of the report below is a fact with its place: none says whether a change answers a "
      + "comment, which is yours to judge.";
  }

  async function run(before, after, letter, comments) {
    $("run").disabled = true;
    $("example").disabled = true;
    page.clearReport();
    draft = null;
    const title = `${before.name} with ${after.name}`;
    const order = ["versions", "differences", "before", "after", ...(letter ? ["letter"] : []),
      ...(comments ? ["comments"] : []), "written"];
    page.stepsShown(`Comparing ${title}…`, order, COMPARE_STEPS);
    try {
      const result = await page.ask("compare", {
        before: await page.read(before),
        after: await page.read(after),
        letter: letter ? await page.read(letter) : null,
        comments: comments ? await page.read(comments) : null,
        draft: $("draft").checked,
      });
      window.mgLast = result;
      // A file `compare` could not read: what it said, and no report.
      if (result.code !== 0) {
        const said = result.err.trim().split("\n").pop().replace(/^manuscript-guard compare: /, "");
        page.runEnded(`The comparison could not run: ${said.replace(/[\s.]+$/, "")}.`,
          { failed: true });
        return;
      }
      shown(result, title);
      $("netlog").textContent += "\n\n" + page.listRequests(
        `This comparison of ${title} sent requests to:`, result.sent);
      page.runEnded(`Compared ${title} in ${(result.ms / 1000).toFixed(1)} s: your report is below.`);
      $("reporthead").scrollIntoView({ block: "start", behavior: page.scrolling() });
      $("reporthead").focus({ preventScroll: true });
    } catch (error) {
      page.runEnded(`The comparison could not run: ${error.message.replace(/[\s.]+$/, "")}. The `
        + "command line says more: uvx manuscript-guard compare v1.docx v2.docx", { failed: true });
      window.mgLast = { error: error.message };
    } finally {
      $("run").disabled = false;
      $("example").disabled = false;
    }
  }

  // Both versions chosen, and the letter and the comments where they are.
  async function submitted() {
    const [before] = $("before").files;
    const [after] = $("after").files;
    if (before && after) await run(before, after, $("letter").files[0] || null,
      $("comments").files[0] || null);
  }

  // Not fetched at the start, as the example paper is not (app.js).
  async function example() {
    let files;
    try {
      files = await Promise.all(EXAMPLE.map(async (name) => {
        const answer = await fetch(name);
        if (!answer.ok) throw new Error(`the page answered ${answer.status}`);
        return new File([await answer.blob()], name, { type: "text/markdown" });
      }));
    } catch (error) {
      page.notLoaded(`The example revision could not be loaded (${error.message}): it comes `
        + "from this page's address, so it needs the network.");
      return;
    }
    const [before, after, letter] = files;
    await run(before, after, letter, null);
  }

  // The start of the reader's report, as the command line's `--report-draft` writes it.
  $("savedraft").addEventListener("click", () => {
    if (!draft) return;
    const link = document.createElement("a");
    link.href = URL.createObjectURL(new Blob([draft.data], { type: "text/markdown" }));
    link.download = draft.name;
    link.click();
    URL.revokeObjectURL(link.href);
  });

  return { on, submitted, example };
}
