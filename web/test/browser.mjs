// The built site in a real browser, served as GitHub Pages serves it (no policy header). The
// landing page at / loads its style and every picture it names, and asks no other host for
// anything. The audit page at /audit/ starts under its own Content-Security-Policy, each
// case's report is the command line's word for word, no audit sends a request anywhere, a run
// it refuses leaves no report on screen, and "Test the rules" finds every forbidden request
// refused.
//
//   node web/test/browser.mjs <site> <cases> chrome|firefox [executable]
//
// <site> is what web/build.py writes: the landing page, and the audit page in audit/.
// <cases> holds cases.json, [{"name", "paper", "against": [...], "expect"}], and the files it
// names; "expect" names a file holding what the command line printed.
import { createServer } from "node:http";
import { existsSync, readFileSync, statSync } from "node:fs";
import { extname, join, normalize, resolve, sep } from "node:path";
import puppeteer from "puppeteer-core";

const [site, casesDir, browserName, given] = process.argv.slice(2);
const TYPES = { ".html": "text/html; charset=utf-8", ".js": "text/javascript", ".mjs": "text/javascript",
  ".css": "text/css", ".json": "application/json", ".wasm": "application/wasm",
  // The landing page's: a picture sent under another type is not drawn.
  ".svg": "image/svg+xml", ".png": "image/png", ".mp4": "video/mp4", ".vtt": "text/vtt" };
const KNOWN = {
  chrome: ["/usr/bin/google-chrome", "C:/Program Files/Google/Chrome/Application/chrome.exe",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"],
  firefox: ["/usr/bin/firefox", "C:/Program Files/Mozilla Firefox/firefox.exe",
    "/Applications/Firefox.app/Contents/MacOS/firefox"],
};
const executable = given || process.env[browserName.toUpperCase()] ||
  KNOWN[browserName].find((path) => existsSync(path));
if (!executable) {
  console.error(`no ${browserName} found: name it as the fourth argument`);
  process.exit(2);
}

// The site at /, and the test cases at /__cases__/, which no built site has. A folder's
// address is its index.html, as on GitHub Pages.
const AUDIT = "/audit/";
function serve(request, response) {
  const path = decodeURIComponent(new URL(request.url, "http://x").pathname);
  const [folder, named] = path.startsWith("/__cases__/")
    ? [resolve(casesDir), path.slice("/__cases__/".length)] : [resolve(site), path.slice(1)];
  const rest = !named || named.endsWith("/") ? named + "index.html" : named;
  const file = normalize(join(folder, rest));
  if (!file.startsWith(folder + sep) || !existsSync(file) || !statSync(file).isFile()) {
    response.writeHead(404).end();
    return;
  }
  response.writeHead(200, { "Content-Type": TYPES[extname(file)] || "application/octet-stream" });
  response.end(readFileSync(file));
}
const server = createServer(serve);
await new Promise((ready) => server.listen(0, "127.0.0.1", ready));
const origin = `http://127.0.0.1:${server.address().port}`;

const failures = [];
const fail = (what) => { failures.push(what); console.error(`FAIL ${browserName}: ${what}`); };
// GitHub's Ubuntu runners let Chrome make no sandbox of its own (AppArmor). The sandbox keeps
// the browser from the machine, and has no part in the page's policy, which is what is tested.
const args = browserName === "chrome" && process.env.CI ? ["--no-sandbox"] : [];
const browser = await puppeteer.launch({ browser: browserName, executablePath: executable, headless: true, args });
try {
  const front = await browser.newPage();
  const asked = [];
  front.on("request", (request) => asked.push(request.url()));
  await front.goto(origin + "/", { waitUntil: "load" });
  const shown = await front.evaluate(() => ({
    // style.css defines --ink; a style the policy refused leaves it undefined.
    styled: getComputedStyle(document.body).getPropertyValue("--ink").trim() !== "",
    pictures: document.images.length,
    broken: [...document.images].filter((image) => !image.complete || !image.naturalWidth)
      .map((image) => image.currentSrc || image.src),
  }));
  if (!shown.styled) fail("the landing page loaded without its style");
  if (!shown.pictures) fail("the landing page shows no picture");
  if (shown.broken.length) fail(`the landing page did not load ${shown.broken.join(", ")}`);
  // Over the network only: Firefox loads a font of its own from a data: address.
  const away = asked.filter((url) => /^(https?|wss?):/.test(url) && !url.startsWith(origin));
  if (away.length) fail(`the landing page asked ${away.join(", ")}`);
  console.log(`landing page: ${shown.pictures} pictures, ${shown.broken.length} not loaded, ` +
    `${asked.length} requests, ${away.length} to another host`);
  await front.close();

  const page = await browser.newPage();
  page.setDefaultTimeout(600000);
  page.setDefaultNavigationTimeout(300000);
  const started = Date.now();
  await page.goto(origin + AUDIT);
  await page.waitForFunction("window.mgReady || /could not start/.test(document.getElementById('status').textContent)");
  const status = await page.$eval("#status", (element) => element.textContent);
  console.log(`${await browser.version()}: ${status} (${((Date.now() - started) / 1000).toFixed(1)} s)`);
  if (!status.startsWith("Ready")) fail(`the page did not start: ${status}`);

  // At the top, the release the page was built from, which manifest.json names; the loading
  // bar gone once the page is ready; and the browser's own controls following a dark setting.
  const { manuscript_guard: version } = JSON.parse(readFileSync(join(site, "audit", "manifest.json"), "utf-8"));
  const named = await page.waitForFunction(
    (version) => document.getElementById("version").textContent.includes(`manuscript-guard ${version},`),
    { timeout: 10000 }, version).then(() => true, () => false);
  const top = await page.evaluate(() => ({
    version: document.getElementById("version").textContent,
    link: document.querySelector("#version a")?.href,
    loading: !document.getElementById("progress").hidden,
    scheme: getComputedStyle(document.documentElement).colorScheme,
  }));
  if (!named) fail(`the page does not say it is ${version}: "${top.version}"`);
  if (top.link !== `https://github.com/BasileChretien/manuscript-guard/releases/tag/v${version}`) {
    fail(`the page's link to what changed is ${top.link}`);
  }
  if (top.loading) fail("the loading bar is still shown once the page is ready");
  if (!/\bdark\b/.test(top.scheme)) fail(`the page's controls follow no dark setting: "${top.scheme}"`);
  console.log(`top of the page: "${top.version}", controls: ${top.scheme}`);
  // The percentage counted what the manifest says the start fetches, nearly all of it, and
  // reached the top of its bar: a file left out of `bytes` would pass 100%, one counted twice
  // or not at all would stop short.
  const counted = await page.evaluate(() => ({ ...window.mgLoading }));
  const share = counted.expected ? counted.received / counted.expected : 0;
  if (!counted.expected || share < 0.98 || share > 1.02) {
    fail(`the start received ${counted.received} bytes of the ${counted.expected} the manifest names`);
  }
  if (counted.shown < 97) fail(`the bar stopped at ${counted.shown}% before the page was ready`);
  console.log(`loading: ${counted.received} of ${counted.expected} bytes counted, bar at ${counted.shown}%`);

  // The files of the cases folder named, chosen as a reader chooses them, and the audit run.
  const choose = (paper, against) => page.evaluate(async (paper, against) => {
    const put = async (id, names) => {
      const files = new DataTransfer();
      for (const name of names) {
        const blob = await (await fetch("/__cases__/" + encodeURIComponent(name))).blob();
        files.items.add(new File([blob], name));
      }
      document.getElementById(id).files = files.files;
    };
    await put("paper", [paper]);
    await put("against", against);
    window.mgLast = null;
    document.getElementById("run").click();
    while (!window.mgLast) await new Promise((wait) => setTimeout(wait, 100));
    return window.mgLast;
  }, paper, against);

  const cases = JSON.parse(readFileSync(join(casesDir, "cases.json"), "utf-8"));
  for (const one of status.startsWith("Ready") ? cases : []) {
    const result = await choose(one.paper, one.against || []);
    if (result.error) {
      fail(`${one.name}: the audit could not run: ${result.error}`);
      continue;
    }
    // What the command line printed, its notes and its exit code (check.py).
    const said = JSON.parse(readFileSync(join(casesDir, one.expect), "utf-8"));
    const wrong = ["out", "err", "code"].filter((part) =>
      (typeof said[part] === "string" ? said[part].replace(/\r\n/g, "\n") : said[part]) !== result[part]);
    if (wrong.length) {
      fail(`${one.name}: the page's ${wrong.join(", ")} not the command line's`);
      console.error(`--- command line\n${said.out}${said.err}\n--- page\n${result.out}${result.err}`);
    }
    const elsewhere = result.sent.filter((entry) => !entry.url.startsWith(origin));
    if (elsewhere.length) fail(`${one.name}: the audit sent ${elsewhere.map((e) => e.url).join(", ")}`);
    // The run said it had ended, and its PDF opens in a tab of its own (window.open, stood in
    // for here) from an address of the browser's, not from anywhere the page sends to.
    const after = await page.evaluate(() => {
      const shown = { ran: document.getElementById("runtext").textContent,
        moving: !document.getElementById("runbar").hidden,
        pdf: !document.getElementById("openpdf").hidden, opened: null };
      if (shown.pdf) {
        const own = window.open;
        window.open = (address) => { shown.opened = address; return null; };
        document.getElementById("openpdf").click();
        window.open = own;
      }
      return shown;
    });
    if (!after.ran.startsWith("Audited ") || after.moving) {
      fail(`${one.name}: after the run the page says "${after.ran}"${after.moving ? ", its bar moving" : ""}`);
    }
    if (result.pdf && result.pdf.data && !(after.pdf && /^blob:/.test(after.opened || ""))) {
      fail(`${one.name}: the PDF made does not open (${after.pdf ? after.opened : "no button"})`);
    }
    console.log(`${one.name}: ${wrong.length ? "DIFFERENT" : "same report, notes and exit code"}, ` +
      `${(result.ms / 1000).toFixed(1)} s, ${result.sent.length} requests`);
  }

  // A run the page refuses, two outputs of one name, after a report is on screen: it leaves
  // no report for "Save the report" to save as this one's (round 2 of #527).
  const one = cases.find((each) => (each.against || []).length);
  if (status.startsWith("Ready") && one) {
    const twice = [one.against[0], one.against[0]];
    const refused = await choose(one.paper, twice);
    const left = await page.evaluate(() => ({
      hidden: document.getElementById("result").hidden,
      report: document.getElementById("report").textContent,
    }));
    if (!/two of the files chosen are named/.test(refused.error || "")) {
      fail(`two outputs named ${twice[0]}: not refused (${refused.error || "it ran"})`);
    }
    if (!left.hidden || left.report) fail("a refused run left the last report on screen");
    console.log(`two outputs of one name: ${refused.error ? "refused" : "run"}, ` +
      `${left.hidden && !left.report ? "no report left" : "the last report left"}`);
  } else if (status.startsWith("Ready")) {
    // Not passed over without a word (round 1 of #535).
    fail("no case has an output: the refused run was not tried");
  }

  await page.click("#probe");
  const probe = await page.waitForFunction("window.mgProbe").then((handle) => handle.jsonValue());
  for (const [what, how] of Object.entries(probe.tried)) {
    console.log(`  ${what}: ${how}`);
    if (how !== "refused by the rules") fail(`the rules let through: ${what}`);
  }
  if (Object.keys(probe.tried).length < 7) fail("Test the rules tried fewer than seven requests");
} finally {
  await browser.close();
  server.close();
}
console.log(failures.length ? `${failures.length} failure(s) in ${browserName}` : `${browserName}: all held`);
process.exit(failures.length ? 1 : 0);
