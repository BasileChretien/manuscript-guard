// poppler's programs as the page runs them (web/poppler.mjs, with the package's glue as
// web/build.py puts it in), run in Node for tests/test_web.py. Reads one JSON object on its
// standard input, {"module": its path, "wasm": poppler-multicall.wasm's, "runs": [[program,
// ...arguments], ...]}, runs each in the folder this is run in, a file each argument names
// given as worker.js gives it, and prints {"said": [{"code", "out", "err"}, ...], "refused":
// what a program the page has not is refused with, "programs", "code": Node's exit code after
// the runs}.
import { readFileSync, statSync } from "node:fs";
import { createRequire } from "node:module";
import { pathToFileURL } from "node:url";

const { module, wasm, runs } = JSON.parse(readFileSync(0, "utf-8"));
const { createPoppler, PROGRAMS } = await import(pathToFileURL(module).href);
const poppler = await createPoppler(readFileSync(wasm), createRequire(import.meta.url));
const read = (path) => {
  try {
    return statSync(path).isFile() ? readFileSync(path) : null;
  } catch {
    return null;
  }
};
const text = (bytes) => Buffer.from(bytes).toString("utf-8");
const said = runs.map(([name, ...args]) => poppler.run(name, args, process.cwd(), read))
  .map(({ code, stdout, stderr }) => ({ code, out: text(stdout), err: text(stderr) }));
let refused = null;
try {
  poppler.run("pdftoppm", [], process.cwd(), read);
} catch (error) {
  refused = error.message;
}
console.log(JSON.stringify({ said, refused, programs: PROGRAMS, code: process.exitCode ?? null }));
