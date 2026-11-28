// poppler's pdftotext and pdfinfo, from the npm package @ai-ecoverse/wasm-poppler, run as a
// command line runs a program: given its arguments and the files they name, from a folder,
// and giving back what it printed and its exit code.
//
// The package's glue (bin/poppler-multicall) is one script for every program of the build,
// and starts none of them itself (its `noInitialRun`). A program keeps in its memory what its
// options set: an instance that ran `pdftotext -raw` would read the next PDF in that order
// too. So each run is an instance of its own, made from the module compiled once, and its
// `main` is called once. web/build.py appends the glue, as the package has it, inside
// `function glue(Module, require, __dirname) { ... }`, which makes one instance each time it
// is called. Under Node, `require` is Node's, which the glue asks for `fs` and `crypto`, and
// `__dirname` the folder it would load the wasm from, which it does not here; in a worker
// neither is used. The glue sets no environment variable, so a program runs alike in both.

export const PROGRAMS = ["pdftotext", "pdfinfo"];

// The bytes a program writes, kept as they come, one at a time (the glue's `stdout`).
function collector() {
  let data = new Uint8Array(1 << 16);
  let length = 0;
  return {
    put(byte) {
      if (byte === null || byte === undefined) return;
      if (length === data.length) {
        const more = new Uint8Array(data.length * 2);
        more.set(data);
        data = more;
      }
      // A byte comes as the glue's signed view of memory holds it; a Uint8Array keeps its
      // low eight bits, which are the byte.
      data[length++] = byte;
    },
    line(text) {
      for (const byte of new TextEncoder().encode(text + "\n")) this.put(byte);
    },
    bytes: () => data.slice(0, length),
  };
}

const parent = (path) => (path.includes("/") ? path.slice(0, path.lastIndexOf("/")) : "");

// `wasm` is a compiled WebAssembly.Module (the page compiles it as it downloads) or the bytes
// of poppler-multicall.wasm.
export async function createPoppler(wasm, require) {
  const compiled = wasm instanceof WebAssembly.Module ? wasm : await WebAssembly.compile(wasm);

  // `program`, one of PROGRAMS, run in the folder `cwd` with `args`. Each argument that
  // `read` gives bytes for, a file it names from that folder, is put at that place in the
  // program's own memory first. Returns its exit code and what it wrote to its standard
  // output and its standard error. A run that stops in the WebAssembly itself, a trap, has
  // exit code 1 and says why on its standard error, as a program that fails does.
  function run(program, args, cwd, read) {
    if (!PROGRAMS.includes(program)) throw new Error(`no program ${program} here`);
    const stdout = collector();
    const stderr = collector();
    const instance = glue({
      thisProgram: program,
      noInitialRun: true,
      instantiateWasm(imports, received) {
        const made = new WebAssembly.Instance(compiled, imports);
        received(made, compiled);
        return made.exports;
      },
      stdin: () => null,
      stdout: (byte) => stdout.put(byte),
      stderr: (byte) => stderr.put(byte),
      print: (text) => stdout.line(text),
      printErr: (text) => stderr.line(text),
    }, require, ".");
    const { FS } = instance;
    FS.mkdirTree(cwd);
    FS.chdir(cwd);
    for (const arg of args) {
      const data = read(arg);
      if (!data) continue;
      if (parent(arg)) FS.mkdirTree(parent(arg));
      FS.writeFile(arg, data);
    }
    // Under Node, the glue's exit sets the exit code of Node itself.
    const exitCode = globalThis.process?.exitCode;
    let code;
    try {
      code = instance.callMain([...args]);
    } catch (error) {
      stderr.line(`${program}: ${String((error && error.message) || error)}`);
      code = 1;
    } finally {
      if (globalThis.process) globalThis.process.exitCode = exitCode;
    }
    return { code, stdout: stdout.bytes(), stderr: stderr.bytes() };
  }

  return { run, programs: PROGRAMS };
}
