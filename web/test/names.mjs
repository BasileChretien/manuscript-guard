// worker.js's `run`, in Node and without Pyodide: a stand-in `py` keeps the files it is given
// to write and the command it is asked to run, so that the names a reader chooses are seen to
// reach the command line as given (round 2 of #527: parity.mjs gives the command line its
// arguments itself, and never runs worker.js). tests/test_web.py runs this.
//
//   node web/test/names.mjs < cases.json
//
// Each case is {"paper": name, "against": [names]}; each answer {"args", "written"}, or
// {"error", "written"} where the worker refuses the names.
import { readFileSync } from "node:fs";
import { createContext, runInContext } from "node:vm";

const source = readFileSync(new URL("../worker.js", import.meta.url), "utf-8");
const written = [];
const context = createContext({
  BASE: "/",
  self: { addEventListener() {}, postMessage() {} },
  performance: { setResourceTimingBufferSize() {}, clearResourceTimings() {}, now: () => 0,
    getEntriesByType: () => [] },
  stub: {
    runPython: (code) => (code.includes("web.view")
      ? '{"code": 0, "out": "", "err": "", "view": null}' : undefined),
    FS: { writeFile: (path) => written.push(path) },
    globals: { set() {}, delete() {} },
    toPy: (value) => value,
  },
});
runInContext(source, context);
runInContext("py = stub;", context);

const file = (name) => ({ name, data: new ArrayBuffer(0) });
const cases = JSON.parse(readFileSync(0, "utf-8"));
const answers = cases.map(({ paper, against }) => {
  written.length = 0;
  context.payload = { paper: file(paper), against: against.map(file), lookup: false };
  try {
    const { args } = runInContext("run(payload)", context);
    return { args: [...args], written: [...written] };
  } catch (error) {
    return { error: String(error.message), written: [...written] };
  }
});
process.stdout.write(JSON.stringify(answers));
