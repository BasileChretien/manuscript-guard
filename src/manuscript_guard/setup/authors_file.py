"""`authors.yaml` written from the answers: `authors_data`, then `checked_authors`.

The text is written here rather than by a YAML library, so that it reads as a person would
write it and keeps the comment `init` writes on the AI-use statement. Each name and
affiliation is written between double quotation marks, as JSON writes a string, which YAML
reads back as it was; and the file is read back before it is taken, and held to its schema.
"""

from __future__ import annotations

import json
from typing import Any

import yaml

from manuscript_guard.setup.answers import LATER, MISSING, answer


class AuthorsRefused(Exception):
    """Why `authors.yaml` cannot be written from the answers."""




def _string(text: str) -> str:
    return json.dumps(text, ensure_ascii=False)


def _strings(values: list) -> str:
    return "[" + ", ".join(_string(str(value)) for value in values) + "]"


def authors_data(answers: dict) -> dict:
    """`authors.yaml` as the answers give it: each affiliation once, in the order first
    named, and the roles where they were given."""
    authors = answer(answers, "authors")
    texts: list[str] = []
    for author in authors:
        texts += [text for text in author["affiliations"] if text not in texts]
    ids = {text: f"a{number}" for number, text in enumerate(texts, 1)}
    people = []
    for author in authors:
        person = {"given": author["given"], "family": author["family"],
                  "affiliations": [ids[text] for text in author["affiliations"]],
                  "corresponding": bool(author.get("corresponding", False)),
                  "equal_contribution": author.get("equal_contribution", False)}  # fmt: skip
        for key in ("degrees", "orcid", "email", "credit", "funding", "competing_interests"):
            if key in author:
                person[key] = author[key]
        people.append(person)
    data = {"schema": "manuscript-guard/authors/1",
            "affiliations": [{"id": ids[text], "text": text} for text in texts],
            "authors": people}  # fmt: skip
    roles = {}
    statistician = answer(answers, "statistician")
    if statistician not in (MISSING, LATER):
        roles["statistician"] = statistician
    lead = answer(answers, "ethics_lead")
    if isinstance(lead, dict):
        roles["ethics_lead"] = dict(lead)
    if roles:
        data["roles"] = roles
    return data


def _scalar(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, list):
        return _strings(value)
    return _string(str(value))


def authors_text(data: dict) -> str:
    """`data` as the text of `authors.yaml`, with the comment on the AI-use statement that
    `init` writes kept at its end."""
    from manuscript_guard.scaffold import AUTHORS

    lines = ["schema: manuscript-guard/authors/1", "",
             "# Written by `manuscript-guard setup apply` from design/setup.yaml, as the",
             "# authors gave it. It is yours to edit, as any file of the project.", "",
             "affiliations:"]  # fmt: skip
    for entry in data["affiliations"]:
        lines += [f"  - id: {entry['id']}", f"    text: {_string(entry['text'])}"]
    lines += ["", "authors:"]
    for person in data["authors"]:
        first, *rest = person.items()
        lines.append(f"  - {first[0]}: {_scalar(first[1])}")
        lines += [f"    {key}: {_scalar(value)}" for key, value in rest]
    if "roles" in data:
        lines += ["", "roles:"]
        for role, holder in data["roles"].items():
            if isinstance(holder, dict):
                lines.append(f"  {role}:")
                lines += [f"    {key}: {_scalar(value)}" for key, value in holder.items()]
            else:
                lines.append(f"  {role}: {_scalar(holder)}")
    ai_use = AUTHORS[AUTHORS.index("# The AI use") :]
    return "\n".join(lines) + "\n\n" + ai_use


def checked_authors(data: dict) -> str:
    from jsonschema import Draft202012Validator

    from manuscript_guard.contracts._schema import load_schema

    text = authors_text(data)
    if yaml.safe_load(text) != data:
        raise AuthorsRefused("authors.yaml, written, would not read back as the authors given")
    wrong = next(iter(Draft202012Validator(load_schema("authors")).iter_errors(data)), None)
    if wrong is not None:
        raise AuthorsRefused(f"authors.yaml would not be taken: {wrong.message}")
    return text
