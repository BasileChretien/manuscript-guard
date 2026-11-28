// One command, run as the page runs it, with the files of a built site: Pyodide, the
// wheel, pandoc.wasm and its bundled shim, poppler's pdftotext and pdfinfo, and
// `manuscript_guard.web`. Prints {"code", "out", "err"} as JSON, for web/test/check.py to
// hold to the command line.
//
//   node web/test/parity.mjs <site> <folder> -- audit paper.docx --against results.json --json
//   node web/test/parity.mjs <site> <folder> --unpack project.zip -- audit project
//   node web/test/parity.mjs <site> <folder> --read report-draft.md -- compare v1/a.md v2/b.md \
//       --report-draft report-draft.md
//
// Every file and folder in <folder> is copied into the working folder first. With
// `--unpack`, the archive named is then unpacked as the page unpacks one (worker.js
// `unpacked`, `web.unpack_paper`): moved out of the working folder, the folder of its name
// that <folder> holds removed, and the archive unpacked into one of that name, which the
// command is then given. With `--read`, the text of the file named, which the command
// wrote in the working folder, is given as "file" beside them, null where it wrote none.
import { readFileSync, readdirSync, statSync } from "node:fs";
import { createRequire } from "node:module";
import { join, resolve } from "node:path";
import { pathToFileURL } from "node:url";

const given = process.argv.slice(2);
const [site, folder] = given;
const options = {};
let at = 2;
while (["--unpack", "--read"].includes(given[at])) {
  options[given[at].slice(2)] = given[at + 1];
  at += 2;
}
const [dashes, ...args] = given.slice(at);
const unpack = options.unpack || null;
if (!site || !folder || dashes !== "--" || !args.length) {
  console.error("usage: node web/test/parity.mjs <site> <folder> [--unpack <archive>] "
    + "[--read <file>] -- <command> [arguments]");
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
// poppler's programs, given the files of Pyodide's their arguments name, as worker.js gives
// them (`programs`). Under Node the glue asks for Node's own `require`.
const { createPoppler } = await import(pathToFileURL(join(root, "poppler", "poppler.mjs")).href);
const poppler = await createPoppler(readFileSync(join(root, "poppler", "poppler-multicall.wasm")),
  createRequire(import.meta.url));
const fileOf = (path) => {
  try {
    return py.FS.isFile(py.FS.stat(path).mode) ? py.FS.readFile(path) : null;
  } catch {
    return null;
  }
};
py.globals.set("POPPLER_JS", { run: (program, args, cwd) => poppler.run(program, args, cwd, fileOf) });
py.globals.set("PANDOC_JS", pandoc);
py.runPython("from manuscript_guard import web; web.install_programs(POPPLER_JS); web.install(PANDOC_JS)");

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
if (options.read) {
  const written = fileOf("/work/" + options.read);
  const said = { ...JSON.parse(result), file: written ? new TextDecoder().decode(written) : null };
  process.stdout.write(JSON.stringify(said));
} else {
  process.stdout.write(result);
}
