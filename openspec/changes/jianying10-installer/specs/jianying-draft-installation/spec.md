## ADDED Requirements

### Requirement: Jianying 10 draft installation API

The system SHALL expose a focused Jianying installer API for installing an existing `draft_content.json` into a new Jianying 10 draft directory.

#### Scenario: Public installer symbols are exported

- **GIVEN** the `tripclipper.jianying` package
- **WHEN** consumers import the installer API
- **THEN** `DraftInstallRequest`, `InstallValidationItem`, `DraftInstallResult`, `DraftInstallError`, and `Jianying10Installer` SHALL be available.

#### Scenario: Existing draft content is the only draft input

- **GIVEN** a `DraftInstallRequest`
- **WHEN** `Jianying10Installer.install(request)` runs
- **THEN** the installer SHALL consume `request.draft_content_path`
- **AND** it SHALL NOT generate `draft_content.json` from `rough_cut_plan.json`
- **AND** it SHALL NOT call exporter, planner, `pyJianYingDraft`, VectCutAPI, CLI, or Jianying UI code.

### Requirement: Preflight validation

The installer SHALL validate required inputs before creating a destination draft directory.

#### Scenario: Missing required paths are rejected

- **GIVEN** a request with a missing `draft_content_path`, missing `template_draft_dir`, or missing `jianying_drafts_dir`
- **WHEN** installation is attempted
- **THEN** installation SHALL fail with `DraftInstallError`
- **AND** no new draft directory SHALL be created.

#### Scenario: Unreadable media is rejected before install

- **GIVEN** an input `draft_content.json` that references a local media path in `materials.videos[]`, `materials.audios[]`, or `materials.images[]`
- **WHEN** the referenced media cannot be read
- **THEN** installation SHALL fail with `DraftInstallError`
- **AND** no new draft directory SHALL be created.

#### Scenario: Template shell is required

- **GIVEN** a request without `template_draft_dir`
- **WHEN** installation proceeds
- **THEN** the installer SHALL use the bundled Jianying 10 template shell.

#### Scenario: Template shell may be overridden

- **GIVEN** a request with a valid explicit `template_draft_dir`
- **WHEN** installation proceeds
- **THEN** the installer SHALL copy the explicit template shell
- **AND** it SHALL NOT create the Jianying shell files from scratch.

#### Scenario: Template creation is outside installer scope

- **GIVEN** the bundled template is unavailable and no explicit reusable Jianying 10 template draft has been selected
- **WHEN** installation is attempted
- **THEN** the installer SHALL fail validation
- **AND** it SHALL NOT open Jianying, create a new Jianying project, or synthesize a template draft directory.

#### Scenario: Bundled template is sanitized

- **GIVEN** the bundled Jianying 10 template shell
- **WHEN** it is inspected
- **THEN** it SHALL NOT contain media assets, backup directories, cache files, `.DS_Store`, or machine-local absolute paths.

### Requirement: Unique draft directory creation

The installer SHALL create one uniquely named draft directory under the resolved Jianying drafts directory.

#### Scenario: Draft directory name format

- **GIVEN** `draft_name="Summer Trip"`
- **WHEN** installation succeeds
- **THEN** the created draft directory name SHALL be `tc-summer-trip` when that path is available
- **AND** collisions SHALL use a short numeric suffix such as `tc-summer-trip-2`
- **AND** the directory SHALL be created under `request.jianying_drafts_dir`.

#### Scenario: Destination path is explicit

- **GIVEN** `request.jianying_drafts_dir` is provided
- **WHEN** installation is attempted
- **THEN** the installer SHALL create the new draft under that explicit destination.

#### Scenario: Destination path is discovered by default

- **GIVEN** `request.jianying_drafts_dir` is omitted
- **WHEN** exactly one valid local Jianying drafts directory is discoverable
- **THEN** the installer SHALL create the new draft under that discovered directory.

#### Scenario: Ambiguous or missing destination discovery fails safely

- **GIVEN** `request.jianying_drafts_dir` is omitted
- **WHEN** no valid local Jianying drafts directory is discoverable or multiple ambiguous directories are discoverable
- **THEN** installation SHALL fail with `DraftInstallError`
- **AND** no new draft directory SHALL be created.

#### Scenario: Repeated installs are unique

- **GIVEN** the same request is installed twice
- **WHEN** both installs succeed
- **THEN** the two created draft directories SHALL be different
- **AND** both installs SHALL preserve the template timeline id.

### Requirement: Local media copy and explicit path rewriting

The installer SHALL copy referenced media into the new draft's local `assets/` directory and rewrite only known Jianying media fields.

#### Scenario: Media is copied into draft-local assets

- **GIVEN** an input draft with video, audio, and image media references
- **WHEN** installation succeeds
- **THEN** each readable referenced media file SHALL be copied into `<new_draft>/assets/`
- **AND** the installed draft content SHALL reference the copied local files.

#### Scenario: Bundled template media slots are filled from input timeline order

- **GIVEN** installation uses the bundled placeholder-based Jianying 10 template shell
- **AND** two input draft content files have identical `materials.videos[]` order but different main video `tracks[].segments[].material_id` order
- **WHEN** each input is installed
- **THEN** the installed draft content SHALL preserve the bundled template track layout and material IDs
- **AND** the template main video slots SHALL be filled according to each input timeline segment order.

#### Scenario: Explicit media fields are rewritten

- **GIVEN** media entries in `materials.videos[]`, `materials.audios[]`, and `materials.images[]`
- **WHEN** installation succeeds
- **THEN** the installer SHALL rewrite each entry's `path` to its copied draft-local asset path
- **AND** if that entry has `remote_url`, the installer SHALL handle it consistently with the copied local asset path
- **AND** `materials.videos[].type="photo"` entries SHALL be covered by the videos array rewrite rule.

#### Scenario: Arbitrary path fields are not recursively rewritten

- **GIVEN** an input draft containing fields outside the explicit media containers whose names end in `_path`
- **WHEN** installation succeeds
- **THEN** the installer SHALL NOT recursively rewrite those arbitrary `*_path` fields.

### Requirement: Draft content and metadata writes

The installer SHALL write a consistent Jianying draft shell using the template timeline id.

#### Scenario: Draft content files are written consistently

- **GIVEN** installation succeeds with template `timeline_id`
- **WHEN** the new draft directory is inspected
- **THEN** the following files SHALL exist:
  - `draft_content.json`
  - `draft_content.json.bak`
  - `Timelines/<timeline_id>/draft_content.json`
  - `Timelines/<timeline_id>/draft_content.json.bak`
- **AND** each file SHALL contain the same rewritten draft content.

#### Scenario: Template shell tmp files are preserved

- **GIVEN** installation succeeds with template `timeline_id`
- **WHEN** the new draft directory is inspected
- **THEN** the following files SHALL exist:
  - `template.tmp`
  - `template-2.tmp`
  - `Timelines/<timeline_id>/template.tmp`
  - `Timelines/<timeline_id>/template-2.tmp`
- **AND** these files SHALL preserve the copied Jianying template shell metadata shape
- **AND** they SHALL NOT be overwritten with `draft_content.json`.

#### Scenario: Root metadata files are updated

- **GIVEN** installation succeeds
- **WHEN** structured metadata files such as `project.json`, `Timelines/project.json.bak`, and `timeline_layout.json` are loaded
- **THEN** they SHALL reference the template timeline and installed draft metadata required by the template shell.

#### Scenario: Opaque metadata files are preserved safely

- **GIVEN** a template metadata file uses `.json` suffix but is not parseable JSON
- **WHEN** installation succeeds
- **THEN** the installer SHALL NOT parse it with `json.load()`
- **AND** it SHALL preserve or copy it unless a tested structured rewrite path exists.

### Requirement: Install report and cleanup

The installer SHALL leave an install report beside the input draft content and clean up incomplete draft directories.

#### Scenario: Success report is written outside the draft library

- **GIVEN** installation succeeds
- **WHEN** the report path is inspected
- **THEN** `install_report.json` SHALL exist in the same directory as the input `draft_content.json`
- **AND** it SHALL NOT be written inside the new Jianying draft directory.

#### Scenario: Failure after directory creation cleans up the draft

- **GIVEN** installation fails after creating the destination draft directory
- **WHEN** the installer returns the failure
- **THEN** the incomplete draft directory SHALL be removed
- **AND** a failure `install_report.json` SHALL remain beside the input `draft_content.json`.
