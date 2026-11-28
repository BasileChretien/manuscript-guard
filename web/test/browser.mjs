// The built site in a real browser, served as GitHub Pages serves it (no policy header). The
// landing page at / loads its style and every picture it names, and asks no other host for
// anything. The audit page at /audit/ starts under its own Content-Security-Policy, each
// case's report is the command line's word for word and its PDF is shown in the page, no
// audit sends a request anywhere, a run it refuses leaves no report on screen, and "Test the
// rules" finds every forbidden request refused, a frame from elsewhere among them.
//
//   node web/test/browser.mjs <site> <cases> chrome|firefox [executable] [--hosted]
//
// <site> is what web/build.py writes: the landing page, and the audit page in audit/. With
// `--hosted`, it is a page web/build.py --host built for a journal's host, served at /check/,
// another address than the site's, with no landing page; its cases are hosted-cases.json, and
// it must also show the host's name, logo, accent and contact line, keep the release it runs,
// its licences and the proof that nothing is uploaded, show each journal's rules as it serves
// them, preselect the journal ?journal=<slug> names, and say so where it offers none.
// <cases> holds cases.json, [{"name", "paper", "against": [...], "expect", "form"}], and the
// files it names; "expect" names a file holding what the command line printed, "form" the
// page's boxes to set, by id, for the options the command line was given, "tracked", where
// the copy with tracked changes is asked for, how many corrections it must track, and
// "made", where the journal's form is filled, the files the page must make of it, by the day
// the page dates them (made.mjs).
import { createServer } from "node:http";
import { existsSync, readFileSync, statSync } from "node:fs";
import { extname, join, normalize, resolve, sep } from "node:path";
import puppeteer from "puppeteer-core";
import { caseHeld, dayOf } from "./made.mjs";

const hosted = process.argv.includes("--hosted");
const [site, casesDir, browserName, given] = process.argv.slice(2).filter((arg) => arg !== "--hosted");
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
// A hosted page is the audit page alone, served where its host puts it, at another address.
const HOSTED_AT = "/check/";
const PAGE_AT = hosted ? HOSTED_AT : AUDIT;
function serve(request, response) {
  const path = decodeURIComponent(new URL(request.url, "http://x").pathname);
  if (hosted && !path.startsWith("/__cases__/") && !path.startsWith(PAGE_AT)) {
    response.writeHead(404).end();
    return;
  }
  const [folder, named] = path.startsWith("/__cases__/")
    ? [resolve(casesDir), path.slice("/__cases__/".length)]
    : hosted ? [resolve(site), path.slice(PAGE_AT.length)] : [resolve(site), path.slice(1)];
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
  // A hosted page has no landing page: its host's site is around it.
  if (!hosted) await landingHeld();

  const page = await browser.newPage();
  page.setDefaultTimeout(600000);
  page.setDefaultNavigationTimeout(300000);
  const started = Date.now();
  await page.goto(origin + PAGE_AT);
  await page.waitForFunction("window.mgReady || /could not start/.test(document.getElementById('status').textContent)");
  const status = await page.$eval("#status", (element) => element.textContent);
  console.log(`${await browser.version()}: ${status} (${((Date.now() - started) / 1000).toFixed(1)} s)`);
  if (!status.startsWith("Ready")) fail(`the page did not start: ${status}`);

  // At the top, the release the page was built from, which manifest.json names; the loading
  // bar gone once the page is ready; and the browser's own controls following a dark setting.
  const manifest = JSON.parse(readFileSync(join(site, ...(hosted ? [] : ["audit"]), "manifest.json"), "utf-8"));
  const { manuscript_guard: version } = manifest;
  // A hosted page is built when its host builds it, and says which release runs it.
  const release = hosted ? `Run by manuscript-guard ${version} (` : `manuscript-guard ${version},`;
  const named = await page.waitForFunction(
    (release) => document.getElementById("version").textContent.includes(release),
    { timeout: 10000 }, release).then(() => true, () => false);
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

  // The files of the cases folder named, chosen as a reader chooses them, every box of the
  // form as the page starts and those of the case set, each said changed as a reader's
  // typing says it, and the audit run.
  const choose = (paper, against, form = {}) => page.evaluate(async (paper, against, form) => {
    const put = async (id, names) => {
      const files = new DataTransfer();
      for (const name of names) {
        const blob = await (await fetch("/__cases__/" + encodeURIComponent(name))).blob();
        files.items.add(new File([blob], name));
      }
      document.getElementById(id).files = files.files;
    };
    await put("paper", [paper]);
    document.getElementById("paper").dispatchEvent(new Event("change", { bubbles: true }));
    await put("against", against);
    for (const box of document.getElementById("form").querySelectorAll("input, select, textarea")) {
      if (box.type === "file") continue;
      if (box.type === "checkbox") box.checked = Boolean(form[box.id]);
      else box.value = form[box.id] ?? "";
      box.dispatchEvent(new Event("change", { bubbles: true }));
    }
    window.mgLast = null;
    document.getElementById("run").click();
    while (!window.mgLast) await new Promise((wait) => setTimeout(wait, 100));
    return window.mgLast;
  }, paper, against, form);
  // The day in the page, in this computer's own time, as it dates the journal's form.
  const today = async () => dayOf(await page.evaluate(() => {
    const now = new Date();
    return [now.getFullYear(), now.getMonth() + 1, now.getDate()];
  }));

  const cases = JSON.parse(readFileSync(join(casesDir, hosted ? "hosted-cases.json" : "cases.json"), "utf-8"));
  for (const one of status.startsWith("Ready") ? cases : []) {
    // The case, and the files the page made of the journal's form in it held to those the
    // command line was given, dated the day the case began or ended on; none where the form
    // is empty.
    const { result, unlike } = await caseHeld(today,
      () => choose(one.paper, one.against || [], one.form || {}), one.made);
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
    // The run said it had ended, and its PDF is shown in the page, in a frame whose address is
    // the browser's own, not anywhere the page sends to (2026-11-12: the PDF inside the page, not
    // in a tab of its own). In Chrome the frame must hold a PDF under the page's policy, which
    // a blob: document takes; Firefox's viewer is out of puppeteer's reach, and the frame's
    // address is what is held there.
    const after = await page.evaluate(() => ({
      ran: document.getElementById("runtext").textContent,
      moving: !document.getElementById("running").hidden,
      shown: !document.getElementById("pdfbox").hidden,
      address: document.getElementById("pdfview").getAttribute("src") || "",
    }));
    if (!after.ran.startsWith("Checked ") || after.moving) {
      fail(`${one.name}: after the run the page says "${after.ran}"${after.moving ? ", its steps still shown" : ""}`);
    }
    let held = null;
    if (browserName === "chrome" && after.shown) {
      const frame = await page.waitForFrame((each) => each.url().startsWith("blob:"), { timeout: 20000 })
        .catch(() => null);
      held = frame ? await frame.evaluate(() => document.contentType).catch(() => null) : null;
    }
    if (result.pdf && result.pdf.data && !(after.shown && /^blob:/.test(after.address)
        && (browserName !== "chrome" || held === "application/pdf"))) {
      fail(`${one.name}: the PDF made is not shown in the page (${after.shown ? `${after.address}, ${held}` : "no frame"})`);
    }
    // The frame was not refused by the page's policy, which a browser reports as it refuses
    // (round 1 of #644): in Firefox, whose viewer puppeteer cannot reach, this is what holds.
    const framesRefused = await page.evaluate(
      () => window.mgRefused.filter((each) => each.rule === "frame-src"));
    if (framesRefused.length) {
      fail(`${one.name}: the policy refused the PDF's frame: ${JSON.stringify(framesRefused)}`);
    }
    // The copy with tracked changes the reader asked for: as many corrections tracked as the
    // command line's `--tracked` tracks, and its button shown; none where it was not asked.
    if (one.tracked !== undefined) {
      // The copy's bytes are counted in the page: a Uint8Array does not come back out of it
      // whole in Firefox, whose protocol gives it as no data (CI's web job, #786).
      const { button, bytes } = await page.evaluate(() => ({
        button: !document.getElementById("savetracked").hidden,
        bytes: window.mgLast?.tracked?.data?.byteLength ?? 0,
      }));
      if (!result.tracked || !bytes || result.tracked.tracked !== one.tracked || !button) {
        fail(`${one.name}: the copy tracks ${result.tracked ? result.tracked.tracked ?? result.tracked.error : "nothing"} `
          + `of the command line's ${one.tracked} corrections in ${bytes} bytes`
          + `${button ? "" : ", and no button is shown"}`);
      }
    } else if (result.tracked) {
      fail(`${one.name}: a copy with tracked changes was made though none was asked for`);
    }
    // The journal's profile and the authors' names the form made (caseHeld, above).
    if (unlike) fail(`${one.name}: ${unlike}`);
    console.log(`${one.name}: ${wrong.length ? "DIFFERENT" : "same report, notes and exit code"}, ` +
      `${(result.ms / 1000).toFixed(1)} s, ${result.sent.length} requests`);
  }

  // A run the page refuses, two outputs of one name, after a report is on screen: it leaves
  // no report or PDF on screen as this one's (round 2 of #527), and no step shown as under way
  // (round 1 of #644).
  // A hosted page runs the same code, which the site's run holds: its cases have no output.
  const one = cases.find((each) => (each.against || []).length);
  if (hosted) {
    // Nothing to try here.
  } else if (status.startsWith("Ready") && one) {
    const twice = [one.against[0], one.against[0]];
    const refused = await choose(one.paper, twice);
    const left = await page.evaluate(() => ({
      hidden: document.getElementById("result").hidden,
      report: document.getElementById("pdfview").getAttribute("src") || "",
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

  // These two call the page's own functions, which the site's run holds; on a hosted page a
  // real run's PDF is still on screen, where the site's refused run has cleared it.
  // A run whose PDF could not be made shows the report as the command line prints it, the
  // only report there then is, and says so (round 1 of #644).
  if (status.startsWith("Ready") && !hosted) {
    const fallback = await page.evaluate(() => {
      window.mgShowReport({ out: "The report as text.\n", err: "", ms: 1000, view: null,
        pdf: { error: "it could not be written" }, commented: null }, "paper.md");
      return { shown: !document.getElementById("astext").hidden,
        text: document.getElementById("report").textContent,
        said: document.getElementById("done").textContent,
        frame: !document.getElementById("pdfbox").hidden };
    });
    if (!fallback.shown || fallback.text !== "The report as text.\n" || fallback.frame
        || !/report is below as text/.test(fallback.said)) {
      fail(`a run with no PDF shows no report: ${JSON.stringify(fallback)}`);
    }
    console.log(`no PDF: ${fallback.shown ? "the report shown as text" : "NO REPORT"}`);
  }

  // A check that fails after a step has started leaves no step shown as under way, and its
  // message shown (round 2 of #644).
  if (status.startsWith("Ready") && !hosted) {
    const failed = await page.evaluate(() => {
      window.mgRun.runStarted("paper.md", { lookup: false, docx: false });
      window.mgRun.stepped({ key: "read", done: 0, total: 0 });
      window.mgRun.runEnded("The check could not run: a test.", { failed: true });
      return { spinning: Boolean(document.querySelector("#steps li.now")),
        shown: !document.getElementById("running").hidden };
    });
    if (failed.spinning || !failed.shown) fail(`a failed check: ${JSON.stringify(failed)}`);
  }
  // No frame of the PDF's refused by the policy, its event come late or not (round 2 of #644).
  const lateFrames = await page.evaluate(() => window.mgRefused.filter(
    (each) => each.rule === "frame-src" && /^blob:/.test(each.url || "")));
  if (lateFrames.length) fail(`the policy refused a PDF's frame: ${JSON.stringify(lateFrames)}`);

  // The button stands under the question "Is my paper uploaded?", which a reader opens first.
  await page.$eval("#probe", (button) => { button.closest("details").open = true; });
  await page.click("#probe");
  const probe = await page.waitForFunction("window.mgProbe").then((handle) => handle.jsonValue());
  for (const [what, how] of Object.entries(probe.tried)) {
    console.log(`  ${what}: ${how}`);
    if (how !== "refused by the rules") fail(`the rules let through: ${what}`);
  }
  if (Object.keys(probe.tried).length < 8) fail("Test the rules tried fewer than eight requests");

  if (status.startsWith("Ready")) await rulesLinkHeld(page);
  if (hosted && status.startsWith("Ready")) await hostHeld(page, manifest);
} finally {
  await browser.close();
  server.close();
}
console.log(failures.length ? `${failures.length} failure(s) in ${browserName}` : `${browserName}: all held`);
process.exit(failures.length ? 1 : 0);

// A link with the journal's rules (web/rules.js): the form filled and its link made, shown to
// copy where the browser does not let the page copy it; a page opened at the link holds the
// same rules in its form and says where they came from, its address not written to; and a
// link that is not one the page made fills nothing and says so.
async function rulesLinkHeld(page) {
  const ready = "window.mgRulesRead || /could not start/.test(document.getElementById('status').textContent)";
  await page.goto(origin + PAGE_AT);
  await page.waitForFunction("window.mgReady || /could not start/.test(document.getElementById('status').textContent)");
  const typed = { jname: "Journal of Links", jurl: "https://example.org/authors", jabstract: "250",
    jtables: "4", jsections: "Introduction\nMéthodes", jblinding: "open" };
  const { link, unmade, long } = await page.evaluate(async (typed) => {
    const note = document.getElementById("rulesnote");
    document.getElementById("journalbox").open = true;
    const said = async () => {
      note.textContent = "";
      document.getElementById("copyrules").click();
      while (!note.textContent) await new Promise((wait) => setTimeout(wait, 50));
      return { note: note.textContent, shown: !document.getElementById("ruleslink").hidden };
    };
    for (const [id, value] of Object.entries({ ...typed, jabstract: "4.5" })) {
      const box = document.getElementById(id);
      box.value = value;
      box.dispatchEvent(new Event("input", { bubbles: true }));
    }
    document.getElementById("jst-funding").checked = true;
    // A limit the checker refuses makes no link, and the checker names its box, before the
    // form's shape is asked (rounds 1 and 3 of #847).
    const unmade = await said();
    // Rules that pack short and unpack to more than a page opened at the link takes.
    document.getElementById("jabstract").value = typed.jabstract;
    document.getElementById("jsections").value = Array(100).fill("a".repeat(2000)).join("\n");
    const long = await said();
    document.getElementById("jsections").value = typed.jsections;
    note.textContent = "";
    document.getElementById("copyrules").click();
    while (document.getElementById("ruleslink").hidden) await new Promise((wait) => setTimeout(wait, 50));
    return { link: document.getElementById("ruleslink").value, unmade, long };
  }, typed);
  if (unmade.shown || !unmade.note.startsWith("No link was made: the limit on the words in the abstract")) {
    fail(`a link of rules the checker refuses: ${JSON.stringify(unmade)}`);
  }
  if (long.shown || long.note !== "No link was made: the rules are too long for a link.") {
    fail(`a link of rules that unpack to too much: ${JSON.stringify(long)}`);
  }
  if (!link.startsWith(`${origin}${PAGE_AT}#rules=`)) fail(`the link with the rules is "${link.slice(0, 80)}"`);
  const opened = await browser.newPage();
  opened.setDefaultTimeout(600000);
  await opened.goto(link);
  await opened.waitForFunction(ready);
  const filled = await opened.evaluate((ids) => ({
    values: Object.fromEntries(ids.map((id) => [id, document.getElementById(id).value])),
    funding: document.getElementById("jst-funding").checked,
    ethics: document.getElementById("jst-ethics").checked,
    note: document.getElementById("rulesnote").textContent,
    address: location.href,
  }), Object.keys(typed));
  if (JSON.stringify(filled.values) !== JSON.stringify(typed) || !filled.funding || filled.ethics) {
    fail(`a link's rules filled the form with ${JSON.stringify(filled)}`);
  }
  if (!filled.note.startsWith("These rules came with the link")) fail(`a link's rules said "${filled.note}"`);
  if (filled.address !== link) fail("the page opened at a link with rules wrote to its address");
  await opened.close();
  // A link of base64 that is no deflate: refused, and the form left empty.
  const typedOver = await browser.newPage();
  typedOver.setDefaultTimeout(600000);
  await typedOver.goto(`${origin}${PAGE_AT}#rules=eyJuYW1lIjoiYSJ9`);
  await typedOver.waitForFunction(ready);
  // Said above the form, where it is seen with the form closed (round 1 of #847).
  const refused = await typedOver.evaluate(() => ({
    name: document.getElementById("jname").value,
    note: document.getElementById("journalnote").textContent,
    seen: document.getElementById("journalnote").getClientRects().length > 0,
  }));
  if (refused.name || !refused.seen
    || refused.note !== "The link's rules were not put in the form: it is not a link this page made.") {
    fail(`a link the page did not make: ${JSON.stringify(refused)}`);
  }
  // A link pasted into the page already open is read, though the browser does not load it
  // anew (round 1 of #847).
  await typedOver.evaluate((hash) => {
    window.mgRulesRead = false;
    location.hash = hash;
  }, new URL(link).hash);
  await typedOver.waitForFunction(ready);
  const pasted = await typedOver.evaluate(() => document.getElementById("jname").value);
  if (pasted !== typed.jname) fail(`a link pasted into an open page filled the name with "${pasted}"`);
  await typedOver.close();
  console.log(`a link with the rules: ${link.length} characters, the form filled from it; one typed over: "${refused.note}"`);
}

// What a hosted page must show of its host, and keep of the page; each journal's rules shown
// as it serves them; and the journal a link names chosen, or said not offered, the address
// never written to.
async function hostHeld(page, manifest) {
  const { host } = manifest;
  // The host's accent, light and dark; where it gives none, the page's own teal (round 1 of
  // #791: a host with no accent stopped the check).
  const accents = [...readFileSync(join(site, host.style || "style.css"), "utf-8")
    .matchAll(/--teal: (#[0-9a-f]{6})/g)].map((match) => match[1]).slice(0, 2);
  const shown = await page.evaluate(() => {
    const visible = (element) => Boolean(element) && element.getClientRects().length > 0;
    const logo = document.getElementById("hostlogo");
    const contact = document.getElementById("contact");
    return {
      title: document.title,
      kicker: document.getElementById("kicker").textContent,
      logo: visible(logo) && logo.complete && logo.naturalWidth > 0,
      teal: getComputedStyle(document.documentElement).getPropertyValue("--teal").trim(),
      dark: matchMedia("(prefers-color-scheme: dark)").matches,
      contact: visible(contact) ? contact.textContent : "",
      link: contact.querySelector("a")?.getAttribute("href"),
      options: [...document.getElementById("journal").options].map((option) => option.value),
      picker: visible(document.getElementById("journalpick")),
      // What the page keeps on a host's site: that nothing is uploaded and how to see it,
      // the release, and the licences with pandoc's and poppler's sources.
      private: visible(document.querySelector(".private"))
        && /never uploaded/.test(document.querySelector(".private").textContent),
      probe: Boolean(document.getElementById("probe")),
      sums: Boolean(document.querySelector('a[href="files.sha256"]')),
      gpl: visible(document.querySelector('footer a[href="licences/pandoc-GPL-2.0.txt"]'))
        && visible(document.querySelector('footer a[href="licences/poppler-GPL-2.0.txt"]')),
      pandoc: document.getElementById("src-pandoc").getAttribute("href"),
      poppler: [document.getElementById("src-poppler").getAttribute("href"),
        document.getElementById("build-poppler").getAttribute("href")],
    };
  });
  if (!shown.title.includes(host.name) || !shown.kicker.startsWith(host.name)) {
    fail(`the hosted page does not name its host: "${shown.title}", "${shown.kicker}"`);
  }
  if (host.logo && !shown.logo) fail(`the hosted page shows no logo from ${host.logo}`);
  if (shown.teal !== accents[shown.dark ? 1 : 0]) {
    fail(`the hosted page's accent is ${shown.teal}, not the host's ${accents.join(" or ")}`);
  }
  if (host.contact && (!shown.contact.includes(host.contact.text) || shown.link !== host.contact.link)) {
    fail(`the hosted page's contact line is "${shown.contact}" to ${shown.link}`);
  }
  // The list of the journals offered, and none where the host offers none.
  const offered = host.journals.map((journal) => journal.slug);
  if (shown.picker !== Boolean(offered.length)
      || JSON.stringify(shown.options) !== JSON.stringify(["", ...offered, "other"])) {
    fail(`the hosted page offers ${shown.picker ? shown.options.join(", ") : "no list"}, not ${offered.join(", ") || "none"}`);
  }
  if (!shown.private || !shown.probe || !shown.sums || !shown.gpl || shown.pandoc !== manifest.sources.pandoc
      || shown.poppler.join(" ") !== `${manifest.sources.poppler} ${manifest.sources["poppler-build"]}`) {
    fail(`the hosted page lost what it must keep: ${JSON.stringify(shown)}`);
  }
  console.log(`host: "${shown.kicker}", accent ${shown.teal}, contact "${shown.contact}", ` +
    `${offered.length} journals offered`);

  // Each journal's rules as the page serves them, and the form for another journal put away.
  for (const journal of host.journals) {
    const rules = await page.evaluate((slug) => {
      const list = document.getElementById("journal");
      list.value = slug;
      list.dispatchEvent(new Event("change", { bubbles: true }));
      return { text: document.getElementById("journaltext").textContent,
        shown: !document.getElementById("journalrules").hidden,
        form: !document.getElementById("journalbox").hidden };
    }, journal.slug);
    if (!rules.shown || rules.text !== readFileSync(join(site, journal.file), "utf-8") || rules.form) {
      fail(`${journal.name}: its rules ${rules.shown ? "differ from" : "are not shown as"} ${journal.file}` +
        `${rules.form ? ", and the form for another journal is still shown" : ""}`);
    }
  }

  // A link names a journal: it is chosen, and the address is not written to; one the page
  // does not offer is said, and none is chosen.
  const links = [...(offered.length ? [[offered[0], offered[0]]] : []), ["no-such-journal", ""]];
  for (const [slug, chosen] of links) {
    const address = `${origin}${PAGE_AT}?journal=${slug}`;
    await page.goto(address);
    await page.waitForFunction("window.mgReady || /could not start/.test(document.getElementById('status').textContent)");
    const after = await page.evaluate(() => ({
      value: document.getElementById("journal").value,
      note: document.getElementById("journalnote").hidden ? "" : document.getElementById("journalnote").textContent,
      address: location.href,
    }));
    if (after.value !== chosen || after.address !== address || (!chosen && !after.note.includes(slug))) {
      fail(`?journal=${slug}: ${JSON.stringify(after)}`);
    }
    console.log(`?journal=${slug}: ${after.value ? `${after.value} chosen` : `none chosen, "${after.note}"`}`);
  }
}

// The landing page at /: its style and every picture it names loaded, and no other host asked.
async function landingHeld() {
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
}
