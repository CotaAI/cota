# README narrative and animation

**Goal:** Explain Cota's complete Bot delivery model quickly with an original instructional animation and a short path to running the weather Bot. Publish to main after verification.

**Reference:** Cotal's visual-first introduction, early quick start, concrete mechanisms and task-oriented documentation. Preserve Cota's own positioning and copy; do not reuse reference artwork, claims, screenshots or product vocabulary.

- [x] Rewrite README around the business problem, runnable start, define/run/verify/deliver workflow, deployment choices and concise FAQ.
- [x] Render an original looping GIF plus a readable static PNG under docs/assets/readme. Show illustrative facts and a human-led improvement loop; no invented execution metrics or live-product recording claims.
- [x] Keep the animation compact and make the assets reproducible with an optional Pillow authoring script, without adding runtime dependencies or bundling fonts.
- [x] Validate links, images, frame count/durations/file size, YAML examples and CLI commands against the repository. Inspect the artwork and README layout.
- [x] Check source syntax/lint and prepare the validated files for main.

**Publication:** Commit and push main, then verify the remote commit and raw animation assets.

## Verification

- GIF: 1040 × 610, 29 decoded frames, 17.4-second loop, 213,700 bytes; static PNG provides the same overview.
- Reduced-motion picture source and explicit static link provide alternatives to the GIF.
- Rebuilding both assets produced byte-identical results in the authoring environment.
- Checked 35 README links, 3 YAML examples, CLI commands and the 30-case weather evaluation set.
- Browser preview loaded the actual animated GIF. Independent review found no factual, command, format, media or runtime-dependency issues.
- Source syntax and Ruff checks pass; no Bot runtime/config changes or font files are included.
