// The checker: Pyodide, the manuscript-guard wheel and pandoc.wasm, in a module worker.
//
// app.js starts this worker from a blob: URL, with `const BASE = "<the page's folder>";`
// put before this text. That is what keeps it under the page's Content-Security-Policy: a
// worker started from a blob: URL takes the policy of the page that made it, while one
// started from a file on a host that sends no policy header, as GitHub Pages sends none,
// runs under no policy at all. The page's policy allows no other kind of worker.
const now = () => performance.now();
// What the browser refused under the page's policy, as it reported it.
const refused = [];
self.addEventListener("securitypolicyviolation", (event) =>
  refused.push({ rule: event.effectiveDirective, url: event.blockedURI }));
performance.setResourceTimingBufferSize(10000);
let py;

// Where the start has got to, for the page to show while it waits: a message with no id,
// which answers no question (app.js).
const BOOT_STEPS = ["Python", "the Python packages and manuscript-guard",
  "pandoc, which reads a .docx (16 MB)", "the checker itself"];
const step = (at) => self.postMessage({ progress: { at: at + 1, of: BOOT_STEPS.length, what: BOOT_STEPS[at] } });

// The bytes the start has received, against those the manifest says it fetches (web/build.py,
// `bytes`), for the page's percentage: each answer's body counted as it arrives, while the
// start runs and no longer. A message with no id, as a step's, at most every 100 ms.
const loading = { received: 0, expected: 0, said: 0 };
// The browser's own fetch, taken when the start begins.
let ownFetch = null;
function tell(last = false) {
  if (!last && now() - loading.said < 100) return;
  loading.said = now();
  self.postMessage({ bytes: { received: loading.received, expected: loading.expected } });
}
// The answer itself goes on, as fetched, so that the browser keeps what it keeps of it by its
// address (Chrome's compiled WebAssembly, round 1 of #633); a copy of its body is read to count
// it. Each copy still being read is awaited before the last count is told.
const reading = new Set();
const readers = new Set();
async function counted(input, init) {
  const answer = await ownFetch(input, init);
  if (!answer.body) return answer;
  const reader = answer.clone().body.getReader();
  readers.add(reader);
  const read = (async () => {
    for (;;) {
      const { done, value } = await reader.read();
      if (done) return;
      loading.received += value.byteLength;
      tell();
    }
  })().catch(() => { /* a copy that fails to read counts no further */ });
  reading.add(read);
  read.finally(() => reading.delete(read));
  return answer;
}

async function boot() {
  ownFetch = self.fetch.bind(self);
  self.fetch = counted;
  try {
    const value = await started();
    await Promise.allSettled([...reading]);
    return value;
  } catch (error) {
    // A start that failed says so at once: the copies still being counted are let go, not
    // waited for to the end of their files (round 2 of #633).
    for (const reader of readers) reader.cancel().catch(() => { /* gone already */ });
    throw error;
  } finally {
    self.fetch = ownFetch;
    tell(true);
  }
}

async function started() {
  const timings = {};
  let start = now();
  step(0);
  const manifest = await (await fetch(BASE + "manifest.json")).json();
  loading.expected = manifest.bytes || 0;
  const { loadPyodide } = await import(BASE + "pyodide/pyodide.mjs");
  py = await loadPyodide({ indexURL: BASE + "pyodide/" });
  timings.python = now() - start;

  start = now();
  step(1);
  await py.loadPackage(manifest.load, { messageCallback: () => {} });
  py.unpackArchive(await (await fetch(BASE + manifest.wheel)).arrayBuffer(), "wheel");
  timings.packages = now() - start;

  start = now();
  step(2);
  const { createPandoc } = await import(BASE + "pandoc/pandoc.mjs");
  const pandoc = await createPandoc(await WebAssembly.compileStreaming(fetch(BASE + "pandoc/pandoc.wasm")));
  timings.pandoc = now() - start;

  start = now();
  step(3);
  py.globals.set("PANDOC_JS", pandoc);
  const pandocVersion = py.runPython(`
from manuscript_guard import web
import manuscript_guard.cli
web.install(PANDOC_JS)
`);
  py.globals.delete("PANDOC_JS");
  timings.imports = now() - start;
  return { manifest, pandocVersion, timings, loaded: requests() };
}

// Every request this worker made, as the browser recorded it.
function requests() {
  return performance.getEntriesByType("resource").map((entry) => ({
    url: entry.name, sent: entry.transferSize, size: entry.decodedBodySize,
  }));
}

// Each file under the name the reader gave it, so that the report names it as the command
// line would. A name is not changed to make it fit: two names made one would put one file
// over the other, and the audit would read one file twice and the other not at all.
function names(files) {
  const given = files.map((file) => file.name);
  for (const name of given) {
    if (!name || name === "." || name === ".." || /[/\0]/.test(name)) {
      throw new Error(`the checker cannot use a file named "${name}": rename it`);
    }
  }
  const twice = given.find((name, at) => given.indexOf(name) !== at);
  if (twice) {
    throw new Error(`two of the files chosen are named ${twice}: rename one, as a command line `
      + "could not be given both either");
  }
  return given;
}

// A name that starts with "-" would be read as an option; "./" before it is the same file.
const argument = (name) => (name.startsWith("-") ? "./" + name : name);

// A step of the audit under way, as the page draws it (app.js `stepped`): its key, and how
// many of its items are done of how many, where it counts them.
const told = (key, done, total) => self.postMessage({ step: { key, done, total } });

// The designs `audit --design` takes, the only values the page passes it.
const DESIGNS = ["observational", "trial"];
// Labels of table rows, as typed, one a line: those that would be read as an option go, as a
// word to leave alone does.
const labels = (typed) => typed.map((label) => label.trim())
  .filter((label) => label && !label.startsWith("-"));

// The names the page gives the files its journal form makes, which no file chosen may have.
const FORM_FILES = { profile: "journal.yaml", authors: "authors.yaml" };

// The journal's profile and the authors' names the form describes, as `audit --journal` and
// `--authors` read them (`web.journal_files`), where no file of the reader's stands in for
// them: the text of each, by the name it is written under. Refused, before anything is
// written, where the form cannot make one or a file chosen has its name.
function formFiles(journal, authors, chosen) {
  const wanted = { profile: journal, authors };
  const clash = Object.entries(FORM_FILES).find(([kind, name]) => wanted[kind] && chosen.includes(name));
  if (clash) {
    throw new Error(`a file chosen is named ${clash[1]}, the name the page gives the `
      + `${clash[0] === "profile" ? "journal's profile" : "authors' names"} it makes: rename it`);
  }
  if (!journal && !authors) return {};
  py.globals.set("JOURNAL", journal ? py.toPy(journal) : null);
  py.globals.set("AUTHORS", authors ? py.toPy(authors) : null);
  const said = JSON.parse(py.runPython(`import json
from manuscript_guard import web
json.dumps(web.journal_files(JOURNAL, AUTHORS))`));
  py.globals.delete("JOURNAL");
  py.globals.delete("AUTHORS");
  if (said.error) throw new Error(`the journal's form: ${said.error}`);
  return Object.fromEntries(Object.keys(FORM_FILES).filter((kind) => said[kind] !== undefined)
    .map((kind) => [FORM_FILES[kind], said[kind]]));
}

function run({ paper, against, lookup, details, english = "", known = [], noAbstract = false,
  noResults = false, results = "", tracked = false, design = "", wholeNumbers = [],
  binary = [], nonNegative = [], minimumCellCount = "", journal = null, journalFile = null,
  authors = null, authorsFile = null }) {
  const own = [journalFile, authorsFile].filter(Boolean);
  const chosen = names([paper, ...against, ...own]);
  const [paperName, ...outputNames] = chosen.slice(0, 1 + against.length);
  const made = formFiles(journalFile ? null : journal, authorsFile ? null : authors, chosen);
  py.runPython(`import os, shutil
os.chdir("/")
shutil.rmtree("/work", ignore_errors=True)
os.makedirs("/work", exist_ok=True)
os.chdir("/work")`);
  py.FS.writeFile("/work/" + paperName, new Uint8Array(paper.data));
  const args = ["audit", argument(paperName)];
  if (against.length) {
    args.push("--against");
    against.forEach((file, at) => {
      py.FS.writeFile("/work/" + outputNames[at], new Uint8Array(file.data));
      args.push(argument(outputNames[at]));
    });
  }
  for (const file of own) py.FS.writeFile("/work/" + file.name, new Uint8Array(file.data));
  for (const [name, text] of Object.entries(made)) py.FS.writeFile("/work/" + name, text);
  // The journal's rules and the authors' names, a file of the reader's or the form's.
  const profileName = journalFile ? journalFile.name : made[FORM_FILES.profile] && FORM_FILES.profile;
  const authorsName = authorsFile ? authorsFile.name : made[FORM_FILES.authors] && FORM_FILES.authors;
  if (profileName) args.push("--journal", argument(profileName));
  if (authorsName) args.push("--authors", argument(authorsName));
  if (english) args.push("--english", english);
  // A word that starts with "-" would be read as an option; one such word is no word.
  const words = known.filter((word) => !word.startsWith("-"));
  if (words.length) args.push("--known", ...words);
  if (noAbstract) args.push("--no-abstract");
  if (noResults) args.push("--no-results");
  // Joined to its flag, so that a heading that starts with "-" is read as the heading.
  if (results) args.push(`--results=${results}`);
  // A referee's or an editor's: the study's design, and the table rows to hold to their
  // kind of number (`--whole-numbers`, `--binary`, `--non-negative`), each flag once with
  // its labels, and the data custodian's minimum count.
  if (DESIGNS.includes(design)) args.push("--design", design);
  for (const [flag, typed] of [["--whole-numbers", wholeNumbers], ["--binary", binary],
    ["--non-negative", nonNegative]]) {
    const rows = labels(typed);
    if (rows.length) args.push(flag, ...rows);
  }
  if (/^[1-9][0-9]{0,5}$/.test(String(minimumCellCount))) {
    args.push("--minimum-cell-count", String(minimumCellCount));
  }
  if (lookup) args.push("--lookup");
  if (details) args.push("--details");
  // The copy with G14's corrections as tracked changes, for a .docx, where the reader asked
  // for it: worked out only then (Basile, 2026-11-12, "only when asked").
  const correcting = Boolean(tracked) && /\.docx$/i.test(paperName);
  performance.clearResourceTimings();
  py.globals.set("ARGS", py.toPy(args));
  py.globals.set("CORRECTED", correcting);
  // Each step the audit says as it starts (`auditing.progress`), passed to the page, which
  // shows what is being done and how long is left: the audit runs in this one call.
  py.globals.set("TOLD", told);
  const start = now();
  // The text the command line prints, and the report as the page draws it, from one audit.
  const result = JSON.parse(py.runPython(`import json
from manuscript_guard import web
from manuscript_guard.auditing import progress
progress.STEP = TOLD
try:
    said = json.dumps(web.view(ARGS, corrected=CORRECTED))
finally:
    progress.STEP = None
said`));
  py.globals.delete("ARGS");
  py.globals.delete("TOLD");
  py.globals.delete("CORRECTED");
  const ms = now() - start;
  // A copy or a PDF that could not be written never costs the report (round 1 of #617).
  let pdf = null;
  try {
    told("pdf", 0, 0);
    pdf = reportPdf(result, paperName);
  } catch (error) {
    pdf = { error: String((error && error.message) || error) };
  }
  let commented = null;
  try {
    if (/\.docx$/i.test(paperName)) told("copy", 0, 0);
    commented = commentedCopy(result, paperName);
  } catch (error) {
    commented = { error: String((error && error.message) || error) };
  }
  let trackedCopy = null;
  if (correcting) {
    try {
      told("tracked", 0, 0);
      trackedCopy = commentedCopy(result, paperName, true);
    } catch (error) {
      trackedCopy = { error: String((error && error.message) || error) };
    }
  }
  return { ...result, commented, tracked: trackedCopy, pdf, args, made, ms, sent: requests(),
    refused: [...refused] };
}

// The report as a PDF with every place and every section, from that very audit
// (`web.report_pdf`, as `audit --pdf` writes it): its name and its bytes; or null.
function reportPdf(result, paperName) {
  if (!result.view) return null;
  const said = JSON.parse(py.runPython(`import json, os
from manuscript_guard import web
os.makedirs("/out", exist_ok=True)
json.dumps(web.report_pdf("/out/report.pdf"))`));
  if (said.error) return { error: said.error };
  return { name: paperName.replace(/\.[^.]*$/, "") + " (audit report).pdf",
    data: py.FS.readFile("/out/report.pdf") };
}

// The paper with the audit's findings as Word comments at their places, for a .docx the audit
// drew a report of, written from that very audit (`web.commented`, as `audit --commented`
// writes it): its name, its bytes and how many comments stand at their places; or null.
// `tracked`, with G14's corrections as tracked changes as well (`audit --tracked`), and how
// many of them there are.
function commentedCopy(result, paperName, tracked = false) {
  if (!result.view || !/\.docx$/i.test(paperName)) return null;
  const file = tracked ? "/out/tracked.docx" : "/out/commented.docx";
  py.globals.set("PAPER", paperName);
  py.globals.set("COPY", file);
  py.globals.set("TRACKED", tracked);
  const said = JSON.parse(py.runPython(`import json, os
from manuscript_guard import web
os.makedirs("/out", exist_ok=True)
# The last run's copy goes: the copy is never written over (fix round of #617).
if os.path.exists(COPY): os.remove(COPY)
json.dumps(web.commented(PAPER, COPY, tracked=TRACKED))`));
  for (const name of ["PAPER", "COPY", "TRACKED"]) py.globals.delete(name);
  if (said.error) return { error: said.error };
  const stem = paperName.replace(/\.docx$/i, "");
  return { ...said, name: stem + (tracked ? " (tracked changes).docx" : " (commented).docx"),
    data: py.FS.readFile(file) };
}

// Requests the page's policy must refuse, made from this worker. None carries anything. One
// counts as refused only where the browser reports refusing it under the policy: a request
// can fail for other reasons (example.com answers no XMLHttpRequest from a page, and has no
// WebSocket server), and a failure is not the rule holding.
const ATTEMPTS = {
  "fetch to example.com": "https://example.com/probe-fetch",
  "fetch to github.com": "https://github.com/probe-fetch",
  "XMLHttpRequest to example.com": "https://example.com/probe-xhr",
  "WebSocket to example.com": "wss://example.com/probe-socket",
};

function judged(attempts, reports) {
  return Object.fromEntries(Object.entries(attempts).map(([what, url]) => [what,
    reports.some((report) => report.url && report.url.startsWith(url))
      ? "refused by the rules" : "NOT refused by the rules"]));
}

async function probe() {
  const settle = () => new Promise((resolve) => setTimeout(resolve, 300));
  try { await fetch(ATTEMPTS["fetch to example.com"], { mode: "no-cors" }); } catch { /* judged below */ }
  try { await fetch(ATTEMPTS["fetch to github.com"], { mode: "no-cors" }); } catch { /* judged below */ }
  try {
    const xhr = new XMLHttpRequest();
    xhr.open("GET", ATTEMPTS["XMLHttpRequest to example.com"], false);
    xhr.send();
  } catch { /* judged below */ }
  await new Promise((resolve) => {
    try {
      const socket = new WebSocket(ATTEMPTS["WebSocket to example.com"]);
      socket.onopen = () => { socket.close(); resolve(); };
      socket.onerror = () => resolve();
    } catch { resolve(); }
  });
  await settle();
  return { tried: judged(ATTEMPTS, refused), refused: [...refused] };
}

self.onmessage = async ({ data: { id, type, payload } }) => {
  try {
    const value = type === "boot" ? await boot() : type === "run" ? run(payload) : await probe();
    self.postMessage({ id, value });
  } catch (error) {
    self.postMessage({ id, error: String((error && error.message) || error) });
  }
};
