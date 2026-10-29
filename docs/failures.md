# When manuscript-guard itself fails

A failure of the tool's own, not a finding about your manuscript, ends in one sentence:

```text
manuscript-guard: check stopped on an error in manuscript-guard itself, not in your files: KeyError: 'G7'
It is recorded on this machine in ~\AppData\Local\manuscript-guard\reports, as 3f2a9c01b4de.json; nothing was sent. `manuscript-guard report-issue --last` shows the report to send.
```

The command exits 2, as when it could not run at all, so a script reading the exit code does
not take it for a failing check. A gate that fails inside `check` is still reported as
`gate-errored`, and fails at every stage: a gate that could not check has not passed.

## What is recorded, and where

One file per fault, in a folder of yours rather than of the project's, so that no repository,
package or submission picks it up:

| System | Folder |
|---|---|
| Windows | `%LOCALAPPDATA%\manuscript-guard\reports` |
| macOS | `~/Library/Application Support/manuscript-guard/reports` |
| Linux and others | `$XDG_STATE_HOME/manuscript-guard/reports` (`~/.local/state/...`) |

A record holds the tool's version, Python's, the system's name, the command, the names of the
flags you gave (never their values), the error's type, where in the tool it happened (file,
line and function), how often and when it was met, and the error's message with your
project's folder, your home folder, e-mail addresses, credentials held in the environment and
the names and ORCIDs in `authors.yaml` replaced by labels. Never the contents of a file, and
never the environment. The newest twenty faults are kept.

The replacement is a convenience. A path written another way, a name `authors.yaml` does not
list, a listed name written in another case (as in a lowercase citation key, `lovelace2020`),
or a line of your manuscript quoted in the error's message stays as it was; read a record
before you send it to anyone. Its limits are listed under "Known gaps" in
[DESIGN.md](../DESIGN.md).

Hooks record their failures too, without a word, since a hook must not stop the agent's tool
call. The next session's start says once that the hooks failed since a date, because a check a
hook holds may not have run.

## Reporting it

```bash
manuscript-guard report-issue --last
```

writes a report of the failure met last, prints all of it, writes it beside the records, and
gives two addresses: a search of the project's issues for its fingerprint, so that a fault
already reported is found first, and the new-issue page with the report filled in. Read the
report, then open the page and post it yourself; `--open` opens it in your browser. Nothing is
posted until you click Submit.

- `report-issue --list` lists the failures recorded, and `report-issue <fingerprint>` (its
  first characters will do) writes a report of one of them.
- The error's message is left out, since it can quote your files; `--with-message` adds it,
  with the replacements above.
- `--note "..."` adds what you ran and what you expected. Make up the smallest text that shows
  the fault rather than pasting your manuscript's own sentences.
- `report-issue --title "..." --note "..."` writes a report of something else: a result that
  is wrong without any error, or a suggestion.
- A report longer than an address can carry is to be pasted: from the file it was written
  to, or, with recording off, from the report printed in the terminal. An address too long to
  hand to a browser opens the page with the title only, and the body is pasted the same way.

[CONTRIBUTING.md](../CONTRIBUTING.md) says what else helps, and how to report a gate that got
something wrong.

## Nothing is sent

Nothing in this goes over the network: `report-issue` prints, writes a file and, with
`--open`, hands an address to your browser. An agent that runs `report-issue --open` is
stopped by the plugin's hook until you say yes.

| Variable | Effect |
|---|---|
| `MANUSCRIPT_GUARD_NO_REPORTS=1` | record nothing |
| `MANUSCRIPT_GUARD_REPORTS=<folder>` | keep the records there instead |
| `MANUSCRIPT_GUARD_DEBUG=1` | let the error through as a Python traceback |
| `CI` set (as CI services do) | print the traceback and record nothing |
