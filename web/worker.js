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

async function boot() {
  const timings = {};
  let start = now();
  const manifest = await (await fetch(BASE + "manifest.json")).json();
  const { loadPyodide } = await import(BASE + "pyodide/pyodide.mjs");
  py = await loadPyodide({ indexURL: BASE + "pyodide/" });
  timings.python = now() - start;

  start = now();
  await py.loadPackage(manifest.load, { messageCallback: () => {} });
  py.unpackArchive(await (await fetch(BASE + manifest.wheel)).arrayBuffer(), "wheel");
  timings.packages = now() - start;

  start = now();
  const { createPandoc } = await import(BASE + "pandoc/pandoc.mjs");
  const pandoc = await createPandoc(await WebAssembly.compileStreaming(fetch(BASE + "pandoc/pandoc.wasm")));
  timings.pandoc = now() - start;

  start = now();
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

function run({ paper, against, lookup, details }) {
  const [paperName, ...outputNames] = names([paper, ...against]);
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
  if (lookup) args.push("--lookup");
  if (details) args.push("--details");
  performance.clearResourceTimings();
  py.globals.set("ARGS", py.toPy(args));
  const start = now();
  // The text the command line prints, and the report as the page draws it, from one audit.
  const result = py.runPython("import json; from manuscript_guard import web; json.dumps(web.view(ARGS))");
  py.globals.delete("ARGS");
  return { ...JSON.parse(result), args, ms: now() - start, sent: requests(), refused: [...refused] };
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
