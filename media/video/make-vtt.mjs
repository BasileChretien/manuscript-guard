// Writes the WebVTT captions from the caption elements of index.html, so that the file and
// the burned-in captions cannot differ: same words, same start, same duration.
// Usage: node make-vtt.mjs [output path]   (default: ../../web/landing/media/vord.en.vtt)
import { readFileSync, writeFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const html = readFileSync(resolve(here, "index.html"), "utf8");
const out = resolve(process.argv[2] ?? resolve(here, "../../web/landing/media/vord.en.vtt"));

const pattern =
  /<div id="cap-\d+" class="cap clip" data-start="([\d.]+)" data-duration="([\d.]+)"[^>]*><span>(.+?)<\/span><\/div>$/gm;
const cues = [...html.matchAll(pattern)].map(([, start, duration, text]) => ({
  start: Number(start),
  end: Number(start) + Number(duration),
  // A span inside a caption only keeps a word from breaking; its words are the caption's.
  text: text.replace(/<[^>]+>/g, "").replace(/&lt;/g, "<").replace(/&gt;/g, ">").replace(/&amp;/g, "&"),
}));
if (cues.length === 0) {
  throw new Error("no caption elements found in index.html");
}
if ((html.match(/class="cap clip"/g) ?? []).length !== cues.length) {
  throw new Error("a caption element in index.html is not in the expected form");
}

function escape(text) {
  return text.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

function stamp(seconds) {
  const ms = Math.round(seconds * 1000);
  const h = String(Math.floor(ms / 3600000)).padStart(2, "0");
  const m = String(Math.floor((ms % 3600000) / 60000)).padStart(2, "0");
  const s = String(Math.floor((ms % 60000) / 1000)).padStart(2, "0");
  return `${h}:${m}:${s}.${String(ms % 1000).padStart(3, "0")}`;
}

const body = cues
  // WebVTT reads &, < and > as markup, as HTML does.
  .map((cue, i) => `${i + 1}\n${stamp(cue.start)} --> ${stamp(cue.end)}\n${escape(cue.text)}\n`)
  .join("\n");
writeFileSync(out, `WEBVTT\n\n${body}`, "utf8");
console.log(`${cues.length} cues written to ${out}`);
