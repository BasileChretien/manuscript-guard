// A link with a journal's rules (item 4 of the editor's list; Basile, 2026-11-26, "A link
// with the rules"): the values of the page's journal form, as app.js `journalForm` gives
// them, compressed into the link after "#rules=". A browser sends no part of an address after
// "#" to the server it asks for the page, so the rules reach whoever opens the link and no
// one else. The authors' names are never in it. Opened, the page reads the link's rules,
// holds them to the form's shape here and to the profile's schema in the checker, as it
// holds a profile the reader chooses, and fills the form from them, or says why it did not.
// Kept apart from app.js so that Node runs it as the page does (web/test/rules.mjs).

export const RULES = "#rules=";
// The longest a link's rules may be, encoded and unpacked: a form filled with the rules of
// any journal is far under both, and a link of more is no link this page made.
export const RULES_CHARS = 16000;
export const RULES_BYTES = 65536;
// The form's values, as `journal_form.profile_of` reads them, and the most a text or a list
// of lines may hold.
const TEXTS = ["name", "url", "date", "blinding"];
const LINES = ["sections", "abstract_headings"];
const KEYS = [...TEXTS, ...LINES, "limits", "statements", "headings"];
const MOST_CHARS = 2000;
const MOST_LINES = 100;
const NOT_MADE = "it is not a link this page made";

const encoded = (bytes) => {
  let text = "";
  for (const byte of bytes) text += String.fromCharCode(byte);
  return btoa(text).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
};

// The form's values as the text after "#rules=": JSON, compressed (deflate), in the letters
// an address keeps as they are (base64url).
export async function packed(form) {
  const stream = new Blob([JSON.stringify(form)]).stream()
    .pipeThrough(new CompressionStream("deflate-raw"));
  return encoded(new Uint8Array(await new Response(stream).arrayBuffer()));
}

// The form's values a link's text holds; refused, with why, where it is too long, is no text
// `packed` makes, or unpacks to more than any journal's rules.
export async function unpacked(text) {
  if (!text || text.length > RULES_CHARS || !/^[A-Za-z0-9_-]+$/.test(text)) {
    throw new Error(NOT_MADE);
  }
  let bytes;
  try {
    bytes = Uint8Array.from(atob(text.replace(/-/g, "+").replace(/_/g, "/")), (c) => c.charCodeAt(0));
  } catch {
    throw new Error(NOT_MADE);
  }
  const reader = new Blob([bytes]).stream()
    .pipeThrough(new DecompressionStream("deflate-raw")).getReader();
  const parts = [];
  let size = 0;
  try {
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      size += value.length;
      if (size > RULES_BYTES) {
        await reader.cancel();
        throw new RangeError("too long");
      }
      parts.push(value);
    }
  } catch (error) {
    throw new Error(error instanceof RangeError ? "it holds more than any journal's rules" : NOT_MADE);
  }
  try {
    return JSON.parse(new TextDecoder("utf-8", { fatal: true })
      .decode(await new Blob(parts).arrayBuffer()));
  } catch {
    throw new Error(NOT_MADE);
  }
}

// Why the values a link holds are not the form's, or "" where they are: only the boxes the
// form has, each holding what its box can, the limits, statements and blindings among those
// `offered` names ({limits, statements, blindings}). What the profile then makes of them is
// the checker's to say (`web.journal_files`).
export function shaped(form, offered) {
  // A line a box holds as it is given: a text box drops a line break (round 1 of #847).
  const text = (value) => typeof value === "string" && value.length <= MOST_CHARS
    && !/[\r\n]/.test(value);
  const lines = (value) => Array.isArray(value) && value.length <= MOST_LINES && value.every(text);
  const mapping = (value) => value !== null && typeof value === "object" && !Array.isArray(value);
  const quoted = (value) => `"${String(value).slice(0, 40)}"`;
  if (!mapping(form)) return "it holds no journal's rules";
  const unknown = Object.keys(form).find((key) => !KEYS.includes(key));
  if (unknown !== undefined) return `it holds ${quoted(unknown)}, which the form has no box for`;
  const untexted = TEXTS.find((key) => key in form && !text(form[key]));
  if (untexted) return `its ${untexted} is not a text the form can hold`;
  const unlined = LINES.find((key) => key in form && !lines(form[key]));
  if (unlined) return `its ${unlined.replace("_", " ")} are not lines the form can hold`;
  if ("limits" in form) {
    if (!mapping(form.limits)) return "its limits are not the form's";
    const other = Object.keys(form.limits).find((key) => !offered.limits.includes(key));
    if (other !== undefined) return `it gives a limit on ${quoted(other)}, which the form has no box for`;
    // Digits alone, as a number box holds them; " 4" it would hold as nothing.
    if (!Object.values(form.limits).every((value) => typeof value === "string" && /^[0-9]{0,7}$/.test(value))) {
      return "a limit it gives is not a number the form can hold";
    }
  }
  if ("statements" in form) {
    if (!lines(form.statements)) return "its statements are not the form's";
    const other = form.statements.find((one) => !offered.statements.includes(one));
    if (other !== undefined) return `it asks for a statement ${quoted(other)}, which the form has no box for`;
  }
  if ("headings" in form) {
    if (!mapping(form.headings) || !Object.values(form.headings).every(text)) {
      return "its statements' headings are not texts the form can hold";
    }
    const other = Object.keys(form.headings).find((key) => !(form.statements || []).includes(key));
    if (other !== undefined) return `it gives a heading for ${quoted(other)}, a statement it does not ask for`;
  }
  if (form.blinding && !offered.blindings.includes(form.blinding)) {
    return `its review is ${quoted(form.blinding)}, which the form does not offer`;
  }
  return "";
}
