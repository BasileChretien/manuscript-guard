// The files the page made of the journal's form, held to those the command line was given
// (check.py's "made"), as the page dates them: the day it runs the case, in this computer's
// own time. A run that crosses midnight makes the next day's (main's `web` job at #850's
// merge), so check.py gives the files for each day the run may reach, and a case is held to
// those of the day it began or ended on. browser.mjs holds each case so, and
// tests/test_web.py imports this in Node.

/** [year, month, day] as web/app.js writes the date the journal's instructions were read on. */
export const dayOf = ([year, month, day]) =>
  `${year}-${String(month).padStart(2, "0")}-${String(day).padStart(2, "0")}`;

/** What `run` gives, with the days `today` gives just before it and just after it. */
export async function dated(today, run) {
  const begun = await today();
  const result = await run();
  return { result, days: [begun, await today()] };
}

/** "" where `made`, the files the page made, is what check.py's `byDay` gives for one of
 * `days`, the days the case began and ended on, or none where `byDay` is absent (the form
 * empty); else what is wrong with it. */
export function madeHeld(made, byDay, days) {
  const text = JSON.stringify(made);
  if (byDay === undefined) {
    return text === "{}" ? "" : `the page made ${text} of the journal's form, not {}`;
  }
  if (days.some((day) => byDay[day] !== undefined && JSON.stringify(byDay[day]) === text)) return "";
  const each = [...new Set(days)];
  const known = each.filter((day) => byDay[day] !== undefined);
  const missing = each.filter((day) => byDay[day] === undefined);
  const unlike = `the page made ${text} of the journal's form`
    + (known.length ? `, not ${known.map((day) => JSON.stringify(byDay[day])).join(" or ")}` : "");
  return missing.length
    ? `${unlike}, and the case ran on ${missing.join(" and ")}, a day check.py made no files of it `
      + `for (${Object.keys(byDay).join(", ")})`
    : unlike;
}
