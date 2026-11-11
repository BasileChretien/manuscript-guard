// The page: start the checker, hand it the files the reader chooses, show what it says.
// Nothing here sends anything anywhere; the checker runs in worker.js, in this browser.
const $ = (id) => document.getElementById(id);
const say = (text) => { $("status").textContent = text; };
// What the browser refused under the page's policy, as it reported it.
const pageRefused = [];
document.addEventListener("securitypolicyviolation", (event) =>
  pageRefused.push({ rule: event.effectiveDirective, url: event.blockedURI }));

const base = new URL("./", location.href).href;
const megabytes = (n) => (n / 1e6).toFixed(1) + " MB";
const here = (url) => url.startsWith(base);

// The worker is made from a blob: URL so that it runs under this page's policy (worker.js).
const source = await (await fetch("worker.js")).text();
const blob = new Blob([`const BASE = ${JSON.stringify(base)};\n${source}`], { type: "text/javascript" });
const worker = new Worker(URL.createObjectURL(blob), { type: "module" });
let nextId = 0;
const waiting = new Map();

// Where the start has got to: the step it is on (worker.js `step`) and the bytes it has
// received of those it fetches (worker.js `counted`). The bar and its percentage come from the
// bytes, held under 97% until the last step, which fetches nothing, and under 99% until the
// checker answers; with no count of bytes (a manifest from before it), from the steps. The
// status, which a screen reader says, changes with the step only. A step still under way
// after this long is said to be slow, with what to do; the page keeps waiting, as a slow
// network is no failure.
const SLOW_AFTER_MS = 90000;
const loading = { at: 0, of: 4, what: "", received: 0, expected: 0, shown: 0 };
window.mgLoading = loading;
let slow = null;
let stepped = false;
// The error the worker met while loading, if any: the slow note keeps it (round 2 of #627).
let met = "";
function showBar() {
  const { at, of, received, expected } = loading;
  const share = expected ? Math.min(received / expected, at < of ? 0.97 : 0.99)
    : Math.max(0, at - 1) / of;
  loading.shown = Math.max(loading.shown, Math.round(share * 100));
  $("progress").max = 100;
  $("progress").value = loading.shown;
  // A share, not megabytes: the bytes counted are the files' own, several times what the
  // network carries of them compressed, which is what "about 26 MB" says.
  $("amount").textContent = `${loading.shown}%`;
}
function loadingStep({ at, of, what }) {
  stepped = true;
  Object.assign(loading, { at, of, what });
  say(`Loading the checker, step ${at} of ${of}: ${what}. The first time only: after that it `
    + "is in this browser's cache.");
  showBar();
  clearTimeout(slow);
  slow = setTimeout(() => say(`Still on step ${at} of ${of} (${what}) after ${SLOW_AFTER_MS / 1000} s`
    + (met ? `, after an error (${met})` : "") + ". On a slow network this can take a few "
    + "minutes. If nothing changes, reload the page; the command line runs the same audit: "
    + "uvx manuscript-guard audit paper.docx"), SLOW_AFTER_MS);
}
const loaded = () => {
  clearTimeout(slow);
  $("progress").hidden = true;
  $("amount").textContent = "";
};

worker.onmessage = ({ data }) => {
  if (data.progress) {
    loadingStep(data.progress);
    return;
  }
  if (data.bytes) {
    Object.assign(loading, data.bytes);
    if (stepped) showBar();
    return;
  }
  const { resolve, reject } = waiting.get(data.id);
  waiting.delete(data.id);
  if (data.error) reject(new Error(data.error)); else resolve(data.value);
};
const ask = (type, payload) => new Promise((resolve, reject) => {
  const id = nextId++;
  waiting.set(id, { resolve, reject });
  worker.postMessage({ id, type, payload });
});

function listRequests(title, requests) {
  const elsewhere = requests.filter((r) => !here(r.url));
  const lines = elsewhere.length
    ? elsewhere.map((r) => `  ${new URL(r.url).host}${new URL(r.url).pathname}`)
    : ["  none"];
  return `${title}\n${lines.join("\n")}`;
}

// A worker whose script did not load or failed at its top answers nothing, and says no step:
// said, rather than "Loading" for ever. An error once a step is under way may come from
// something the start does not wait on, and the start may still answer: it is said, and the
// page keeps waiting (round 1 of #627).
worker.onerror = (event) => {
  if (window.mgReady) return;
  const what = event.message || "its script did not load";
  if (!stepped) {
    loaded();
    say(`The checker could not start: ${what}`);
    return;
  }
  met = what;
  say(`The checker met an error while loading (${what}). It may still start; if nothing `
    + "changes, reload the page.");
};

// Which release this page is, at the top, where a reader sees that it moved on.
fetch("manifest.json").then((answer) => answer.json()).then((manifest) => {
  const version = $("version");
  version.textContent = `manuscript-guard ${manifest.manuscript_guard}, rebuilt with each new release (`;
  const link = add(version, "a", "what changed");
  link.href = manifest.sources["manuscript-guard"].replace("/tree/", "/releases/tag/");
  version.append(")");
}).catch((error) => { $("version").textContent += ` (its version could not be read: ${error.message})`; });

const started = performance.now();
const booted = ask("boot").then((boot) => {
  loaded();
  const seconds = ((performance.now() - started) / 1000).toFixed(1);
  const sent = boot.loaded.reduce((sum, r) => sum + (r.sent || 0), 0);
  const m = boot.manifest;
  say(`Ready (${seconds} s). You can turn off your network now: the audit does not need it.`);
  $("versions").textContent =
    `manuscript-guard ${m.manuscript_guard}, Pyodide ${m.pyodide}, pandoc ${boot.pandocVersion}`;
  $("source").href = m.sources["manuscript-guard"];
  $("src-pandoc").href = m.sources.pandoc;
  $("netlog").textContent =
    `Loaded ${boot.loaded.length} files from ${location.host}, ${megabytes(sent)} over the network ` +
    `(nothing if they were already in this browser's cache).\n` +
    listRequests("Requests to any other host while loading:", boot.loaded);
  for (const id of ["paper", "against", "english", "known", "lookup", "details", "run"]) {
    $(id).disabled = false;
  }
  window.mgReady = true;
}).catch((error) => {
  loaded();
  say(`The checker could not start: ${error.message}`);
});

const read = async (file) => ({ name: file.name, data: await file.arrayBuffer() });

// An element under `parent`, its text set as text, never as markup: a paper's words are the
// reader's, and none of them is HTML to this page.
function add(parent, tag, text, kind) {
  const element = document.createElement(tag);
  if (text !== undefined) element.textContent = text;
  if (kind) element.className = kind;
  parent.append(element);
  return element;
}

// The report as `web.view` gives it: what each check found in a table, the findings on the
// words a fold for each kind with every place inside, the other sections as their text. The
// text the command line prints stays below, folded, and is what "Save the report" saves.
// With no view (a run that made no report), the text is shown open.
function draw(view) {
  const box = $("view");
  box.replaceChildren();
  $("astext").open = !view;
  if (!view) return;
  for (const line of view.header) add(box, "p", line, "headline");
  for (const [heading, said] of view.notes) {
    add(box, "h3", heading);
    const list = add(box, "ul");
    for (const item of said) add(list, "li", item);
  }
  add(box, "h3", "What was checked");
  const table = add(box, "table", undefined, "checks");
  for (const [name, said] of view.checks) {
    const row = add(table, "tr");
    add(row, "th", name);
    add(row, "td", said);
  }
  // What --strict counts, where the view still says it: the table's rows and the sections'
  // headings name it (round 1 of #627). Each heading below gives the paper's name only where
  // there are several, and a check's code (G14) only on pointing at its kind.
  if (view.strict) add(box, "p", view.strict, "small");
  const papers = view.words.filter((paper) => paper.note || paper.kinds.length);
  for (const paper of papers) {
    // The paper's name wherever several were audited, though only one has findings: no place
    // under the heading names the paper again (review of #631).
    add(box, "h3", view.words.length > 1 ? `Writing and language: ${paper.paper}` : "Writing and language");
    if (paper.note) {
      add(box, "p", paper.note);
      continue;
    }
    add(box, "p", "For you to look at, kind by kind: open one to see its places.", "small");
    for (const kind of paper.kinds) {
      const fold = add(box, "details", undefined, "kind");
      fold.title = `Checked by ${kind.gate}`;
      add(fold, "summary", `${kind.title} (${kind.count})`);
      if (kind.hint) add(fold, "p", `Hint: ${kind.hint}`, "hint");
      const list = add(fold, "ol");
      for (const place of kind.places) {
        const item = add(list, "li");
        add(item, "span", `${place.where}: `, "where");
        add(item, "span", (place.failing ? "FAIL: " : "") + place.message);
        if (place.context) add(item, "div", place.context, "context");
        if (place.hint) add(item, "div", `Hint: ${place.hint}`, "hint");
      }
    }
  }
  for (const [heading, text] of view.sections) {
    const fold = add(box, "details", undefined, "section");
    fold.open = true;
    add(fold, "summary", heading);
    add(fold, "pre", text);
  }
  add(box, "p", view.closing, "closing");
}

// The paper dropped on its box, as if chosen, once the checker is ready, and refused before.
// A file dropped where nothing takes it is not opened by the browser in place of the page,
// which would lose what the reader set; the outputs' box and the words' box take a drop as
// the browser has them do (round 1 of #633).
const dropBox = $("paper").closest("label");
const carriesFiles = (event) => [...(event.dataTransfer?.types || [])].includes("Files");
// Only a box that can take a drop takes it; a disabled one, while the checker loads, does not
// (round 2 of #633).
const takesItsOwn = (target) => target instanceof Element
  && target.closest("#against:not(:disabled), #known:not(:disabled)");
for (const name of ["dragenter", "dragover"]) {
  dropBox.addEventListener(name, (event) => {
    if (!carriesFiles(event)) return;
    event.preventDefault();
    // While the checker loads the drop still fires, so that the page can say why it was not
    // taken (round 2 of #633).
    if (!$("paper").disabled) dropBox.classList.add("dropping");
  });
}
dropBox.addEventListener("dragleave", (event) => {
  if (!dropBox.contains(event.relatedTarget)) dropBox.classList.remove("dropping");
});
dropBox.addEventListener("drop", (event) => {
  dropBox.classList.remove("dropping");
  if (!carriesFiles(event)) return;
  event.preventDefault();
  if ($("paper").disabled) {
    say("The checker is still loading: drop the paper again once the page says Ready.");
    return;
  }
  const [file] = event.dataTransfer.files;
  if (!file) return;
  if (!/\.(docx|md)$/i.test(file.name)) {
    say(`${file.name} is not a .docx or a .md file: drop or choose the paper itself.`);
    return;
  }
  const chosen = new DataTransfer();
  chosen.items.add(file);
  $("paper").files = chosen.files;
  $("paper").dispatchEvent(new Event("change", { bubbles: true }));
});
for (const name of ["dragover", "drop"]) {
  window.addEventListener(name, (event) => {
    if (!dropBox.contains(event.target) && !takesItsOwn(event.target)) event.preventDefault();
  });
}

// What an audit under way says, beside the button that started it: the paper, and the
// seconds it has taken, with a bar that moves without a measure, since the audit runs in one
// call the page cannot look inside. The text a screen reader says is set at the start and at
// the end, not at each second.
const running = { timer: null, started: 0 };
function runStarted(name) {
  $("running").hidden = false;
  $("runbar").hidden = false;
  $("runtext").textContent = `Auditing ${name}…`;
  running.started = performance.now();
  $("elapsed").textContent = "";
  running.timer = setInterval(() => {
    $("elapsed").textContent = `${Math.round((performance.now() - running.started) / 1000)} s`;
  }, 1000);
}
function runEnded(said) {
  clearInterval(running.timer);
  $("runbar").hidden = true;
  $("elapsed").textContent = "";
  $("runtext").textContent = said;
}

$("form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const paper = $("paper").files[0];
  if (!paper) return;
  $("run").disabled = true;
  // The last report goes before this run starts, so that a run refused or failed leaves none
  // on screen for "Save the report" to save as this one's (round 2 of #527).
  $("result").hidden = true;
  $("savecommented").hidden = true;
  $("savepdf").hidden = true;
  $("openpdf").hidden = true;
  commented = null;
  pdf = null;
  if (pdfAddress) URL.revokeObjectURL(pdfAddress);
  pdfAddress = null;
  $("report").textContent = "";
  $("view").replaceChildren();
  $("notes").textContent = "";
  runStarted(paper.name);
  try {
    const result = await ask("run", {
      paper: await read(paper),
      against: await Promise.all([...$("against").files].map(read)),
      lookup: $("lookup").checked,
      details: $("details").checked,
      english: $("english").value,
      // The words to leave alone, as typed: split at spaces, commas and semicolons.
      known: $("known").value.split(/[\s,;]+/).filter(Boolean),
    });
    $("result").hidden = false;
    $("report").textContent = result.out;
    draw(result.view);
    $("notes").hidden = !result.err;
    $("notes").textContent = result.err;
    if (result.commented && result.commented.error) {
      $("notes").hidden = false;
      $("notes").textContent += (result.err ? "\n" : "")
        + `No copy of the paper with comments was made: ${result.commented.error}`;
    }
    if (result.commented && result.commented.data) {
      commented = result.commented;
      $("savecommented").hidden = false;
      // The file's name is the download's; the button says what is in it.
      $("savecommented").textContent = `Save the paper with its ${commented.placed} `
        + "finding" + (commented.placed === 1 ? "" : "s") + " as Word comments";
      $("savecommented").title = commented.name;
    }
    if (result.pdf && result.pdf.data) {
      pdf = result.pdf;
      $("savepdf").hidden = false;
      $("openpdf").hidden = false;
    } else if (result.pdf && result.pdf.error) {
      $("notes").hidden = false;
      $("notes").textContent += ($("notes").textContent ? "\n" : "")
        + `No PDF of the report was made: ${result.pdf.error}`;
    }
    $("netlog").textContent += "\n\n" + listRequests(
      `This audit of ${paper.name} sent requests to:`, result.sent);
    runEnded(`Audited ${paper.name} in ${(result.ms / 1000).toFixed(1)} s: the report is below.`);
    // The report, where the reader's eyes and a keyboard's focus go next.
    $("reporthead").scrollIntoView({ block: "start" });
    $("reporthead").focus({ preventScroll: true });
    window.mgLast = result;
  } catch (error) {
    // What the checker said, which says why, and where to read more; no guess at the cause,
    // which may be any file chosen (round 1 of #633).
    runEnded(`The audit could not run: ${error.message.replace(/[\s.]+$/, "")}. The command `
      + "line says more: uvx manuscript-guard audit paper.docx");
    window.mgLast = { error: error.message };
  } finally {
    $("run").disabled = false;
  }
});

// The report as a PDF (`web.report_pdf`), from the last audit: shown in a tab of its own,
// by the browser's PDF viewer, or saved. Its address lasts until the next audit.
let pdf = null;
let pdfAddress = null;
$("openpdf").addEventListener("click", () => {
  if (!pdf) return;
  pdfAddress = pdfAddress || URL.createObjectURL(new Blob([pdf.data], { type: "application/pdf" }));
  window.open(pdfAddress, "_blank");
});
$("savepdf").addEventListener("click", () => {
  if (!pdf) return;
  const link = document.createElement("a");
  link.href = URL.createObjectURL(new Blob([pdf.data], { type: "application/pdf" }));
  link.download = pdf.name;
  link.click();
  URL.revokeObjectURL(link.href);
});

// The paper with the findings as Word comments (`web.commented`), from the last audit.
let commented = null;
$("savecommented").addEventListener("click", () => {
  if (!commented) return;
  const link = document.createElement("a");
  link.href = URL.createObjectURL(new Blob([commented.data], {
    type: "application/vnd.openxmlformats-officedocument.wordprocessingml.document" }));
  link.download = commented.name;
  link.click();
  URL.revokeObjectURL(link.href);
});

$("save").addEventListener("click", () => {
  const link = document.createElement("a");
  link.href = URL.createObjectURL(new Blob([$("report").textContent], { type: "text/plain" }));
  link.download = "audit-report.txt";
  link.click();
  URL.revokeObjectURL(link.href);
});

// Tries what the page's policy must refuse, and shows that it did. Nothing is carried. One
// counts as refused only where the browser reports refusing it under the policy, as in
// worker.js: an image can fail to load, and a worker to start, for other reasons.
const ATTEMPTS = {
  "fetch from the page to example.com": "https://example.com/probe-page",
  "image from example.com": "https://example.com/probe-image.ico",
  // A worker started from a file would run under no policy (worker.js says why).
  "worker started from a file": new URL("probe.js", location.href).href,
};

$("probe").addEventListener("click", async () => {
  await booted;
  try { await fetch(ATTEMPTS["fetch from the page to example.com"], { mode: "no-cors" }); } catch { /* judged below */ }
  await new Promise((resolve) => {
    const image = new Image();
    image.onload = image.onerror = resolve;
    image.src = ATTEMPTS["image from example.com"];
  });
  await new Promise((resolve) => {
    try {
      const other = new Worker(ATTEMPTS["worker started from a file"]);
      other.onmessage = other.onerror = () => { other.terminate(); resolve(); };
      setTimeout(() => { other.terminate(); resolve(); }, 3000);
    } catch { resolve(); }
  });
  const fromWorker = await ask("probe");
  const tried = Object.fromEntries(Object.entries(ATTEMPTS).map(([what, url]) => [what,
    pageRefused.some((report) => report.url && report.url.startsWith(url))
      ? "refused by the rules" : "NOT refused by the rules"]));
  Object.assign(tried, fromWorker.tried);
  window.mgProbe = { tried, refused: [...pageRefused, ...fromWorker.refused] };
  const held = Object.values(tried).every((how) => how === "refused by the rules");
  $("probelog").hidden = false;
  $("probelog").textContent =
    (held ? "The browser refused each of these under the page's rules:\n"
      : "NOT every one of these was refused under the page's rules:\n") +
    Object.entries(tried).map(([what, how]) => `  ${what}: ${how}`).join("\n");
});
