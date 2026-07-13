# Rough-cut stability fixtures design

## Goal

Add two valid `RoughCutPlan` schema `0.1` fixtures that exercise materially different media counts and timeline shapes. They will be stable inputs for testing the later RoughCut-to-Jianying compilation and installation pipeline.

The fixtures are editing-software-independent. They must not contain Jianying IDs, Jianying material structures, or template-specific slot assumptions.

## Fixtures

### Short linear plan

File: `tests/fixtures/roughcut/short_linear_rough_cut_plan.json`

- Three sequential video segments on video track `0`.
- Two distinct existing video assets from `tests/fixtures/media/`, with one reused by two segments.
- Unequal source and timeline durations across the segments, while each individual segment remains normal-speed (`source_range` duration equals `timeline_range` duration).
- A contiguous 11-second main timeline.
- No audio, image, or text tracks.
- No transition or styling requirements.

This fixture verifies that the compiler does not assume the bundled Jianying template's fixed video count or decorative tracks.

### Multitrack plan

File: `tests/fixtures/roughcut/multitrack_rough_cut_plan.json`

- Six sequential video segments on video track `0` spanning 24 seconds.
- Two distinct video assets reused across six segments; every use has a different `segment_id` and `source_range`.
- Two image overlay segments on image track `1`, both using the existing overlay image at different timeline ranges.
- One BGM segment on audio track `0` spanning the full timeline.
- Three text segments on text track `0`, placed at the opening, middle, and ending.
- No requirement for non-cut transitions or complex text styles.

This fixture verifies dynamic material counts, multiple track types, repeated source-asset use, independent segment identity, and nontrivial timeline placement.

## Data contract

- Both files conform exactly to the existing strict `RoughCutPlan` schema version `0.1`.
- Media-bearing segments include `asset_id`, repository-relative `asset_path`, `asset_relative_path`, and `asset_type`, matching the current fixture convention.
- Every timeline item has a unique `segment_id`, valid `timeline_range`, `track_type`, and non-negative `track_index`.
- Video and audio segments include valid `source_range` values within the known fixture media durations.
- Image and text segments omit `source_range` because their visible duration is defined by `timeline_range`.
- Every segment includes concise `reason` and `tags` values for diagnostics; downstream Jianying compilation must not depend on them.
- `unused_assets` and `warnings` remain empty; these fixtures test valid compilation inputs, not planner warning behavior.

## Verification

- Load both files through `read_rough_cut_plan` to prove schema validity.
- Run `validate_rough_cut_plan` and require no validation errors.
- Add fixture-contract assertions for segment counts, track composition, unique `segment_id` values, total timeline duration, and deliberate asset reuse in the multitrack fixture.
- Run the existing rough-cut model, validator, and fixture-contract test suites.

## Non-goals

- Do not generate or install Jianying drafts in this change.
- Do not change the RoughCutPlan schema.
- Do not add new media files.
- Do not test transitions, effects, speed changes, or advanced text styling.
