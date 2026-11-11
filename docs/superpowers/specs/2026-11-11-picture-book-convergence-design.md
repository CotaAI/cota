# Picture-book production convergence

Approved by the user: each page/cover receives one initial generation and at most two revisions; same image and fixed criteria reuse observations; an unresolved target stops regenerating while independent work continues and unresolved items remain explicit. This belongs to the portable example Bot, not Cota DST or Pi Core.

Evidence: the audited run generated page-04 ten times. Existing Skill prose already says two rounds but models.generate has no target identity/counter. Review caching only checks the requested output filename; changing that name repeats paid judging. Two assistant observations contradicted each other for identical provider image bytes.

## Contract

- Generate and review require a stable `--asset` identifier (e.g. `page-04`, `cover`, `pdf-face-05`); revision filenames do not create new identities. Task/user scope remains the project directory. No new framework configuration or Event.
- Generation journals remain the evidence and budget source. Each new paid generation writes its asset and request status before HTTP. Three attempts per asset include unknown outcomes; an unknown same-asset request prevents another request even under a new filename. Valid completed identical inputs reuse original bytes, including when a different output name is requested, without spending another attempt. Completed images and original reports are never silently overwritten.
- Fixed review criteria are bound to each asset when first reviewed. A changed filename with identical criteria is valid; changing criteria does not silently start a new cycle. Genuinely changed user requirements require a deliberately separate production task, not automatic budget resets.
- Review cache identity includes the stable target, fixed criteria, model/protocol and ordered image hashes. Requested output names and byte-identical image aliases do not produce a new paid review. Original input labels/hashes remain intact; reuse under different labels is explicitly identified. A missing/tampered cached report fails closed. Reports remain observations, never automatic book QA approval.
- A small per-project file lock protects reserve/check/write across CLI processes. It is released by the OS after process exit; another in-flight command returns a clear busy result, never a second simultaneous paid request.
- Blocked commands return a nonzero exit plus compact JSON with reason, asset, retryable=false and next action. Status exposes per-asset attempts, remaining generations, last saved output and review evidence. Unclassified older journals are reported honestly; no filename-based guessing or retrospective rewriting of old evidence.
- Bot prompt, Skill runtime instructions and Policy examples direct the model to preserve accepted content, treat conflicting observations as uncertainty, stop cosmetic loops, continue independent pages, and report unresolved targets or an explicitly unapproved draft. Official validation and final QA standards remain unchanged.

## Validation

Use HTTPX fake services only: attempted fourth call must never reach HTTP; new output names/processes must not reset budget; same criteria/pixels under renamed paths must not obtain contradictory fresh judgments; changed bytes must obtain a new review; changed criteria, corrupt cache and unknown outcomes must block safely. Real CLI and Pi tests verify errors can be observed, other assets remain usable, draft output remains honest, and source Skill/endpoint credentials are untouched. Synchronize code/guidance to the existing private Bot without replacing endpoints, assets or databases.
