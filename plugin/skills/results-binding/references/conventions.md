# A convention or a term of your own

Part of the results-binding skill, read when a number `check` reports is not a result but a
convention of the paper's field the shipped ones do not cover, a name that contains digits,
or a `p < 0.05` in the Methods that is still reported.

For a convention of your own field, add one to `paper.yaml` with a reason, pinned to the
value rather than to a shape:

```yaml
conventions:
  - id: maf-threshold
    pattern: '(?i)minor allele frequency (?:below|<) 1%'
    why: Standard genotype quality-control threshold, stated in the Methods.
    added_on: 2026-09-24
```

`id` is optional. The report and `explain` cite the rule by it, as `project:maf-threshold`,
and without it by the start of the pattern.

Every run reports how many numbers the project's own rules accounted for. A pattern wide
enough to cover results is allowed, and it is visible, and it switches the check off.

## A name with digits

A name that contains digits, such as a gene or a product code, goes under `terms:`. A name
typed with a subscript or a superscript is declared without the signs: `terms: [CO2]` covers
`CO~2~` as well as `CO2`, and `HbA~1c~` needs nothing, since `HbA1c` is built in. An isotope
is declared by its mass and its element, `terms: [18F]` for `^18^F-FDG`. An exponent on a
unit, `kg/m^2^` or `s^-1^`, is read as `m²` is and needs nothing either; `10^6^` is a
number. A tilde that nothing closes is no subscript: `pH~2` is a number after "about", and
is bound or written out.

## `p < 0.05` in the Methods, still reported

If `p < 0.05` is reported although it is in the Methods, look above it for a line that
starts with `#`, or sits over a line of `-` or `=`, inside a paragraph, a list item or a
quotation. Pandoc prints that line as text, not as a heading, and the gate ends the Methods
there. Do not add a convention. If the line is text ("# of reports" moved to the start of a
line by a hard wrap), rewrap it or write `\#`. If it was meant as a heading, put a blank line
before it. If the `-` line under it was meant as a rule, put the blank line before the rule.
