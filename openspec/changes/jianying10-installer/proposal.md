## Why

TripClipper needs a safe bridge from an existing Jianying `draft_content.json` into a user's Jianying 10 drafts directory. Exporter and planner work should not write into the real Jianying drafts directory directly, so this change adds a focused installer that validates inputs, copies media into a new draft-local `assets/` directory, rewrites only known media references, and rolls back incomplete installs.

## What Changes

- Add `tripclipper.jianying` installer models, path helpers, and `Jianying10Installer`.
- Install an existing `draft_content.json` into a newly created Jianying 10 draft directory by copying a bundled Jianying 10 template shell, with optional caller override.
- Discover the local Jianying drafts directory by default, while still allowing callers to pass an explicit destination.
- With the bundled template, preserve the renderable template draft skeleton and fill its media slots from the input draft timeline order; for non-placeholder templates, copy referenced media and rewrite explicit Jianying media fields.
- Write the required root and timeline `draft_content`/template files, refresh project metadata files, and produce an install report next to the input draft content.
- Add tests for preflight failures, successful install, media rewriting, timeline uniqueness, key file writes, metadata updates, rollback, and report placement.
- Explicitly do not generate `draft_content.json`, parse `rough_cut_plan.json`, call `pyJianYingDraft`, operate Jianying UI, implement hardlinks, add CLI commands, or implement exporter/planner behavior.

## Capabilities

### New Capabilities

- `jianying-draft-installation`: Safe, repeatable installation of an existing Jianying `draft_content.json` into a new Jianying 10 draft directory.

### Modified Capabilities

- None.

## Impact

- New package files under `src/tripclipper/jianying/`.
- New bundled Jianying 10 template shell under `src/tripclipper/jianying/templates/jianying10_template/`.
- New tests in `tests/test_jianying_installer.py`.
- Depends on the R0 fixture package, especially `tests/fixtures/jianying/realistic_draft_content.json`.
- Does not modify `tripclipper.roughcut`, exporter code, planner code, or CLI commands.
