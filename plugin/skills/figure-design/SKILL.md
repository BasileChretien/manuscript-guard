---
name: figure-design
description: Choose with the author how a figure looks, a layout suited to its kind (forest plot, disproportionality plot, Kaplan-Meier curve, flow diagram, bar or box plot, scatter, heat map) and a palette, artists' or scientific, that readers with a colour-vision deficiency can still read, within the journal's artwork rules, and apply it to the author's own figure script. Use when starting or restyling a figure, when the author asks for a theme, colours or a palette (MetBrewer, MoMAColors, wesanderson, viridis, Okabe-Ito, Crameri), or when check reports figure-colours-confused, figure-greyscale-confused, figure-colours-scale, figure-colours-many or figure-colours-unread. Not for recording what a rendered figure shows; that is figure-review.
---

# Designing a figure

The figure script is the author's, and so is the choice. Your part is to propose two or
three looks that suit what the figure has to show, say plainly which of them every reader
can read, and put the one the author picks into their script with a line or two. Never draw
the figure for them, and never choose for them.

## What to find out first

Read the figure script and the rendered figure, and ask what is not there:

- **What it shows**: one estimate or many, groups to tell apart, an order (dose, time,
  severity), values above and below a middle (a difference, a log ratio), or a flow of
  counts. This decides the kind of palette: qualitative, sequential, diverging, or none.
- **How many colours** it needs: the number of groups, or "a scale".
- **Who reads it**: a journal page printed in colour or in grey, a slide, a poster.
- **The journal's artwork rules**, in its profile under `figures:` (widths, smallest text,
  thinnest line, formats, whether it prints in grey). `manuscript-guard check` holds the
  file to them.

## Layouts by kind

| Kind | What usually serves it |
|---|---|
| Forest plot | One row per estimate, a point (a square sized by weight in a meta-analysis) and its interval as a line, a log axis for a ratio with the line of no effect at 1, rows in a meaningful order, the estimates and intervals as text bound from the results. One colour, black, unless groups need telling apart. |
| Disproportionality plot (ROR, PRR, IC) | As a forest plot, on a log axis, the signal threshold drawn and labelled from the results, never typed. |
| Kaplan-Meier curve | Steps per arm told apart by colour *and* line style, censoring marks, the number at risk beneath, the y axis from 0 to 1 or its truncation said; a confidence band drawn light, which `check` reads at the colour it shows over white. |
| Flow diagram (CONSORT, PRISMA, STROBE) | Boxes and arrows in black and grey, every count bound from the results so G8 can check the arithmetic; no colour needed. |
| Bar, box or violin plot | Points over the summary where n is small, the error bar said in the legend; colour only for a grouping the axis does not already give. |
| Scatter | A colour for a group (qualitative) or a scale for a variable (sequential), with markers that differ by shape as well where groups matter. |
| Heat map | A sequential map for magnitudes, a diverging one centred on the meaningful middle for differences; viridis, cividis or one of Crameri's, never a rainbow. |

Whatever the kind: do not carry information by colour alone. A label on each line, a marker
shape or a line style keeps it readable in grey and for every reader. Size the text and the
lines to the journal at the width the figure prints:

```python
from manuscript_guard import palettes
import matplotlib.pyplot as plt

plt.rcParams.update(palettes.figure_style(width="single"))   # the journal's own sizes
palettes.use("okabe-ito", 3)                                   # the colour cycle
```

```r
library(manuscriptguard)
p + mg_theme() + scale_colour_mg("okabe-ito")
size <- mg_figure_size("single")
ggplot2::ggsave("figures/km.pdf", p, width = size[["width"]], height = size[["height"]])
```

## Palettes

```bash
manuscript-guard palettes --kind qualitative --colours 4 --safe   # four colours every reader tells apart
manuscript-guard palettes --kind sequential --safe
manuscript-guard palettes --collection MetBrewer                  # the artists' palettes, with what the check says
manuscript-guard palettes --show met/Hiroshige --colours 5        # its colours, and how to use it
```

Every palette there is held to the rule `check` holds a figure to: for a set of colours, how
many of them stay at least 10 apart (CIEDE2000) for a reader with protanopia, deuteranopia
or tritanopia (`cvd`) and in grey; for a map, whether its lightness runs one way, or turns
once for a diverging one, and still does for each deficiency. Beside it is what the
collection itself claims, where it claims anything: MetBrewer, MoMAColors and
NatParksPalettes mark some palettes colour-blind friendly by their own reading, which is
looser than this check, so the two can disagree. Say both.

Propose two or three, for the number of colours the figure needs:

1. one that every reader can read, Okabe and Ito's for a few groups, viridis, cividis or
   one of Crameri's for a scale, a ColorBrewer scheme the check passes;
2. one from the artists' collections the author may like better, where one passes the check
   at that number of colours;
3. where the author asks for an artist's palette the check does not pass, offer it only with
   that said: which pairs a deficiency or grey makes one, and that a marker or a line style
   beside the colour would keep it readable.

Let the author choose. Then change their script with the helper, re-render the figure, and
run `manuscript-guard check`: the colour check reads the rendered SVG or PDF, which is what
counts, not the palette's name.

## When check reports a colour finding

- `figure-colours-confused`: two colours a deficiency makes one. Take a palette that passes
  at that number, or tell the series apart by more than colour; where they already are, say
  so in the figure's guard file under `allow_colours`, the pair and why.
- `figure-greyscale-confused`: two colours of one grey. Matters where the journal prints in
  grey; otherwise a note. A difference in lightness, or a marker, fixes it.
- `figure-colours-scale` or `figure-colours-many`: the figure draws a continuous scale, or
  paints too many colours to compare, and its colours were not compared: which are the
  scale's and which a series' cannot be told from the colours. Draw the scale with a map made
  for every reader (viridis, cividis, Crameri's), and the series beside it in colours that
  stay apart; look at both under the figure review. Drawn as a figure of its own, a panel of
  series has its colours compared.
- `figure-colours-unread`: the figure is only a raster. Save an SVG or a PDF beside it from
  the same script, and its colours are read from that.

The palettes are their makers': each collection's licence and notice are in the package's
`data/palettes_LICENSES.txt` and the repository's ATTRIBUTION.md. Cite the palette where the
journal asks for software and data sources.
