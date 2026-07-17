## Why

TripClipper's rough-cut pipeline needs a stable center contract before exporter, installer, planner, or CLI work can proceed. The current demo rough cut sample is a legacy evaluator input, so tests need committed fixtures plus a formal `RoughCutPlan` schema and validator that future stages can consume safely.

## What Changes

- Add a fixture package for rough-cut and Jianying regression work:
  - a minimal `cut_index.json`
  - a formal minimal `rough_cut_plan.json`
  - the user-provided legacy rough cut source sample
  - the user-provided realistic Jianying `draft_content.json`
  - a minimal template draft shell for later installer tests
- Add `tripclipper.roughcut` models, JSON IO helpers, and validation for `RoughCutPlan` schema version `0.1`.
- Add tests for fixture contracts, model round-trips, and validator behavior.
- Explicitly do not implement Jianying installer, Jianying exporter, rough-cut planner, CLI commands, LLM planner, or VectCutAPI adapter in this change.

## Capabilities

### New Capabilities

- `rough-cut-plan-contract`: Fixture and schema contract for rough-cut plans, including read/write helpers and validation against `cut_index.json`.

### Modified Capabilities

- None.

## Impact

- New test fixtures under `tests/fixtures/roughcut/`, `tests/fixtures/jianying/`, and `tests/fixtures/media/`.
- New rough-cut package under `src/tripclipper/roughcut/`.
- New tests:
  - `tests/test_roughcut_fixture_contract.py`
  - `tests/test_roughcut_models.py`
  - `tests/test_roughcut_validator.py`
- Existing `tripclipper.models.EditCandidateStatus` is reused rather than re-declared.
