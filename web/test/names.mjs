// worker.js's `run`, in Node and without Pyodide: a stand-in `py` keeps the files it is given
// to write and the command it is asked to run, so that the names a reader chooses are seen to
// reach the command line as given (round 2 of #527: parity.mjs gives the command line its
// arguments itself, and never runs worker.js). tests/test_web.py runs this.
//
//   node web/test/names.mjs < cases.json
//
// Each case is {"paper": name, "against": [names]}, with "english", "known", "noAbstract",
// "noResults", "results", "tracked", "design", "wholeNumbers", "binary", "nonNegative",
// "minimumCellCount", "journal" and "authors" where the reader set them, "journalFile"
// and "authorsFile" by their names where the reader chose one, and "offered", the file of
// the journal the page offers that was chosen (web/build.py --host); each answer {"args",
// "written", "corrected", "made"}, "corrected" whether the audit was asked to work out G14's
// corrections and "made" the files the journal's form made, by name; or {"error", "written"}
// where the worker refuses the names or the form. The stand-in for `web.journal_files` makes
// "profile" and "authors" of what it is given, and refuses a journal named "refused"; the
// stand-in for `web.unpack_paper` unpacks an archive into the folder named after it, and
// refuses one whose name holds "bad". A case {"compare": {"before", "after", "letter",
// "comments", "draft"}} is worker.js's `compared` given those files by their names: its
// answer {"args", "written"}, or {"error", "written"}.
import { readFileSync } from "node:fs";
import { createContext, runInContext } from "node:vm";

const source = readFileSync(new URL("../worker.js", import.meta.url), "utf-8");
const written = [];
const set = {};
// The call as Python reads it: each of JOURNAL and AUTHORS it names must have been set to
// something, since a JavaScript null reaches Python as JsNull, which `journal_files` takes
// for a form and fails on (round 1 of #791); "None" in the call is none.
function journalFiles(code) {
  const [journal, authors] = code.match(/journal_files\((\w+), (\w+)\)/).slice(1)
    .map((name) => {
      if (name === "None") return null;
      if (!set[name]) throw new Error(`${name} reached Python as JsNull`);
      return set[name];
    });
  if (journal && journal.name === "refused") return JSON.stringify({ error: "a test" });
  return JSON.stringify({ ...(journal ? { profile: "profile\n" } : {}),
    ...(authors ? { authors: "authors\n" } : {}) });
}
function unpacked() {
  const name = set.ARCHIVE.slice("/upload/".length);
  if (name.includes("bad")) return JSON.stringify({ error: `${name}: a test` });
  return JSON.stringify({ folder: name.replace(/\.(zip|tar\.gz|tgz)$/i, "") });
}
const context = createContext({
  BASE: "/",
  self: { addEventListener() {}, postMessage() {} },
  performance: { setResourceTimingBufferSize() {}, clearResourceTimings() {}, now: () => 0,
    getEntriesByType: () => [] },
  stub: {
    runPython: (code) => (code.includes("web.view")
      ? '{"code": 0, "out": "", "err": "", "view": null}'
      : code.includes("web.run(") ? '{"code": 0, "out": "", "err": ""}'
      : code.includes("web.journal_files") ? journalFiles(code)
        : code.includes("web.unpack_paper") ? unpacked() : undefined),
    FS: { writeFile: (path) => written.push(path) },
    globals: { set: (name, value) => { set[name] = value; }, delete() {} },
    toPy: (value) => value,
  },
});
runInContext(source, context);
runInContext("py = stub;", context);

const file = (name) => ({ name, data: new ArrayBuffer(0) });
const cases = JSON.parse(readFileSync(0, "utf-8"));
// A comparison's files, each by its name, as compare.js sends them.
function comparison({ before, after, letter, comments, draft = false }) {
  context.payload = { before: file(before), after: file(after),
    letter: letter ? file(letter) : null, comments: comments ? file(comments) : null, draft };
  try {
    const { args } = runInContext("compared(payload)", context);
    return { args: [...args], written: [...written] };
  } catch (error) {
    return { error: String(error.message), written: [...written] };
  }
}
const answers = cases.map(({ paper, against, journalFile, authorsFile, offered, compare,
  ...chosen }) => {
  written.length = 0;
  if (compare) return comparison(compare);
  for (const name of ["CORRECTED", "JOURNAL", "AUTHORS", "ARCHIVE"]) delete set[name];
  context.payload = { paper: file(paper), against: against.map(file), lookup: false,
    journalFile: journalFile ? file(journalFile) : null,
    authorsFile: authorsFile ? file(authorsFile) : null,
    offered: offered ? { file: offered, data: new ArrayBuffer(0) } : null, ...chosen };
  try {
    const { args, made } = runInContext("run(payload)", context);
    return { args: [...args], written: [...written], corrected: set.CORRECTED,
      made: { ...made } };
  } catch (error) {
    return { error: String(error.message), written: [...written] };
  }
});
process.stdout.write(JSON.stringify(answers));
