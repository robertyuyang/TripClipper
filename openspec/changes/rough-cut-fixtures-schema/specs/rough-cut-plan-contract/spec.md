## ADDED Requirements

### Requirement: Rough-cut fixture package

The system SHALL provide committed rough-cut and Jianying fixtures that do not reference user-local absolute paths.

#### Scenario: Fixture paths are portable

- **GIVEN** the rough-cut fixture package
- **WHEN** each fixture JSON file is loaded
- **THEN** no fixture value SHALL contain `/Users/bytedance/`
- **AND** media references SHALL point to repository fixtures or paths that tests can resolve.

#### Scenario: Minimal plan covers supported timeline item types

- **GIVEN** `tests/fixtures/roughcut/minimal_rough_cut_plan.json`
- **WHEN** it is inspected
- **THEN** its `timeline` SHALL include `track_type` values `video`, `image`, `audio`, and `text`
- **AND** video/audio segments SHALL include `source_range`
- **AND** image/text segments SHALL omit `source_range`.

#### Scenario: Legacy and realistic samples are retained

- **GIVEN** the user-provided demo export samples
- **WHEN** R0 fixtures are created
- **THEN** the legacy rough cut source SHALL be retained as `legacy_eval_rough_cut_source.json`
- **AND** the realistic Jianying draft SHALL be retained as `realistic_draft_content.json`.

### Requirement: RoughCutPlan schema and IO

The system SHALL define a `RoughCutPlan` schema version `0.1` with JSON read/write helpers.

#### Scenario: Valid plan round-trips

- **GIVEN** a valid `RoughCutPlan`
- **WHEN** it is written with `write_rough_cut_plan` and read with `read_rough_cut_plan`
- **THEN** the reloaded plan SHALL preserve the same JSON data.

#### Scenario: Timeline-only expression

- **GIVEN** a `RoughCutPlan`
- **WHEN** it is serialized
- **THEN** top-level fields SHALL NOT include `text_overlays`, `bgm`, or `transitions`
- **AND** text, audio, images, and transitions SHALL be represented on timeline segments.

### Requirement: RoughCutPlan validation

The system SHALL validate `RoughCutPlan` instances against structural rules and a `CutIndex`.

#### Scenario: Asset identity must exist

- **GIVEN** a plan segment with `asset_id`
- **WHEN** `validate_rough_cut_plan(plan, cut_index)` runs
- **THEN** the `asset_id` SHALL exist in `cut_index.assets`
- **AND** the segment `asset_relative_path` SHALL match the cut-index asset when both are present.

#### Scenario: Track overlap is rejected only within the same concrete track

- **GIVEN** timeline segments with `timeline_range`
- **WHEN** two segments overlap on the same `(track_type, track_index)`
- **THEN** validation SHALL fail
- **BUT** overlapping ranges on different tracks SHALL be allowed.

#### Scenario: Excluded snapshot requires explicit override reason

- **GIVEN** a media segment with `candidate_status_snapshot="excluded"`
- **WHEN** it lacks `selection_override_reason`
- **THEN** validation SHALL fail.

#### Scenario: Source range rules follow segment type

- **GIVEN** timeline segments
- **WHEN** validation runs
- **THEN** video and audio segments SHALL require `source_range`
- **AND** image and text segments SHALL reject `source_range`.

#### Scenario: Text overlay rules follow segment type

- **GIVEN** timeline segments
- **WHEN** validation runs
- **THEN** text segments SHALL require `text_overlay`
- **AND** non-text segments SHALL reject `text_overlay`.
