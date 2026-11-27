// One of poppler's programs, pdftotext or pdfinfo, as the page runs it (the poppler.mjs of a
// built site, in Node), started as a command. web/test/check.py puts one on PATH under each
// program's name for the command line it compares the page with, so that both read a PDF
// with the same pdftotext: what it prints goes to this process's standard output and
// error, byte for byte, and its exit code is this process's.
//
//   node web/test/program.mjs <the site's audit folder> pdftotext -enc UTF-8 paper.pdf -
//
// Each argument that names a file, from the folder this is run in, is given to the program
// with its bytes, as worker.js gives it the files of Pyodide's.
import { readFileSync, statSync } from "node:fs";
import { createRequire } from "node:module";
import { join, resolve } from "node:path";
import { pathToFileURL } from "node:url";

const [page, program, ...args] = process.argv.slice(2);
if (!page || !program) {
  console.error("usage: node web/test/program.mjs <the site's audit folder> <program> [arguments]");
  process.exit(2);
}
const root = resolve(page);
const { createPoppler } = await import(pathToFileURL(join(root, "poppler", "poppler.mjs")).href);
const poppler = await createPoppler(readFileSync(join(root, "poppler", "poppler-multicall.wasm")),
  createRequire(import.meta.url));
const fileOf = (path) => {
  try {
    return statSync(path).isFile() ? new Uint8Array(readFileSync(path)) : null;
  } catch {
    return null;
  }
};
const { code, stdout, stderr } = poppler.run(program, args, process.cwd(), fileOf);
process.stdout.write(stdout);
process.stderr.write(stderr);
process.exitCode = code;
