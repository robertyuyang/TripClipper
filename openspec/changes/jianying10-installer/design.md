## Context

R0 added portable Jianying fixtures, including `realistic_draft_content.json` and a minimal Jianying 10 template shell. R2 isolates installation from generation: this installer consumes an already generated `draft_content.json` and writes exactly one new draft directory under a supplied Jianying drafts directory. It must be conservative because it may later target a real Jianying drafts directory.

## Goals / Non-Goals

**Goals:**

- Validate all required inputs before creating a draft directory.
- Copy the template draft shell rather than generating Jianying structural files from scratch.
- Create a short unique draft directory named `tc-<draft_name_slug>`, adding a numeric suffix only on collision.
- Preserve the template `timeline_id` so Jianying 10 private shell metadata remains consistent.
- With the bundled template, preserve the template `draft_content.json` skeleton and fill its media slots from the input draft content.
- Copy referenced media into draft-local `assets/` and rewrite explicit Jianying media references.
- Write root/timeline `draft_content.json` files with identical rewritten draft content while preserving Jianying template `.tmp` shell metadata.
- Update root/timeline metadata files so the new draft points at the template timeline, including parseable `.bak` metadata paired with structured JSON files.
- Write an install report beside the input `draft_content.json`.
- Remove the newly created draft directory on post-creation failure while still leaving a failure report.

**Non-Goals:**

- Do not create or export `draft_content.json`.
- Do not read or validate `rough_cut_plan.json`.
- Do not call `pyJianYingDraft`.
- Do not open or automate Jianying.
- Do not implement hardlink mode.
- Do not add CLI commands.

## Public API

- `DraftInstallRequest`
  - `draft_content_path`: existing JSON draft content to install.
  - `draft_name`: user-facing name used for slugging the new draft directory.
  - `template_draft_dir`: optional existing Jianying 10 draft directory used as the structural template shell. When omitted, use the bundled template at `src/tripclipper/jianying/templates/jianying10_template/`.
  - `jianying_drafts_dir`: optional destination directory where Jianying stores draft project directories. When omitted, discover the local default Jianying drafts directory.
  - Optional media resolution inputs may be added only if tests need them for portable fixture paths.
- `InstallValidationItem`
  - Records one preflight or install validation check with a stable name, status, message, and optional path.
- `DraftInstallResult`
  - Returns the created draft directory, preserved template timeline id, install report path, copied media paths, and validation items.
- `DraftInstallError`
  - Raised for preflight or install failures. Failures after directory creation must trigger cleanup and report writing.
- `Jianying10Installer.install(request: DraftInstallRequest) -> DraftInstallResult`

## Installation Flow

1. Resolve request paths. If `template_draft_dir` is omitted, use the bundled Jianying 10 template shell. If `jianying_drafts_dir` is omitted, discover the local Jianying drafts directory.
2. Load `draft_content.json` as JSON.
3. Validate template shell existence, including root metadata files and at least one template timeline directory.
4. Inspect only `materials.videos[]`, `materials.audios[]`, and `materials.images[]` for media references.
5. Validate referenced local media are readable before creating the draft directory.
6. Create a unique draft directory under `jianying_drafts_dir` and copy the full template shell into it.
7. Read `timeline_id` from the copied template timeline directory and keep that directory name unchanged.
8. If the selected template contains TripClipper media placeholders, keep the template `draft_content.json` skeleton and fill its video/audio/image slots from the input draft content. Source video slots are ordered from the input timeline's `tracks[].segments[].material_id` sequence so inputs such as the demo 2/3 swap produce visibly different installed drafts even when `materials.videos[]` order is unchanged.
9. Otherwise, use the compatibility path: copy media into `<new_draft>/assets/` using collision-safe filenames and rewrite the explicit media fields in the input draft JSON to the copied local asset paths.
10. Write root/timeline `draft_content.json` and `.bak` files with consistent rewritten JSON, while preserving copied template `.tmp` shell files.
11. Update `project.json`, `project.json.bak`, `timeline_layout.json`, and `draft_meta_info.json` to reference the new timeline and draft name where applicable when those files are parseable JSON.
12. Write a success `install_report.json` next to the input draft content.

Some Jianying metadata files use `.json` suffix but are not parseable JSON, including real-world `draft_meta_info.json` and `draft_info.json` examples. The installer must only parse known JSON files with structured handling, and must preserve opaque template metadata files unless a safe, tested rewrite path exists. Manual Jianying 10.2 verification showed that generating a fresh timeline id breaks those opaque metadata relationships, while preserving the template timeline id opens successfully.

## Media Rewriting

For placeholder-based templates, the installer rewrites the template's explicit Jianying media containers after mapping source media from the input draft. For non-placeholder templates, it rewrites the input draft's explicit Jianying media containers:

- `materials.videos[].path`
- `materials.audios[].path`
- `materials.images[].path`

When an object in those arrays also has `remote_url`, it must be handled consistently with the local copied media path for that object. The installer must not recursively rewrite arbitrary `*_path` fields elsewhere in the JSON.

`materials.videos[]` may contain image overlays represented with `type="photo"`; those entries are still rewritten through the videos array rule.

The bundled Jianying 10.2 template uses placeholder asset paths under `__TRIPCLIPPER_JIANYING10_TEMPLATE__/assets/`. Installation replaces those placeholders with paths under the new draft directory, copies each source media file into the matching template asset slot, and preserves the template material IDs, track layout, and opaque metadata relationships.

## Path Discovery

The installer may discover `jianying_drafts_dir` when the request omits it. Discovery should check known local Jianying/CapCut draft locations and accept a destination only when it finds one clear valid directory. If discovery finds no valid directory or multiple ambiguous directories, installation must fail with a clear `DraftInstallError` and ask the caller to pass `jianying_drafts_dir`.

Callers may still pass `jianying_drafts_dir` explicitly for tests, temporary draft library copies, non-standard user settings, or manual acceptance.

## Template Setup Responsibility

R2 ships with a bundled Jianying 10 template shell extracted from a real local Jianying 10.2 draft. The bundled template excludes media, backup, cache, and machine-local absolute paths. It is the default `template_draft_dir`.

Callers may override `template_draft_dir` when a user's Jianying version requires a different shell. R2 does not open Jianying or create a new Jianying project; it only consumes the bundled template or a caller-provided template directory.

## Failure Handling

Preflight failures must stop before creating a destination draft directory. If a failure occurs after the destination directory is created, the installer must remove that incomplete directory and write a failure report beside the input `draft_content.json`. The report should include enough check/result data for tests and users to understand the failed stage.

## Risks / Trade-offs

- The first implementation supports copy-only media installation. This is slower than hardlinks but avoids filesystem compatibility surprises and keeps rollback simple.
- The installer intentionally avoids broad recursive path rewriting. That may leave unknown Jianying fields untouched, but it reduces the risk of corrupting unrelated metadata.
- Metadata update details may need fixture-driven refinement because Jianying versions can differ. The tests should pin the minimal fields required by the committed template shell.
