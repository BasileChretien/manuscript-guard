// web/rules.js in Node, as the page runs it: a link's rules packed, unpacked and held to the
// form's shape. tests/test_web.py runs this.
//
//   node web/test/rules.mjs < cases.json
//
// Each case is {"pack": form}, answered {"text"}; {"unpack": text}, answered {"form"} or
// {"error"}; or {"shape": form, "offered": {limits, statements, blindings}}, answered
// {"wrong"}, "" where the form's shape is the page's.
import { packed, shaped, unpacked } from "../rules.js";

let input = "";
for await (const chunk of process.stdin) input += chunk;
const answers = [];
for (const one of JSON.parse(input)) {
  if ("pack" in one) {
    answers.push({ text: await packed(one.pack) });
  } else if ("unpack" in one) {
    try {
      answers.push({ form: await unpacked(one.unpack) });
    } catch (error) {
      answers.push({ error: error.message });
    }
  } else {
    answers.push({ wrong: shaped(one.shape, one.offered) });
  }
}
process.stdout.write(JSON.stringify(answers));
