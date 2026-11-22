// A co-author's checker page (`manuscript-guard checker build`, the template
// src/manuscript_guard/checking/checker.html) in a real browser, served over loopback. Its
// storage keeps an answer across a reload, and where storage throws the page still renders
// and answers; Save downloads a file of the name the page carries, holding the answers given;
// Save and Copy each open the dialog with the answers file in its box, and Close shuts it;
// Copy puts that file on the clipboard, and with the clipboard refused or absent the box still
// holds it; each status key records its answer, an arrow moves between items, a key held with
// Ctrl, Alt or Meta records nothing, and a key typed into the note box is the note's. The page
// asks no host for anything.
//
//   node web/test/checker.mjs <page.html> chrome|firefox [executable]
//
// <page.html> is a page built from the worked example, whose items hold the five groups and
// the methods group's "Code needs changing" (CI's `web` job builds it for "Ada Example").
import { createServer } from "node:http";
import { existsSync, mkdtempSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import puppeteer from "puppeteer-core";

const [pagePath, browserName, given] = process.argv.slice(2);
const KNOWN = {
  chrome: ["/usr/bin/google-chrome", "C:/Program Files/Google/Chrome/Application/chrome.exe",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"],
  firefox: ["/usr/bin/firefox", "C:/Program Files/Mozilla Firefox/firefox.exe",
    "/Applications/Firefox.app/Contents/MacOS/firefox"],
};
if (!pagePath || !KNOWN[browserName]) {
  console.error("usage: node web/test/checker.mjs <page.html> chrome|firefox [executable]");
  process.exit(2);
}
const executable = given || process.env[browserName.toUpperCase()] ||
  KNOWN[browserName].find((path) => existsSync(path));
if (!executable) {
  console.error(`no ${browserName} found: name it as the third argument`);
  process.exit(2);
}

// What the page carries, read out of it as tests/test_checking.py reads it.
const html = readFileSync(pagePath);
const text = html.toString("utf-8");
const start = text.indexOf("const BUNDLE = ") + "const BUNDLE = ".length;
const BUNDLE = JSON.parse(text.slice(start, text.indexOf("\n", start)).trim().replace(/;$/, ""));
const groupOf = (item) => BUNDLE.groups.find((g) => g.id === item.group);
const statusesOf = (item) => (groupOf(item).answers || []).map((a) => a.status);
const coded = BUNDLE.items.findIndex((item) => statusesOf(item).includes("code"));
if (BUNDLE.items.length < 4 || coded < 3) {
  console.error(`the page holds ${BUNDLE.items.length} items and its first item answered with ` +
    `"code" is item ${coded}: build it from the worked example`);
  process.exit(2);
}

// The page at /, and nothing else.
const server = createServer((request, response) => {
  if (new URL(request.url, "http://x").pathname !== "/") {
    response.writeHead(404).end();
    return;
  }
  response.writeHead(200, { "Content-Type": "text/html; charset=utf-8" }).end(html);
});
await new Promise((ready) => server.listen(0, "127.0.0.1", ready));
const origin = `http://127.0.0.1:${server.address().port}`;

const failures = [];
const fail = (what) => { failures.push(what); console.error(`FAIL ${browserName}: ${what}`); };
const check = (held, what) => { if (!held) fail(what); return held; };
const folders = [];
const folder = () => { const made = mkdtempSync(join(tmpdir(), "mg-checker-")); folders.push(made); return made; };

// As browser.mjs launches them. Firefox reads its clipboard only from a menu the person
// clicks, unless told it is under test, as the web platform's own tests tell it.
const args = browserName === "chrome" && process.env.CI ? ["--no-sandbox"] : [];
const browser = await puppeteer.launch({ browser: browserName, executablePath: executable,
  headless: true, args, extraPrefsFirefox: { "dom.events.testing.asyncClipboard": true } });

// A page of its own context, where downloads go to a folder of their own; `before` runs
// ahead of the page's script. `what` names the case in a failure.
async function open(what, before) {
  const downloads = folder();
  const context = await browser.createBrowserContext(
    { downloadBehavior: { policy: "allow", downloadPath: downloads } });
  const page = await context.newPage();
  page.setDefaultTimeout(30000);
  const errors = [];
  const asked = [];
  page.on("pageerror", (error) => errors.push(String(error.message || error)));
  page.on("request", (request) => asked.push(request.url()));
  if (before) await page.evaluateOnNewDocument(before);
  await page.goto(origin + "/", { waitUntil: "load" });
  check(await drawn(page), `${what}: the page draws no item`);
  return { context, page, downloads, errors, asked };
}
// The first item drawn; a page whose script stopped draws none, which is a failure, not a crash.
const drawn = (page) => page.waitForSelector("#item .ask").then(() => true, () => false);
// The dialog open or shut, as asked. One left open is shut, so that what follows can run.
const sent = (page, open, what) => page.waitForFunction(
  (open) => document.getElementById("sent").open === open, {}, open).then(() => true, async () => {
  fail(`${what}: the dialog ${open ? "did not open" : "stayed open"}`);
  if (!open) await page.evaluate(() => document.getElementById("sent").close());
  return false;
});

// The page's state, as its script holds it and as it shows it.
const state = (page) => page.evaluate(() => ({
  pos: S.pos,
  id: (S.list[S.pos] || {}).id,
  shown: document.querySelector("#item .title")?.textContent,
  answers: JSON.parse(JSON.stringify(S.answers)),
  progress: document.getElementById("progress").textContent,
  why: !document.getElementById("why").hidden,
  focus: document.activeElement && document.activeElement.id,
  note: document.getElementById("note").value,
  stored: (() => { try { return localStorage.getItem(KEY); } catch (e) { return "refused"; } })(),
}));
// Out of the note box, as a click on the item's question takes a person out of it.
const away = (page) => page.click("#item .ask");
const note = async (page, words) => { await page.click("#note"); await page.keyboard.type(words); };
const dialog = (page) => page.evaluate(() => ({
  open: document.getElementById("sent").open,
  what: document.getElementById("sentwhat").textContent,
  blob: document.getElementById("blob").value,
}));

// The answers a file holds, against the ones given: [id, status, note] for each, and the
// item's digest and title with it.
function differs(file, expected, where) {
  let parsed;
  try { parsed = typeof file === "string" ? JSON.parse(file) : file; } catch (e) {
    return fail(`${where}: not an answers file: ${String(file).slice(0, 80)}`);
  }
  if (!parsed || parsed.schema !== "manuscript-guard/checking-answers/2" ||
      parsed.bundle !== BUNDLE.bundle || parsed.token !== BUNDLE.token || parsed.by !== BUNDLE.by) {
    return fail(`${where}: not this page's answers file: ${JSON.stringify(parsed).slice(0, 200)}`);
  }
  const got = Object.fromEntries((parsed.answers || []).map((a) => [a.id, a]));
  const wrong = Object.keys(expected).filter((id) => {
    const item = BUNDLE.items.find((each) => each.id === id);
    const one = got[id] || {};
    return one.status !== expected[id].status || one.note !== expected[id].note ||
      one.digest !== item.digest || one.title !== item.title;
  });
  const extra = Object.keys(got).filter((id) => !(id in expected));
  if (wrong.length || extra.length) {
    fail(`${where}: answers ${JSON.stringify(parsed.answers)}, given ${JSON.stringify(expected)}`);
  }
}
const recorded = (answers) => Object.fromEntries(
  Object.entries(answers).map(([id, a]) => [id, { status: a.status, note: a.note }]));
const same = (a, b) => JSON.stringify(a) === JSON.stringify(b);

// A downloaded file, once the browser has finished writing it.
async function downloaded(where, name) {
  const file = join(where, name);
  const until = Date.now() + 30000;
  while (Date.now() < until) {
    if (existsSync(file)) {
      try { return JSON.parse(readFileSync(file, "utf-8")); } catch (e) { /* still being written */ }
    }
    await new Promise((wait) => setTimeout(wait, 100));
  }
  return null;
}

try {
  const items = BUNDLE.items;
  const one = await open("the page");
  const { page } = one;
  if (browserName === "chrome") {
    await one.context.overridePermissions(origin,
      ["clipboard-read", "clipboard-write", "clipboard-sanitized-write"]);
  }
  let now = await state(page);
  check(now.id === items[0].id && now.shown === items[0].title && same(now.answers, {}),
    `the page opened on ${now.id} with ${JSON.stringify(now.answers)}`);

  // keyboard: a key with Ctrl, Alt or Meta is the browser's.
  for (const held of ["Control", "Alt", "Meta"]) {
    await page.keyboard.down(held);
    await page.keyboard.press("y");
    await page.keyboard.up(held);
    now = await state(page);
    check(same(now.answers, {}) && now.pos === 0, `${held}+Y recorded ${JSON.stringify(now.answers)}`);
  }
  // N with no note asks for the reason and waits in the note box, the letter not typed there.
  await page.keyboard.press("n");
  now = await state(page);
  check(same(now.answers, {}) && now.why && now.focus === "note" && now.note === "",
    `N with no note: ${JSON.stringify(now)}`);
  // A letter typed into the note box is the note's.
  const reason = "y, n, c and u typed here";
  await page.keyboard.type(reason);
  now = await state(page);
  check(same(now.answers, {}) && now.note === reason, `typed into the note: ${JSON.stringify(now)}`);
  await away(page);
  await page.keyboard.press("n");
  const expected = { [items[0].id]: { status: "wrong", note: reason } };
  now = await state(page);
  check(same(recorded(now.answers), expected) && now.pos === 1, `N after a note: ${JSON.stringify(now)}`);
  // The arrows.
  await page.keyboard.press("ArrowRight");
  now = await state(page);
  check(now.pos === 2 && now.shown === items[2].title, `the right arrow: at ${now.pos}`);
  await page.keyboard.press("ArrowLeft");
  now = await state(page);
  check(now.pos === 1 && now.shown === items[1].title, `the left arrow: at ${now.pos}`);
  await page.keyboard.press("y");
  expected[items[1].id] = { status: "ok", note: "" };
  now = await state(page);
  check(same(recorded(now.answers), expected) && now.pos === 2, `Y: ${JSON.stringify(now.answers)}`);
  await note(page, "the page is hard to read");
  await away(page);
  await page.keyboard.press("u");
  expected[items[2].id] = { status: "unsure", note: "the page is hard to read" };
  now = await state(page);
  check(same(recorded(now.answers), expected) && now.pos === 3, `U: ${JSON.stringify(now.answers)}`);
  for (let at = 3; at < coded; at += 1) await page.keyboard.press("ArrowRight");
  await note(page, "the code drops a row");
  await away(page);
  await page.keyboard.press("c");
  expected[items[coded].id] = { status: "code", note: "the code drops a row" };
  now = await state(page);
  check(same(recorded(now.answers), expected), `C on ${items[coded].id}: ${JSON.stringify(now.answers)}`);
  console.log(`keys: ${Object.keys(now.answers).length} answers recorded, ` +
    `${Object.keys(expected).length} given`);

  // storage: the answers are there after a reload.
  await page.reload({ waitUntil: "load" });
  check(await drawn(page), "after a reload the page draws no item");
  now = await state(page);
  const done = Object.keys(expected).length;
  check(same(recorded(now.answers), expected) && now.progress.startsWith(`${done} of ${items.length} done`),
    `after a reload: ${JSON.stringify(now.answers)}, "${now.progress}"`);
  check(now.stored && same(recorded(JSON.parse(now.stored)), expected), `stored: ${now.stored}`);
  console.log(`storage: ${Object.keys(now.answers).length} answers after a reload`);

  // download and dialog: Save.
  await page.click("#save");
  await sent(page, true, "Save");
  let shown = await dialog(page);
  check(shown.what.includes(`${done} of ${items.length} answered`) && shown.what.includes(BUNDLE.filename),
    `Save's dialog says "${shown.what}"`);
  differs(shown.blob, expected, "Save's box");
  const file = await downloaded(one.downloads, BUNDLE.filename);
  if (check(file, `Save downloaded no ${BUNDLE.filename}`)) differs(file, expected, "the file Save downloaded");
  await page.click("#shut");
  await sent(page, false, "Close");
  console.log(`download: ${file ? BUNDLE.filename : "nothing"}`);

  // clipboard and dialog: Copy. Something else on the clipboard first, so that what is read
  // back is what Copy wrote.
  const clipboard = await page.evaluate(() => navigator.clipboard.writeText("before Copy").then(
    () => "", (error) => String(error)));
  check(!clipboard, `the clipboard could not be written before Copy: ${clipboard}`);
  await page.click("#copy");
  await sent(page, true, "Copy");
  shown = await dialog(page);
  check(/^Copy everything in the box/.test(shown.what), `Copy's dialog says "${shown.what}"`);
  differs(shown.blob, expected, "Copy's box");
  const pasted = await page.waitForFunction(async () => {
    const held = await navigator.clipboard.readText().catch(() => "before Copy");
    return held !== "before Copy" && held;
  }, { polling: 100 }).then((handle) => handle.jsonValue(), (error) => `not read: ${error.message}`);
  differs(pasted, expected, "the clipboard after Copy");
  await page.click("#shut");
  await sent(page, false, "Close");
  console.log(`clipboard: ${pasted.startsWith("{") ? "the answers file" : pasted.slice(0, 60)}`);
  check(!one.errors.length, `the page's script failed: ${one.errors.join("; ")}`);
  // Over the network only, as browser.mjs reads it: a data: or blob: address is no host.
  const elsewhere = one.asked.filter((url) => /^(https?|wss?):/.test(url) &&
    !url.startsWith(origin + "/"));
  check(!elsewhere.length, `the page asked ${elsewhere.join(", ")}`);
  await one.context.close();

  // C answers only where the item's group lists it: on a literature item, with a note, it
  // records nothing.
  const plain = items.findIndex((item) => item.group === "literature");
  if (check(plain >= 0 && !statusesOf(items[plain]).includes("code"),
    "the page holds no literature item answered without C: C was not tried outside the methods")) {
    const other = await open("C outside the methods");
    for (let at = 0; at < plain; at += 1) await other.page.keyboard.press("ArrowRight");
    await note(other.page, "the source is not this one");
    await away(other.page);
    await other.page.keyboard.press("c");
    now = await state(other.page);
    check(now.id === items[plain].id && same(now.answers, {}),
      `C on ${now.id}, a literature item: ${JSON.stringify(now.answers)}`);
    console.log(`C on a literature item: ${Object.keys(now.answers).length} answers recorded`);
    await other.context.close();
  }

  // The clipboard refused, and absent: the box holds the file all the same. Chrome refuses it
  // by its permission; Firefox writes on a click whatever its permissions say, so there a
  // refusal is the one a browser gives, stood in for.
  const refusals = {
    refused: browserName === "chrome" ? null : () => {
      navigator.clipboard.writeText = () => Promise.reject(new DOMException("refused", "NotAllowedError"));
    },
    absent: () => Object.defineProperty(Navigator.prototype, "clipboard",
      { get: () => undefined, configurable: true }),
  };
  for (const [how, before] of Object.entries(refusals)) {
    const other = await open(`the clipboard ${how}`, before);
    if (!before) await other.context.overridePermissions(origin, []);
    // The refusal is one: a clipboard the page could write would prove nothing here.
    const writes = await other.page.evaluate(() => (navigator.clipboard
      ? navigator.clipboard.writeText("x").then(() => "written", () => "refused") : "absent"));
    check(writes === how, `the clipboard stood in as ${how} is ${writes}`);
    await other.page.keyboard.press("y");
    await other.page.click("#copy");
    await sent(other.page, true, `Copy with the clipboard ${how}`);
    shown = await dialog(other.page);
    differs(shown.blob, { [items[0].id]: { status: "ok", note: "" } }, `Copy with the clipboard ${how}`);
    console.log(`clipboard ${how}: the box holds ${shown.blob.length} characters` +
      (other.errors.length ? `; the page's script reported ${other.errors.join("; ")}` : ""));
    await other.context.close();
  }

  // storage throws: the page renders, answers, and saves.
  const refused = await open("storage refused", () => Object.defineProperty(window, "localStorage", {
    get() { throw new DOMException("The operation is insecure.", "SecurityError"); },
    configurable: true,
  }));
  now = await state(refused.page);
  check(now.stored === "refused", `the stand-in did not refuse storage: ${now.stored}`);
  check(now.shown === items[0].title && now.progress.startsWith(`0 of ${items.length} done`),
    `with storage refused the page shows "${now.shown}", "${now.progress}"`);
  await refused.page.keyboard.press("y");
  now = await state(refused.page);
  const first = { [items[0].id]: { status: "ok", note: "" } };
  check(same(recorded(now.answers), first) && now.pos === 1,
    `with storage refused Y recorded ${JSON.stringify(now.answers)}`);
  await refused.page.click("#save");
  await sent(refused.page, true, "Save with storage refused");
  differs((await dialog(refused.page)).blob, first, "Save's box with storage refused");
  const kept = await downloaded(refused.downloads, BUNDLE.filename);
  if (check(kept, "with storage refused Save downloaded nothing")) {
    differs(kept, first, "the file Save downloaded with storage refused");
  }
  check(!refused.errors.length, `with storage refused the page's script failed: ${refused.errors.join("; ")}`);
  console.log(`storage refused: the page answers and saves (${refused.errors.length} errors)`);
  await refused.context.close();
} finally {
  await browser.close();
  server.close();
  for (const made of folders) rmSync(made, { recursive: true, force: true });
}
console.log(failures.length ? `${failures.length} failure(s) in ${browserName}` : `${browserName}: all held`);
process.exit(failures.length ? 1 : 0);
