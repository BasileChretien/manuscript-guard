# Security

## Reporting a vulnerability

Report it privately, through GitHub's private vulnerability reporting: the repository's
**Security** tab, then **Report a vulnerability**. Please do not open a public issue for
it. Say what someone could do, with what access, and how to make it happen.

## What there is to protect

- **Model providers' API keys.** `review --run` reads each provider's key from the
  environment variable its provider names, once at the start of a run, and from nowhere
  else. A key is never written to disk: not to `paper.yaml`, a review record, a log, or
  what `--dry-run` prints. It travels in one header, to the host `paper.yaml` names for
  that provider and to no other: redirects are not followed, and a message built from a
  provider's answer has the key taken out. Which host that is follows from `paper.yaml`,
  so a provider added there, or a preset whose variable another preset shares, can send a
  key to a host it was not issued for; the prompt before sending names each host.
- **The manuscript.** `review --run` sends it to the models listed in `paper.yaml`
  (`review.models`) once `yes` is typed at the prompt. `--yes` skips the prompt for
  whoever passes it, a script or an agent; the skills tell an agent to ask the author
  first, and nothing enforces it. `--dry-run` shows what would be sent and sends nothing.
- **The author's machine.** The plugin's hooks run on every file edit and every shell
  command an agent makes, and `install-skills` writes files into the user's folders.

## In scope

- **The hooks** (`plugin/hooks/hooks.json`, `src/manuscript_guard/hooks.py`). They run
  `manuscript-guard-hook` before every file edit and every shell command, after a `Write`
  or `Edit`, and when a session starts, on the author's machine. A hook that can be made to run something,
  write anywhere, or reach the network by what a project's files hold is in scope.
- **`install-skills`**, which copies the skills onto the user's machine. A write outside
  the folder it is given, or over a folder it did not write, is in scope.
- **`review --run`**, which sends the manuscript away. A key or the manuscript reaching a
  host other than the provider's is in scope, and so is a key written anywhere.
- **Skill text.** An instruction in a skill that could steer an agent to send the
  manuscript or a key somewhere, to run something downloaded, or to delete the author's
  files is in scope.
- **Reading a project's files.** A `paper.yaml`, a record, or a `.docx` returned by a
  co-author that makes the tool run code, read outside the project, or never finish is in
  scope.

## Out of scope

- What a model provider does with what it is sent: that is between the author and the
  provider.
- The programs the toolkit calls and does not ship: pandoc, R, Zotero and Better BibTeX,
  Word, git.
- A gate that passes what it should have caught. That is a bug: open an issue, and
  [CONTRIBUTING.md](CONTRIBUTING.md) says how to turn the case into a failing test.
- An agent that disregards the skills, and a user who turns the hooks off.
