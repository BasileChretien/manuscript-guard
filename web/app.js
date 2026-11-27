// The page: start the checker, hand it the files the reader chooses, show what it says.
// Nothing here sends anything anywhere; the checker runs in worker.js, in this browser.
import { RULES, packed, shaped, unpacked } from "./rules.js";

const $ = (id) => document.getElementById(id);
const say = (text) => { $("status").textContent = text; };
// What the browser refused under the page's policy, as it reported it.
const pageRefused = [];
window.mgRefused = pageRefused;  // what web/test/browser.mjs reads
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
let started = false;
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
  started = true;
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
    if (started) showBar();
    return;
  }
  if (data.step) {
    stepped(data.step);
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
  if (!started) {
    loaded();
    say(`The checker could not start: ${what}`);
    return;
  }
  met = what;
  say(`The checker met an error while loading (${what}). It may still start; if nothing `
    + "changes, reload the page.");
};

// Which release this page is, at the top, where a reader sees that it moved on. A page a
// journal's host built is built when the host builds it, and says which release runs it.
const manifestRead = fetch("manifest.json").then((answer) => answer.json());
manifestRead.then((manifest) => {
  const version = $("version");
  version.textContent = manifest.host
    ? `Run by manuscript-guard ${manifest.manuscript_guard} (`
    : `manuscript-guard ${manifest.manuscript_guard}, rebuilt with each new release (`;
  const link = add(version, "a", manifest.host ? "what this release changed" : "what changed");
  link.href = manifest.sources["manuscript-guard"].replace("/tree/", "/releases/tag/");
  version.append(")");
}).catch((error) => { $("version").textContent += ` (its version could not be read: ${error.message})`; });

// A page a journal's host built (web/build.py --host): its name, logo, accent and contact,
// and the journals it offers, from manifest.json and the host's files, each set as text,
// never as markup. Each journal's profile is fetched before the page says Ready, so that a
// reader who turns the network off, as the page invites, still has it.
const journals = new Map();
// The journal a link names, ?journal=<slug>: of the address, this and a link's rules after
// "#rules=" are all that is read, and the page never writes to it.
const wanted = new URLSearchParams(location.search).get("journal") || "";
const hostLoaded = manifestRead.then(async (manifest) => {
  const host = manifest.host;
  if (host) {
    document.title = `Check your paper · ${host.name}`;
    $("kicker").textContent = `${host.name} · paper check-up`;
    if (host.logo) {
      $("hostlogo").src = host.logo;
      $("hostlogo").hidden = false;
    }
    if (host.style) {
      const style = document.createElement("link");
      style.rel = "stylesheet";
      style.href = host.style;
      document.head.append(style);
    }
    if (host.contact) {
      $("contact").textContent = `${host.name}: ${host.contact.text} `;
      const link = add($("contact"), "a", host.contact.shown);
      link.href = host.contact.link;
      $("contact").hidden = false;
    }
    const loaded = await Promise.all(host.journals.map(async (journal) => {
      const answer = await fetch(journal.file);
      if (!answer.ok) throw new Error(`${journal.name}'s rules (${journal.file}) could not be loaded`);
      const data = await answer.arrayBuffer();
      return { ...journal, data, text: new TextDecoder().decode(data) };
    }));
    const other = $("journal").querySelector('option[value="other"]');
    for (const journal of loaded) {
      journals.set(journal.slug, journal);
      const option = document.createElement("option");
      option.value = journal.slug;
      option.textContent = journal.name;
      other.before(option);
    }
    $("journalpick").hidden = !journals.size;
  }
  if (wanted && journals.has(wanted)) {
    $("journal").value = wanted;
    journalPicked();
  } else if (wanted) {
    // Said as text, and no longer than a slug can be.
    $("journalnote").textContent = journals.size
      ? `This page offers no journal "${wanted.slice(0, 64)}": choose yours from the list.`
      : `This page offers no journal's own rules, so "${wanted.slice(0, 64)}" was not chosen: `
        + 'type its rules under "For a journal".';
    $("journalnote").hidden = false;
  }
});
window.mgJournals = journals;  // what web/test/browser.mjs reads

const booting = performance.now();
const booted = Promise.all([ask("boot"), hostLoaded]).then(([boot]) => {
  loaded();
  const seconds = ((performance.now() - booting) / 1000).toFixed(1);
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
  for (const id of ["journal", "paper", "tracked", "against", "english", "known", "noabstract",
    "noresults", "results", "lookup", "design", "wholenumbers", "binary", "nonnegative",
    "mincount", "run", "example"]) {
    $(id).disabled = false;
  }
  // The authors' boxes among them, wherever a journal chosen has put them.
  for (const box of [...$("journalbox").querySelectorAll("input, select, textarea, button"),
    ...$("blindbox").querySelectorAll("input, button, textarea")]) {
    box.disabled = false;
  }
  window.mgReady = true;
  if (linkedRules !== null) rulesOpened(linkedRules);
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
  if (!/\.(docx|md|zip|tar\.gz|tgz)$/i.test(file.name)) {
    say(`${file.name} is not a .docx, a .md, or a LaTeX project's .zip or .tar.gz: drop or `
      + "choose the paper itself.");
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

// The paper chosen, said in its box, so that the reader sees it was taken; and for a .docx,
// the box for the copy with its corrections tracked, which only a Word document can have.
const isDocx = (name) => /\.docx$/i.test(name);
$("paper").addEventListener("change", () => {
  const file = $("paper").files[0];
  $("chosen").hidden = !file;
  $("chosen").textContent = file ? `${file.name} (${megabytes(file.size)}), ready to check` : "";
  $("trackedbox").hidden = !(file && isDocx(file.name));
});

// What a check under way says: each step the audit says as it starts (worker.js `told`,
// `auditing.progress`), the one under way named, those done ticked, and the time left from
// how long the steps done took against how long they usually take. The text a screen reader
// says changes with the step, not with each second.
const STEPS = {
  read: ["Reading your paper", 4],
  numbers: ["Checking the numbers", 2],
  words: ["Reading the writing and the language", 6],
  lookup: ["Looking up the references", 0],
  report: ["Writing your report", 1.5],
  pdf: ["Making the PDF of the report", 2],
  copy: ["Making the Word copy with comments", 2],
  tracked: ["Making the Word copy with tracked changes", 3],
};
// How long one reference takes to look up, before any has been.
const PER_LOOKUP = 1.2;
const running = { timer: null, started: 0, order: [], at: {}, now: null, done: 0, total: 0 };
window.mgRunning = running;

function runStarted(name, { lookup, docx, tracked = false }) {
  const order = ["read", "numbers", "words", ...(lookup ? ["lookup"] : []), "report", "pdf",
    ...(docx ? ["copy"] : []), ...(docx && tracked ? ["tracked"] : [])];
  Object.assign(running, { order, at: {}, now: null, done: 0, total: 0, started: performance.now() });
  const list = $("steps");
  list.replaceChildren();
  for (const key of order) {
    const item = add(list, "li", STEPS[key][0]);
    item.dataset.step = key;
    add(item, "span", "", "count");
  }
  $("running").hidden = false;
  $("runbar").hidden = false;
  $("runbar").value = 0;
  $("runtext").textContent = `Checking ${name}…`;
  $("eta").textContent = "working out the time left";
  // The steps, where the reader can see them: below the button, under the fold on a laptop.
  $("running").scrollIntoView({ block: "nearest", behavior: scrolling() });
  running.timer = setInterval(showTimeLeft, 1000);
}

function stepped({ key, done, total }) {
  if (!STEPS[key] || !running.order.includes(key)) return;
  const at = performance.now();
  if (running.now !== key) {
    if (running.now) running.at[running.now].ended = at;
    running.at[key] = { started: at };
    running.now = key;
    $("runtext").textContent = `${STEPS[key][0]}…`;
  }
  if (key === "lookup") Object.assign(running, { done, total });
  for (const item of $("steps").children) {
    const step = item.dataset.step;
    const place = running.order.indexOf(step);
    const now = running.order.indexOf(running.now);
    item.className = place < now ? "done" : place === now ? "now" : "";
    item.querySelector(".count").textContent = step === "lookup" && running.total
      ? ` ${Math.min(running.done + (step === running.now ? 1 : 0), running.total)} of ${running.total}` : "";
  }
  showTimeLeft();
}

// How long each step is expected to take, the lookups by how many there are.
const expected = (key) => key === "lookup" ? PER_LOOKUP * (running.total || 20) : STEPS[key][1];

function showTimeLeft() {
  // Before the first step, nothing is done yet (the paper is still being handed over).
  if (!running.now) return;
  const elapsed = (performance.now() - running.started) / 1000;
  const all = running.order.reduce((sum, key) => sum + expected(key), 0);
  let behind = 0;
  for (const key of running.order) {
    if (key === running.now) {
      const into = (performance.now() - running.at[key].started) / 1000;
      behind += key === "lookup" && running.total
        ? expected(key) * running.done / running.total : Math.min(into, expected(key) * 0.9);
      break;
    }
    behind += expected(key);
  }
  $("runbar").value = Math.min(99, Math.round(100 * behind / all));
  if (!running.now || behind < 1) return;
  // This computer's pace so far, held between half and four times the usual one.
  const pace = Math.min(4, Math.max(0.5, elapsed / behind));
  const left = (all - behind) * pace;
  $("eta").textContent = left < 4 ? "almost done"
    : left < 90 ? `about ${Math.ceil(left / 5) * 5} s left`
      : `about ${Math.round(left / 60)} min left`;
}

// The check ended: its steps go, and so does the ring of the one under way. Where it failed,
// the steps' box stays, and its text is set once it is shown, for a screen reader to say it
// (round 1 of #644).
function runEnded(said, { failed = false } = {}) {
  clearInterval(running.timer);
  running.now = null;
  for (const item of $("steps").children) item.classList.remove("now");
  $("runbar").hidden = true;
  $("eta").textContent = "";
  $("running").hidden = !failed;
  $("runtext").textContent = said;
}

// A smooth scroll, unless the reader asked for less motion.
const scrolling = () => (matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth");

// Whether the browser shows a PDF inside a page: a desktop browser with its viewer on does;
// a phone opens it in a page of its own, or saves it.
const showsPdfHere = () => navigator.pdfViewerEnabled !== false
  && !matchMedia("(pointer: coarse) and (max-width: 48rem)").matches;

// The report as a PDF (`web.report_pdf`), from the last audit: shown in the page by the
// browser's own viewer, from an address of the browser's own that lasts until the next audit.
let pdf = null;
let pdfAddress = null;
function showReport(result, paper) {
  $("result").hidden = false;
  $("notes").hidden = !result.err;
  $("notes").textContent = result.err;
  const note = (said) => {
    $("notes").hidden = false;
    $("notes").textContent += ($("notes").textContent ? "\n" : "") + said;
  };
  if (result.commented && result.commented.error) {
    note(`No copy of the paper with comments was made: ${result.commented.error}`);
  }
  if (result.commented && result.commented.data) {
    commented = result.commented;
    $("savecommented").hidden = false;
    // The file's name is the download's; the button says what is in it.
    $("savecommented").textContent = `Download your paper with its ${commented.placed} `
      + "finding" + (commented.placed === 1 ? "" : "s") + " as Word comments";
    $("savecommented").title = commented.name;
  }
  if (result.tracked && result.tracked.error) {
    note(`No copy of the paper with tracked changes was made: ${result.tracked.error}`);
  }
  if (result.tracked && result.tracked.data) {
    tracked = result.tracked;
    $("savetracked").hidden = false;
    $("savetracked").textContent = `Download your paper with its ${tracked.tracked} `
      + "correction" + (tracked.tracked === 1 ? "" : "s") + " as tracked changes";
    $("savetracked").title = tracked.name;
  }
  if (result.pdf && result.pdf.data) {
    pdf = result.pdf;
    pdfAddress = URL.createObjectURL(new Blob([pdf.data], { type: "application/pdf" }));
    $("savepdf").hidden = false;
    if (showsPdfHere()) {
      $("pdfbox").hidden = false;
      // At the page's width, with the viewer's own contents and search a click away.
      $("pdfview").src = pdfAddress + "#view=FitH";
    } else {
      $("pdfnote").hidden = false;
      $("openpdf").hidden = false;
    }
  } else if (result.pdf && result.pdf.error) {
    note(`No PDF of the report was made: ${result.pdf.error}`);
  }
  // With no PDF there would be no report at all: the text the command line prints is shown
  // in its place, and can be saved (round 1 of #644).
  // This run's PDF, never one an earlier run left (round 2 of #644).
  const shown = Boolean(result.pdf && result.pdf.data);
  $("astext").hidden = shown;
  $("report").textContent = shown ? "" : result.out || "";
  $("done").textContent = `${paper} checked in ${(result.ms / 1000).toFixed(1)} s. `
    + outcome(result.view, shown);
}
window.mgShowReport = showReport;  // what web/test/browser.mjs shows a run with no PDF by
// What web/test/browser.mjs fails a check after a step by (round 2 of #644).
window.mgRun = { runStarted, stepped, runEnded };

// How the checks came out, in a sentence, from where each stands (`summary.standings`, the
// colours of the PDF's summary): the PDF below says the rest.
function outcome(view, inPdf = true) {
  const where = inPdf ? "Every finding and its place is in the report below."
    : "The PDF of the report could not be made here, so the report is below as text.";
  if (!view || !view.standing) return where;
  const states = Object.values(view.standing);
  const count = (state) => states.filter((each) => each === state).length;
  const checks = (n) => `${n} check${n === 1 ? "" : "s"}`;
  const said = [`${count("clear")} of ${checks(states.length)} found nothing`];
  if (count("look")) said.push(`${checks(count("look"))} found something for you to look at`);
  if (count("counted")) said.push(`${checks(count("counted"))} found something counted as an error`);
  if (count("not run")) said.push(`${checks(count("not run"))} could not run`);
  // The questions open, which never count as an error (Basile, 2026-11-17).
  const asked = Object.values(view.asked || {}).reduce((sum, n) => sum + n, 0);
  if (asked) said.push(`${asked} question${asked === 1 ? "" : "s"} for you to answer`);
  return `${said.join(", ")}. ${where}`;
}

// The last report goes before a check starts, so that a check refused or failed leaves none on
// screen as this one's (round 2 of #527).
function clearReport() {
  $("result").hidden = true;
  for (const id of ["savecommented", "savetracked", "savepdf", "openpdf", "pdfbox", "pdfnote",
    "astext"]) {
    $(id).hidden = true;
  }
  $("report").textContent = "";
  commented = null;
  tracked = null;
  pdf = null;
  $("pdfview").removeAttribute("src");
  if (pdfAddress) URL.revokeObjectURL(pdfAddress);
  pdfAddress = null;
  $("notes").textContent = "";
  $("done").textContent = "";
}

// The journal's form, as `web.journal_files` takes it: null where nothing in it is set. The
// date its instructions were read on is today's, in this computer's own time, or the one a
// link with its rules gave, until a box of the rules is changed.
const lines = (id) => $(id).value.split(/\r?\n/).map((line) => line.trim()).filter(Boolean);
const LIMIT_BOXES = { abstract_words: "jabstract", main_text_words: "jmain", figures: "jfigures",
  tables: "jtables", references: "jreferences", keywords: "jkeywords" };
function journalForm() {
  const today = new Date();
  const two = (n) => String(n).padStart(2, "0");
  const form = {
    name: $("jname").value.trim(),
    url: $("jurl").value.trim(),
    date: linked.date || `${today.getFullYear()}-${two(today.getMonth() + 1)}-${two(today.getDate())}`,
    limits: Object.fromEntries(Object.entries(LIMIT_BOXES).map(([key, id]) => [key, $(id).value.trim()])),
    sections: lines("jsections"),
    abstract_headings: lines("jheadings"),
    statements: [...document.querySelectorAll('input[name="jstatement"]:checked')].map((box) => box.value),
    blinding: $("jblinding").value,
  };
  // The heading the journal asks for each statement ticked under, as typed; left empty, the
  // usual one (`journal_form.STATEMENTS`).
  form.headings = Object.fromEntries(form.statements.map((id) => [id, $(`jsh-${id}`).value.trim()]));
  const set = form.name || form.url || Object.values(form.limits).some(Boolean) || form.sections.length
    || form.abstract_headings.length || form.statements.length || form.blinding;
  return set ? form : null;
}
// The authors the blind review's boxes name, as `web.journal_files` takes them: null where
// the boxes are not shown or nothing in them is set.
function authorsForm() {
  if ($("blindbox").hidden) return null;
  const authors = [...$("authorrows").children].map((row) => Object.fromEntries(
    ["given", "family", "orcid", "email"].map((key) => [key, row.querySelector(`[id$="-${key}"]`).value.trim()])));
  const affiliations = lines("affiliations");
  const set = authors.some((one) => Object.values(one).some(Boolean)) || affiliations.length;
  return set ? { authors, affiliations } : null;
}
// The journal the page offers that the reader chose, or a link chose (web/build.py --host),
// in place of the form and of a profile of the reader's: its profile as the host gave it.
const offered = () => journals.get($("journal").value) || null;
async function journalChosen() {
  const chosen = offered();
  const journalFile = !chosen && $("jfile").files[0] ? await read($("jfile").files[0]) : null;
  const authorsFile = !$("blindbox").hidden && $("authorsfile").files[0]
    ? await read($("authorsfile").files[0]) : null;
  return { journal: chosen || journalFile ? null : journalForm(), journalFile,
    offered: chosen ? { file: chosen.file, data: chosen.data } : null,
    authors: authorsFile ? null : authorsForm(), authorsFile };
}
// The authors' boxes, for a blind review or a profile of the reader's own, whose review the
// page cannot see; for a journal the page offers, where its profile says its review is blind.
const BLIND = ["double", "triple"];
const blindShown = () => {
  const chosen = offered();
  $("blindbox").hidden = chosen ? !BLIND.includes(chosen.blinding)
    : !(BLIND.includes($("jblinding").value) || $("jfile").files.length);
};
$("jblinding").addEventListener("change", blindShown);
$("jfile").addEventListener("change", blindShown);
// A journal the page offers, chosen: its rules shown as the check reads them, the form for
// another journal put away, and the authors' boxes under the list; "Another journal" opens
// the form. Nothing of the choice is kept between visits.
function journalPicked() {
  const chosen = offered();
  $("journalrules").hidden = !chosen;
  $("journaltext").textContent = chosen ? chosen.text : "";
  $("journalbox").hidden = Boolean(chosen);
  if ($("journal").value === "other") $("journalbox").open = true;
  if (chosen) $("journalpick").after($("blindbox"));
  else $("jblinding").closest("label").after($("blindbox"));
  $("journalnote").hidden = true;
  blindShown();
}
$("journal").addEventListener("change", journalPicked);

// A link with the journal's rules (web/rules.js; Basile, 2026-11-26): the form's values
// after "#rules=", the authors' names never among them. The page reads its own address and
// never writes it, and keeps nothing: the link is the reader's to keep and send.
const linkedRules = location.hash.startsWith(RULES) ? location.hash.slice(RULES.length) : null;
// The date the instructions were read on, as the link gave it.
const linked = { date: "" };
const rulesSaid = (text) => {
  $("rulesnote").textContent = text;
  $("rulesnote").hidden = !text;
};
// What the form offers, which a link's rules are held to.
const offeredBoxes = () => ({
  limits: Object.keys(LIMIT_BOXES),
  statements: [...document.querySelectorAll('input[name="jstatement"]')].map((box) => box.value),
  blindings: [...$("jblinding").options].map((option) => option.value).filter(Boolean),
});
// A box of the rules changed: they are the reader's now, read today. The authors' boxes, in
// the same part of the page, are none of them.
$("journalbox").addEventListener("input", (event) => {
  if (!$("blindbox").contains(event.target)) linked.date = "";
});
$("copyrules").addEventListener("click", async () => {
  const form = journalForm();
  if (!form) {
    rulesSaid("Type the journal's rules first: the link carries them.");
    return;
  }
  const link = `${location.origin}${location.pathname}${RULES}${await packed(form)}`;
  $("ruleslink").value = link;
  $("ruleslink").hidden = false;
  try {
    await navigator.clipboard.writeText(link);
    rulesSaid("Copied. Whoever opens the link has these rules in this form: not the authors' "
      + "names, nor anything of the paper.");
  } catch {
    $("ruleslink").select();
    rulesSaid("This browser did not let the page copy the link: copy it from the box above.");
  }
});
// The rules a link gave, once the checker is ready: held to the form's shape, then by the
// checker to the profile's schema (`web.journal_files`), as a profile the reader chooses is,
// and only then put in the form, or nothing put in it and why said.
async function rulesOpened(text) {
  try {
    const form = await unpacked(text);
    const wrong = shaped(form, offeredBoxes());
    if (wrong) throw new Error(wrong);
    await ask("rules", form);
    if (journals.size) {
      $("journal").value = "other";
      journalPicked();
    }
    $("jname").value = form.name || "";
    $("jurl").value = form.url || "";
    for (const [key, id] of Object.entries(LIMIT_BOXES)) $(id).value = (form.limits || {})[key] || "";
    $("jsections").value = (form.sections || []).join("\n");
    $("jheadings").value = (form.abstract_headings || []).join("\n");
    for (const box of document.querySelectorAll('input[name="jstatement"]')) {
      box.checked = (form.statements || []).includes(box.value);
      const heading = (form.headings || {})[box.value];
      if (heading) $(`jsh-${box.value}`).value = heading;
    }
    $("jblinding").value = form.blinding || "";
    blindShown();
    linked.date = form.date;
    $("journalbox").open = true;
    rulesSaid(`These rules came with the link, read from the journal's instructions on `
      + `${form.date}. Check them against the instructions before relying on them.`);
  } catch (error) {
    rulesSaid(`The link's rules were not put in the form: ${error.message.replace(/^the journal's form: /, "")}.`);
  }
  window.mgRulesRead = true;  // what web/test/browser.mjs waits for
}
// A row of boxes for one more author.
$("addauthor").addEventListener("click", () => {
  const number = $("authorrows").children.length + 1;
  const row = $("authorrows").firstElementChild.cloneNode(true);
  for (const box of row.querySelectorAll("input")) {
    const key = box.id.split("-").pop();
    box.id = `author-${number}-${key}`;
    box.value = "";
    box.setAttribute("aria-label", box.getAttribute("aria-label").replace(/^Author \d+/, `Author ${number}`));
  }
  $("authorrows").append(row);
  row.querySelector("input").focus();
});

async function check(paper) {
  $("run").disabled = true;
  $("example").disabled = true;
  clearReport();
  const lookup = $("lookup").checked;
  const docx = isDocx(paper.name);
  // Asked for a .docx only, where its box is shown.
  const wantsTracked = docx && $("tracked").checked;
  runStarted(paper.name, { lookup, docx, tracked: wantsTracked });
  try {
    const result = await ask("run", {
      paper: await read(paper),
      against: await Promise.all([...$("against").files].map(read)),
      lookup,
      details: false,
      english: $("english").value,
      // The words to leave alone, as typed: split at spaces, commas and semicolons.
      known: $("known").value.split(/[\s,;]+/).filter(Boolean),
      // The answers to the report's questions (`audit --no-abstract`, `--no-results`,
      // `--results`): one heading, as typed.
      noAbstract: $("noabstract").checked,
      noResults: $("noresults").checked,
      results: $("results").value.trim(),
      tracked: wantsTracked,
      // A referee's or an editor's (`--design`, `--whole-numbers`, `--binary`,
      // `--non-negative`, `--minimum-cell-count`).
      design: $("design").value,
      wholeNumbers: lines("wholenumbers"),
      binary: lines("binary"),
      nonNegative: lines("nonnegative"),
      minimumCellCount: $("mincount").value.trim(),
      // A journal's rules (`--journal`) and, for a blind review, the authors to look for
      // (`--authors`): the form's, or a file of the reader's.
      ...(await journalChosen()),
    });
    showReport(result, paper.name);
    $("netlog").textContent += "\n\n" + listRequests(
      `This check of ${paper.name} sent requests to:`, result.sent);
    runEnded(`Checked ${paper.name} in ${(result.ms / 1000).toFixed(1)} s: your report is below.`);
    // The report, where the reader's eyes and a keyboard's focus go next.
    $("reporthead").scrollIntoView({ block: "start", behavior: scrolling() });
    $("reporthead").focus({ preventScroll: true });
    window.mgLast = result;
  } catch (error) {
    // What the checker said, which says why, and where to read more; no guess at the cause,
    // which may be any file chosen (round 1 of #633).
    runEnded(`The check could not run: ${error.message.replace(/[\s.]+$/, "")}. The command `
      + "line says more: uvx manuscript-guard audit paper.docx", { failed: true });
    window.mgLast = { error: error.message };
  } finally {
    $("run").disabled = false;
    $("example").disabled = false;
  }
}

$("form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const paper = $("paper").files[0];
  if (paper) await check(paper);
});

// A short paper written for this page, with a few things to find in it, checked as a reader's
// paper is, so that a first visit sees what a report looks like.
$("example").addEventListener("click", async () => {
  // Not fetched at the start: a reader who turned the network off, as the page invites,
  // is told why nothing happens (round 1 of #644).
  let file;
  try {
    const answer = await fetch("example-paper.md");
    if (!answer.ok) throw new Error(`the page answered ${answer.status}`);
    file = new File([await answer.blob()], "example-paper.md", { type: "text/markdown" });
  } catch (error) {
    // No earlier steps or report left beside the message, as if they were this one's
    // (round 2 of #644).
    clearReport();
    $("steps").replaceChildren();
    $("runbar").hidden = true;
    $("eta").textContent = "";
    $("running").hidden = false;
    $("runtext").textContent = `The example paper could not be loaded (${error.message}): `
      + "it comes from this page's address, so it needs the network.";
    return;
  }
  await check(file);
});

$("again").addEventListener("click", () => {
  clearReport();
  $("form").scrollIntoView({ block: "start", behavior: scrolling() });
  $("paper").focus();
});

// Where the browser shows no PDF in a page: the report in a page of its own.
$("openpdf").addEventListener("click", () => {
  if (pdfAddress) window.open(pdfAddress, "_blank");
});
$("savepdf").addEventListener("click", () => {
  if (!pdf) return;
  const link = document.createElement("a");
  link.href = URL.createObjectURL(new Blob([pdf.data], { type: "application/pdf" }));
  link.download = pdf.name;
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

// A Word document the last audit wrote, saved under its name.
function saveDocx({ data, name }) {
  const link = document.createElement("a");
  link.href = URL.createObjectURL(new Blob([data], {
    type: "application/vnd.openxmlformats-officedocument.wordprocessingml.document" }));
  link.download = name;
  link.click();
  URL.revokeObjectURL(link.href);
}
// The paper with the findings as Word comments (`web.commented`), from the last audit; and
// where the reader asked for it, with G14's corrections as tracked changes too.
let commented = null;
let tracked = null;
$("savecommented").addEventListener("click", () => { if (commented) saveDocx(commented); });
$("savetracked").addEventListener("click", () => { if (tracked) saveDocx(tracked); });

// Tries what the page's policy must refuse, and shows that it did. Nothing is carried. One
// counts as refused only where the browser reports refusing it under the policy, as in
// worker.js: an image can fail to load, and a worker to start, for other reasons.
const ATTEMPTS = {
  "fetch from the page to example.com": "https://example.com/probe-page",
  "image from example.com": "https://example.com/probe-image.ico",
  // The one frame the page may show is the PDF it made itself, from a blob: address.
  "frame from example.com": "https://example.com/probe-frame",
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
    const frame = document.createElement("iframe");
    frame.hidden = true;
    frame.onload = () => { frame.remove(); resolve(); };
    setTimeout(() => { frame.remove(); resolve(); }, 3000);
    frame.src = ATTEMPTS["frame from example.com"];
    document.body.append(frame);
  });
  await new Promise((resolve) => {
    try {
      const other = new Worker(ATTEMPTS["worker started from a file"]);
      other.onmessage = other.onerror = () => { other.terminate(); resolve(); };
      setTimeout(() => { other.terminate(); resolve(); }, 3000);
    } catch { resolve(); }
  });
  const fromWorker = await ask("probe");
  // Chrome reports a frame from another origin refused by that origin alone,
  // "https://example.com", not by its address.
  const refused = (url) => pageRefused.some((report) => report.url
    && (report.url.startsWith(url)
      || (report.rule === "frame-src" && report.url === new URL(url).origin)));
  const tried = Object.fromEntries(Object.entries(ATTEMPTS).map(([what, url]) => [what,
    refused(url) ? "refused by the rules" : "NOT refused by the rules"]));
  Object.assign(tried, fromWorker.tried);
  window.mgProbe = { tried, refused: [...pageRefused, ...fromWorker.refused] };
  const held = Object.values(tried).every((how) => how === "refused by the rules");
  $("probelog").hidden = false;
  $("probelog").textContent =
    (held ? "The browser refused each of these under the page's rules:\n"
      : "NOT every one of these was refused under the page's rules:\n") +
    Object.entries(tried).map(([what, how]) => `  ${what}: ${how}`).join("\n");
});
