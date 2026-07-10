## 1. Installer Tests

- [x] 1.1 Add preflight failure tests for missing `draft_content_path`, invalid template override, failed `jianying_drafts_dir` discovery, invalid explicit `jianying_drafts_dir`, and unreadable media.
- [x] 1.2 Add a successful install test using the bundled Jianying 10 template and a pytest temporary explicit `jianying_drafts_dir`.
- [x] 1.3 Add media rewrite tests for `materials.videos[].path`, `materials.audios[].path`, `materials.images[].path`, and optional `remote_url` when present.
- [x] 1.4 Add a `materials.videos[].type="photo"` image-overlay rewrite test.
- [x] 1.5 Add tests that root/timeline draft content files are written consistently and Jianying template `.tmp` shell files are preserved.
- [x] 1.6 Add a test that `project.json`, `project.json.bak`, `timeline_layout.json`, and `draft_meta_info.json` are updated for the template timeline/draft.
- [x] 1.7 Add a rollback test proving an incomplete draft directory is removed after a post-creation failure.
- [x] 1.8 Add a test that `install_report.json` is written beside the input `draft_content.json`, including failure reports.
- [x] 1.9 Add a test that repeated installs preserve the template `timeline_id` and generate short unique `tc-...` draft directory names.
- [x] 1.10 Add tests for default `jianying_drafts_dir` discovery and explicit destination override.
- [x] 1.11 Add tests that the bundled template contains no media assets, backups, cache files, or machine-local absolute paths.
- [x] 1.12 Add tests proving opaque Jianying metadata files with `.json` suffix are preserved without `json.load()` parsing.
- [x] 1.13 Add tests proving the bundled template skeleton is preserved and demo 2/3 swap inputs fill video slots from timeline segment order.

## 2. Public Models and Paths

- [x] 2.1 Create `src/tripclipper/jianying/models.py` with `DraftInstallRequest`, `InstallValidationItem`, `DraftInstallResult`, and `DraftInstallError`.
- [x] 2.2 Create `src/tripclipper/jianying/paths.py` with slug, unique draft directory, bundled template path, template timeline, report path, and local Jianying drafts directory discovery helpers.
- [x] 2.3 Create `src/tripclipper/jianying/__init__.py` and export the R2 public installer API.
- [x] 2.4 Ensure the bundled template directory is included as package data.

## 3. Installer Implementation

- [x] 3.1 Implement request preflight validation and validation item collection.
- [x] 3.2 Load and inspect `draft_content.json` without modifying the source file.
- [x] 3.3 Copy the template draft shell into a unique destination draft directory.
- [x] 3.4 Preserve the template timeline id on each install.
- [x] 3.5 Copy all referenced media into draft-local `assets/` using copy-only behavior.
- [x] 3.6 Rewrite only the explicit media fields covered by the spec.
- [x] 3.7 Write the required root/timeline draft content files and preserve template `.tmp` shell files.
- [x] 3.8 Update structured metadata files and preserve opaque Jianying metadata files unless a tested rewrite path exists.
- [x] 3.9 Write success/failure `install_report.json` next to the input draft content.
- [x] 3.10 Clean up the newly created draft directory on post-creation failure.
- [x] 3.11 For placeholder-based templates, fill template media slots from input timeline order while preserving template material IDs and track layout.

## 4. Verification

- [x] 4.1 Run `pytest tests/test_jianying_installer.py -v`.
- [x] 4.2 Run adjacent fixture/schema regression tests if R0/R1 are present: `pytest tests/test_roughcut_fixture_contract.py tests/test_roughcut_models.py tests/test_roughcut_validator.py -v`.
- [x] 4.3 For manual acceptance, use the bundled template by default; if Jianying rejects it, retry with an explicit template draft created by the local Jianying version.
