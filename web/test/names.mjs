// worker.js's `run`, in Node and without Pyodide: a stand-in `py` keeps the files it is given
// to write and the command it is asked to run, so that the names a reader chooses are seen to
// reach the command line as given (round 2 of #527: parity.mjs gives the command line its
// arguments itself, and never runs worker.js). tests/test_web.py runs this.
//
//   node web/test/names.mjs < cases.json
//
// Each case is {"paper": name, "against": [names]}, with "english", "known", "noAbstract",
// "noResults", "results", "tracked", "design", "wholeNumbers", "binary", "nonNegative",
// "minimumCellCount", "journal" and "authors" where the reader set them, and "journalFile"
// and "authorsFile" by their names where the reader chose one; each answer {"args",
// "written", "corrected", "made"}, "corrected" whether the audit was asked to work out G14's
// corrections and "made" the files the journal's form made, by name; or {"error", "written"}
// where the worker refuses the names or the form. The stand-in for `web.journal_files` makes
// "profile" and "authors" of what it is given, and refuses a journal named "refused"; the
// stand-in for `web.unpack_paper` unpacks an archive into the folder named after it, and
// refuses one whose name holds "bad".
import { readFileSync } from "node:fs";
import { createContext, runInContext } from "node:vm";

const source = readFileSync(new URL("../worker.js", import.meta.url), "utf-8");
const written = [];
const set = {};
function journalFiles() {
  if (set.JOURNAL && set.JOURNAL.name === "refused") return JSON.stringify({ error: "a test" });
  return JSON.stringify({ ...(set.JOURNAL ? { profile: "profile\n" } : {}),
    ...(set.AUTHORS ? { authors: "authors\n" } : {}) });
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
      : code.includes("web.journal_files") ? journalFiles()
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
const answers = cases.map(({ paper, against, journalFile, authorsFile, ...chosen }) => {
  written.length = 0;
  for (const name of ["CORRECTED", "JOURNAL", "AUTHORS", "ARCHIVE"]) delete set[name];
  context.payload = { paper: file(paper), against: against.map(file), lookup: false,
    journalFile: journalFile ? file(journalFile) : null,
    authorsFile: authorsFile ? file(authorsFile) : null, ...chosen };
  try {
    const { args, made } = runInContext("run(payload)", context);
    return { args: [...args], written: [...written], corrected: set.CORRECTED,
      made: { ...made } };
  } catch (error) {
    return { error: String(error.message), written: [...written] };
  }
});
process.stdout.write(JSON.stringify(answers));
