// pandoc.wasm, called synchronously.
//
// The pandoc project's own wrapper (the npm package pandoc-wasm) is asynchronous only
// because it reads its input files from Blobs. Python's `from_word` calls pandoc as a
// function and waits for what it prints, so here the files go in and come out as
// Uint8Array, and nothing is awaited once pandoc is started: `manuscript_guard.web` calls
// `convertSync` from Python as `subprocess.run` would be called. The WASI set-up is the
// one pandoc-wasm uses. web/build.py bundles this file with the shim into one module: in
// a Worker made from a blob: URL, Firefox refused the shim's own imports.
import {
  ConsoleStdout,
  Directory,
  File,
  OpenFile,
  PreopenDirectory,
  WASI,
} from "@bjorn3/browser_wasi_shim";

const encoder = new TextEncoder();

// `wasm` is a compiled WebAssembly.Module (the page compiles it as it downloads, which lets
// the browser keep the compiled code) or the bytes of pandoc.wasm.
export async function createPandoc(wasm) {
  const args = ["pandoc.wasm", "+RTS", "-H64m", "-RTS"];
  const fileSystem = new Map();
  const fds = [
    new OpenFile(new File(new Uint8Array(), { readonly: true })),
    ConsoleStdout.lineBuffered(() => {}),
    ConsoleStdout.lineBuffered(() => {}),
    new PreopenDirectory("/", fileSystem),
  ];
  const wasi = new WASI(args, [], fds, { debug: false });
  const imports = { wasi_snapshot_preview1: wasi.wasiImport };
  const made = await WebAssembly.instantiate(wasm, imports);
  const instance = made instanceof WebAssembly.Instance ? made : made.instance;
  wasi.initialize(instance);
  instance.exports.__wasm_call_ctors();

  const memory = () => instance.exports.memory.buffer;
  const view = () => new DataView(memory());
  const argc = instance.exports.malloc(4);
  view().setUint32(argc, args.length, true);
  const argv = instance.exports.malloc(4 * (args.length + 1));
  args.forEach((arg, i) => {
    const at = instance.exports.malloc(arg.length + 1);
    encoder.encodeInto(arg, new Uint8Array(memory(), at, arg.length));
    view().setUint8(at + arg.length, 0);
    view().setUint32(argv + 4 * i, at, true);
  });
  view().setUint32(argv + 4 * args.length, 0, true);
  const argvAt = instance.exports.malloc(4);
  view().setUint32(argvAt, argv, true);
  instance.exports.hs_init_with_rtsopts(argc, argvAt);

  function put(text) {
    const bytes = encoder.encode(text);
    const at = instance.exports.malloc(bytes.length);
    new Uint8Array(memory(), at, bytes.length).set(bytes);
    return [at, bytes.length];
  }

  function reset() {
    fileSystem.clear();
    const files = {};
    for (const name of ["stdin", "stdout", "stderr", "warnings"]) {
      files[name] = new File(new Uint8Array(), { readonly: name === "stdin" });
      fileSystem.set(name, files[name]);
    }
    return files;
  }

  const version = (() => {
    const { stdout } = reset();
    instance.exports.query(...put(JSON.stringify({ query: "version" })));
    return JSON.parse(new TextDecoder().decode(stdout.data));
  })();

  // options: a pandoc defaults-file object; stdin: a string or null; files: {name:
  // Uint8Array}. Returns what pandoc printed and every file it wrote, by path from "/".
  function convertSync(options, stdin, files) {
    const own = reset();
    const known = new Set(Object.keys(own));
    if (stdin) own.stdin.data = encoder.encode(stdin);
    for (const [name, data] of Object.entries(files || {})) {
      fileSystem.set(name, new File(data, { readonly: true }));
      known.add(name);
    }
    instance.exports.convert(...put(JSON.stringify(options)));
    const written = {};
    const walk = (entries, prefix) => {
      for (const [name, entry] of entries) {
        const path = prefix ? `${prefix}/${name}` : name;
        if (entry instanceof Directory) walk(entry.contents.entries(), path);
        else if (!known.has(path) && entry.data && entry.data.length) written[path] = entry.data;
      }
    };
    walk(fileSystem.entries(), "");
    return {
      stdout: new TextDecoder("utf-8", { fatal: true }).decode(own.stdout.data),
      stderr: new TextDecoder().decode(own.stderr.data),
      files: written,
    };
  }

  return { convertSync, version };
}
