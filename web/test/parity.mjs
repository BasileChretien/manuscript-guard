// One command, run as the page runs it, with the files of a built site: Pyodide, the
// wheel, pandoc.wasm and its bundled shim, and `manuscript_guard.web`. Prints
// {"code", "out", "err"} as JSON, for web/test/check.py to hold to the command line.
//
//   node web/test/parity.mjs <site> <folder> -- audit paper.docx --against results.json --json
//   node web/test/parity.mjs <site> <folder> --unpack project.zip -- audit project
//
// Every file and folder in <folder> is copied into the working folder first. With
// `--unpack`, the archive named is then unpacked as the page unpacks one (worker.js
// `unpacked`, `web.unpack_paper`): moved out of the working folder, the folder of its name
// that <folder> holds removed, and the archive unpacked into one of that name, which the
// command is then given.
import { readFileSync, readdirSync, statSync } from "node:fs";
import { join, resolve } from "node:path";
import { pathToFileURL } from "node:url";

const given = process.argv.slice(2);
const unpack = given[2] === "--unpack" ? given[3] : null;
const [site, folder, dashes, ...args] = unpack ? [...given.slice(0, 2), ...given.slice(4)] : given;
if (!site || !folder || dashes !== "--" || !args.length) {
  console.error("usage: node web/test/parity.mjs <site> <folder> [--unpack <archive>] -- "
    + "<command> [arguments]");
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

// Every file and folder in <folder>, a LaTeX project's folder among them, copied as it is.
function copied(from, to) {
  py.FS.mkdirTree(to);
  for (const name of readdirSync(from)) {
    const path = join(from, name);
    if (statSync(path).isDirectory()) copied(path, `${to}/${name}`);
    else if (statSync(path).isFile()) py.FS.writeFile(`${to}/${name}`, readFileSync(path));
  }
}
copied(folder, "/work");
if (unpack) {
  py.globals.set("ARCHIVE", unpack);
  const said = JSON.parse(py.runPython(`
import json, os, shutil
from manuscript_guard import web
from manuscript_guard.auditing.unpack import archive_stem
os.makedirs("/upload", exist_ok=True)
shutil.move("/work/" + ARCHIVE, "/upload/" + ARCHIVE)
shutil.rmtree("/work/" + archive_stem(ARCHIVE), ignore_errors=True)
json.dumps(web.unpack_paper("/upload/" + ARCHIVE, "/work"))
`));
  if (said.error) {
    console.error(`parity.mjs: ${unpack} was not unpacked: ${said.error}`);
    process.exit(1);
  }
}
py.globals.set("ARGS", py.toPy(args));
const result = py.runPython(`
import json, os
from manuscript_guard import web
os.chdir("/work")
json.dumps(web.run(ARGS))
`);
process.stdout.write(result);
