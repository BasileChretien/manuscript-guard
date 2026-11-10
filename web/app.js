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
worker.onmessage = ({ data }) => {
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

const started = performance.now();
const booted = ask("boot").then((boot) => {
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
  for (const id of ["paper", "against", "lookup", "details", "run"]) $(id).disabled = false;
  window.mgReady = true;
}).catch((error) => say(`The checker could not start: ${error.message}`));

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
  if (view.strict) add(box, "p", view.strict, "small");
  for (const paper of view.words) {
    if (!paper.note && !paper.kinds.length) continue;
    add(box, "h3", `Writing and language: ${paper.paper} (not counted by --strict)`);
    if (paper.note) {
      add(box, "p", paper.note);
      continue;
    }
    for (const kind of paper.kinds) {
      const fold = add(box, "details", undefined, "kind");
      add(fold, "summary", `${kind.title} (${kind.gate}, ${kind.count})`);
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

$("form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const paper = $("paper").files[0];
  if (!paper) return;
  $("run").disabled = true;
  // The last report goes before this run starts, so that a run refused or failed leaves none
  // on screen for "Save the report" to save as this one's (round 2 of #527).
  $("result").hidden = true;
  $("report").textContent = "";
  $("view").replaceChildren();
  $("notes").textContent = "";
  say(`Auditing ${paper.name}…`);
  try {
    const result = await ask("run", {
      paper: await read(paper),
      against: await Promise.all([...$("against").files].map(read)),
      lookup: $("lookup").checked,
      details: $("details").checked,
    });
    $("result").hidden = false;
    $("report").textContent = result.out;
    draw(result.view);
    $("notes").hidden = !result.err;
    $("notes").textContent = result.err;
    $("netlog").textContent += "\n\n" + listRequests(
      `This audit of ${paper.name} sent requests to:`, result.sent);
    say(`Audited ${paper.name} in ${(result.ms / 1000).toFixed(1)} s.`);
    window.mgLast = result;
  } catch (error) {
    say(`The audit could not run: ${error.message}`);
    window.mgLast = { error: error.message };
  } finally {
    $("run").disabled = false;
  }
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
