"""Figure 1 — the reporting odds ratio and its interval.

Every value drawn here is read from the results file. The only numbers written into this
script are layout, which is what the source check is built to tell apart.

`svg.fonttype = "none"` matters: matplotlib otherwise converts text to paths, and a figure
with no text layer is a figure the gate cannot read.
"""

from __future__ import annotations

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
RESULTS = ROOT / "results" / "01_disproportionality.json"
OUT = Path(__file__).with_suffix(".svg")

plt.rcParams["svg.fonttype"] = "none"
# A fixed salt makes matplotlib's generated element ids reproducible. The toolkit
# normalises them anyway, but a byte-identical rebuild is worth having on its own.
plt.rcParams["svg.hashsalt"] = "manuscript-guard-example"


def main() -> None:
    values = json.loads(RESULTS.read_text(encoding="utf-8"))["values"]
    point = values["ror.point"]
    low = values["ror.ci_low"]
    high = values["ror.ci_high"]

    estimate = float(point["value"])
    lower = float(low["value"])
    upper = float(high["value"])

    fig, ax = plt.subplots(figsize=(6.5, 2.2))
    ax.errorbar(
        [estimate],
        [0],
        xerr=[[estimate - lower], [upper - estimate]],
        fmt="o",
        color="black",
        capsize=4,
        markersize=6,
    )
    ax.axvline(1, linestyle="--", color="grey", linewidth=0.8)

    ax.set_xscale("log")
    ax.set_xlim(0.5, 10)
    ax.set_xticks([0.5, 1, 2, 5, 10])
    ax.set_xticklabels(["0.5", "1", "2", "5", "10"])
    ax.set_yticks([0])
    ax.set_yticklabels(["example-drug"])
    ax.set_xlabel("Reporting odds ratio (log scale)")

    # The annotation is built from the results, never typed. "95% CI" is a writing
    # convention and passes the source check as one; the values beside it are bindings.
    label = f"{point['display']} (95% CI {low['display']} to {high['display']})"
    ax.annotate(label, xy=(upper, 0), xytext=(8, 4), textcoords="offset points", fontsize=9)

    # The null line was drawn but never named, which the first review picked up.
    ax.annotate(
        "no association",
        xy=(1, 0),
        xytext=(0, -26),
        textcoords="offset points",
        ha="center",
        fontsize=8,
        color="grey",
    )

    ax.spines[["top", "right", "left"]].set_visible(False)
    fig.tight_layout()
    # No render timestamp: it is not part of the figure, and it would make every rebuild
    # look like a change to anything hashing the file.
    fig.savefig(OUT, format="svg", metadata={"Date": None})
    # A raster alongside the vector: journals ask for one, and it is what a reviewer
    # actually looks at. Both are the same figure, so they share one review record.
    fig.savefig(OUT.with_suffix(".png"), format="png", dpi=300)
    plt.close(fig)
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
