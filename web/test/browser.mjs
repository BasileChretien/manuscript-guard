// The built page in a real browser, served as GitHub Pages serves it (no policy header):
// it starts under its own Content-Security-Policy, each case's report is the command line's
// word for word, no audit sends a request anywhere, and "Test the rules" finds every
// forbidden request refused.
//
//   node web/test/browser.mjs <site> <cases> chrome|firefox [executable]
//
// <cases> holds cases.json, [{"name", "paper", "against": [...], "expect"}], and the files it
// names; "expect" names a file holding what the command line printed.
import { createServer } from "node:http";
import { existsSync, readFileSync } from "node:fs";
import { extname, join, normalize, resolve, sep } from "node:path";
import puppeteer from "puppeteer-core";

const [site, casesDir, browserName, given] = process.argv.slice(2);
const TYPES = { ".html": "text/html; charset=utf-8", ".js": "text/javascript", ".mjs": "text/javascript",
  ".css": "text/css", ".json": "application/json", ".wasm": "application/wasm" };
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

// The site at /, and the test cases at /__cases__/, which no built site has.
function serve(request, response) {
  const path = decodeURIComponent(new URL(request.url, "http://x").pathname);
  const [folder, rest] = path.startsWith("/__cases__/")
    ? [resolve(casesDir), path.slice("/__cases__/".length)] : [resolve(site), path.slice(1) || "index.html"];
  const file = normalize(join(folder, rest));
  if (!file.startsWith(folder + sep) || !existsSync(file)) {
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
  const page = await browser.newPage();
  page.setDefaultTimeout(600000);
  page.setDefaultNavigationTimeout(300000);
  const started = Date.now();
  await page.goto(origin + "/index.html");
  await page.waitForFunction("window.mgReady || /could not start/.test(document.getElementById('status').textContent)");
  const status = await page.$eval("#status", (element) => element.textContent);
  console.log(`${await browser.version()}: ${status} (${((Date.now() - started) / 1000).toFixed(1)} s)`);
  if (!status.startsWith("Ready")) fail(`the page did not start: ${status}`);

  const cases = JSON.parse(readFileSync(join(casesDir, "cases.json"), "utf-8"));
  for (const one of status.startsWith("Ready") ? cases : []) {
    const result = await page.evaluate(async (paper, against) => {
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
    }, one.paper, one.against || []);
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
    console.log(`${one.name}: ${wrong.length ? "DIFFERENT" : "same report, notes and exit code"}, ` +
      `${(result.ms / 1000).toFixed(1)} s, ${result.sent.length} requests`);
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
