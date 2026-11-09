# Cota landing page redesign

**Goal:** Help a first-time visitor understand Cota's Bot development/deployment positioning, see a concrete use case, and reach a real starting path.

**Reference:** cotal.ai's problem → working example → getting started → questions narrative, generous light background, strong typography and restrained illustration. Create original Cota copy and illustrations; do not copy its coordination positioning, mascots, partner logos, metrics or cloud claims.

**Implementation:** Keep the existing single static `docs/landing.html`, copied by the existing mdBook deployment. No runtime, dependencies, external font/image requests or new build pipeline. Use semantic HTML, responsive CSS, small progressive-enhancement JavaScript and native FAQ disclosure.

- [x] Lead with the complete Bot as the deliverable; move implementation concepts below the hero.
- [x] Add an original Bot illustration and labeled illustrative scenarios; show capabilities without pretending to run a live model.
- [x] Explain defining behavior, verifying real runs and delivering services/folders with concise visual examples.
- [x] Include personal/business/group scenarios, pluggable channels, accurate install/configure/start commands and a short FAQ.
- [x] Implement working scenario switching, keyboard controls, mobile navigation, command copy feedback and reduced-motion behavior.
- [x] Validate internal/doc links and Policy YAML against the real repository; check inline JavaScript syntax.
- [x] Inspect desktop, tablet and mobile layouts in the browser; exercise navigation, scenarios, FAQ and copy controls; save review screenshots.


## Verification

- Validated all 45 unique HTML IDs and 60 anchor/document links against mdBook sources.
- Parsed the Policy example with PolicyCatalog and confirmed weather contains 30 evaluation cases.
- Checked inline JavaScript syntax and the four CLI examples against the actual parser.
- Browser checks: desktop (1280/1440), tablet (768), phones (390/320); no horizontal overflow. Scenarios, arrow/Home/End navigation, mobile menu/Escape, native FAQ disclosure and clipboard success work.
- Initialization copy contains no interactive Shell/evaluation/service commands; each command step is selected separately.
- Browser console had no warnings/errors. Saved desktop and mobile review screenshots outside the repository.
