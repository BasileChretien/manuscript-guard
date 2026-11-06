// Runs the HyperFrames CLI with its usage telemetry and its check for updates off, on every
// platform: the npm scripts call `node cli.mjs <command>`, so that rendering the video asks
// nothing of the network and sends nothing about whoever runs it.
import { spawnSync } from "node:child_process";
import { createRequire } from "node:module";
import { dirname, join } from "node:path";

const require = createRequire(import.meta.url);
const root = dirname(require.resolve("hyperframes/package.json"));
const bin = join(root, require("hyperframes/package.json").bin.hyperframes);
const done = spawnSync(process.execPath, [bin, ...process.argv.slice(2)], {
  stdio: "inherit",
  env: { ...process.env, HYPERFRAMES_NO_TELEMETRY: "1", DO_NOT_TRACK: "1",
    HYPERFRAMES_NO_UPDATE_CHECK: "1" },
});
if (done.error) throw done.error;
process.exit(done.status ?? 1);
