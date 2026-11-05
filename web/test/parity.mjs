// One command, run as the page runs it, with the files of a built site: Pyodide, the
// wheel, pandoc.wasm and its bundled shim, and `manuscript_guard.web`. Prints
// {"code", "out", "err"} as JSON, for web/test/check.py to hold to the command line.
//
//   node web/test/parity.mjs <site> <folder> -- audit paper.docx --against results.json --json
//
// Every file directly in <folder> is copied into the working folder first.
import { readFileSync, readdirSync, statSync } from "node:fs";
import { join, resolve } from "node:path";
import { pathToFileURL } from "node:url";

const [site, folder, dashes, ...args] = process.argv.slice(2);
if (!site || !folder || dashes !== "--" || !args.length) {
  console.error("usage: node web/test/parity.mjs <site> <folder> -- <command> [arguments]");
  process.exit(2);
}
const root = resolve(site);
const manifest = JSON.parse(readFileSync(join(root, "manifest.json"), "utf-8"));
const { loadPyodide } = await import(pathToFileURL(join(root, "pyodide", "pyodide.mjs")).href);
const py = await loadPyodide({ indexURL: join(root, "pyodide") + "/" });
await py.loadPackage(manifest.load, { messageCallback: () => {} });
// A Node Buffer is a typed array Pyodide does not take: its bytes, as a plain Uint8Array.
py.unpackArchive(new Uint8Array(readFileSync(join(root, manifest.wheel))), "wheel");
const { createPandoc } = await import(pathToFileURL(join(root, "pandoc", "pandoc.mjs")).href);
const pandoc = await createPandoc(readFileSync(join(root, "pandoc", "pandoc.wasm")));
py.globals.set("PANDOC_JS", pandoc);
py.runPython("from manuscript_guard import web; web.install(PANDOC_JS)");

py.FS.mkdirTree("/work");
for (const name of readdirSync(folder)) {
  const path = join(folder, name);
  if (statSync(path).isFile()) py.FS.writeFile("/work/" + name, readFileSync(path));
}
py.globals.set("ARGS", py.toPy(args));
const result = py.runPython(`
import json, os
from manuscript_guard import web
os.chdir("/work")
json.dumps(web.run(ARGS))
`);
process.stdout.write(result);
