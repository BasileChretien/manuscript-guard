# The landing page's video

`index.html` is a [HyperFrames](https://github.com/heygen-com/hyperframes) composition (Apache-2.0)
that renders the short video on the landing page, `web/landing/media/vord.mp4`. It runs 58
seconds at 1280 by 720 and 30 frames a second, with captions and no sound, and is made to loop.

## What it shows

1. Vord beside a manuscript page whose numbers are bound values.
2. An editor and a terminal. `4,000` is typed over `{{results.cohort.n_reports}}`,
   `manuscript-guard check` fails on it with G2 and names the file, line and column, the binding
   goes back, and `check` passes. The terminal text is `CARD` and `CLEAN` from
   `tools/readme_figures.py`, which `tests/test_docs.py` holds to what `check` prints.
3. The six villains, in `CAST` order from `tools/brand_assets.py`, each stopped at Vord's shield,
   which shows the gate that catches its mistake. The captions name each mistake in the words of
   `brand/README.md`. G12 only warns, and its caption says so.
4. The two shadows pass through the shield, and the co-author reads the page.
5. The end card: the emblem, the name, the tagline and the site's address.

The captions are the `cap-NN` elements of `index.html`. `make-vtt.mjs` writes
`web/landing/media/vord.en.vtt` from them, so the burned-in captions and the WebVTT file have the
same words and the same timings. Change a caption in `index.html` and run `npm run vtt`.

## Rendering it again

It needs Node 22 or later, FFmpeg on `PATH` and a Chrome that HyperFrames can find.

```bash
cd media/video
npm ci
npm run check    # lint, runtime errors, layout, contrast
npm run build    # render, encode, poster, captions
```

`build` runs four steps, which can be run one at a time:

- `render` writes `renders/vord-raw.mp4` (`hyperframes render --quality high --fps 30`).
- `encode` writes `web/landing/media/vord.mp4` from it with FFmpeg: H.264, yuv420p, no audio
  track, `+faststart`.
- `poster` writes `web/landing/media/vord-poster.png`, the frame at 24 seconds.
- `vtt` writes `web/landing/media/vord.en.vtt`.

The HyperFrames CLI sends usage telemetry unless `HYPERFRAMES_NO_TELEMETRY=1` or `DO_NOT_TRACK=1`
is set, and on most commands it checks the npm registry for a newer version unless
`HYPERFRAMES_NO_UPDATE_CHECK=1` is set. The scripts run it through `cli.mjs`, which sets all
three. Run `node cli.mjs <command>` rather than `npx hyperframes` for anything else. The render
fetches nothing: GSAP comes from `node_modules`, the fonts and drawings from
this folder.

The words inside the drawings (4,000 on the Stray Number; `"n": 3986`, `"p": 0.04` and 4000 on
the Forger's file; RETRACTED; doi:10.; PLAN; Methods and the "z z" of Stale Methods; train and test on
the data-leakage shadow) are drawn in the fonts of the machine that
renders, as on the page, since a drawing shown as an image cannot use the
composition's fonts. A render on another machine can differ in those words' typeface.

## What is in the folder

- `assets/`: the dark-page drawings, copied unchanged from `docs/img/brand/` (CC BY 4.0, see
  `brand/README.md`). Copy them again after `python tools/brand_assets.py` changes them.
- `fonts/`: Atkinson Hyperlegible and JetBrains Mono, Latin, regular and bold, as WOFF2 files from
  the npm packages `@fontsource/atkinson-hyperlegible@5.3.0` and `@fontsource/jetbrains-mono@5.3.0`.
  Both are under the SIL Open Font License 1.1, whose text is beside them.
- `package.json` pins `hyperframes` at 0.8.190 and `gsap` at 3.14.2 (GSAP's own no-charge
  licence). `node_modules/`, `renders/` and `.hyperframes/` are not committed.

The code here (the composition, `make-vtt.mjs`, `cli.mjs`) is under the MIT licence, which is
what `package.json` says. The drawings in `assets/` and the video made from them are under
CC BY 4.0 (`brand/LICENSE`), and the fonts under the SIL Open Font License.
