## Context

The source design documents define `rough_cut_plan.json` as the center contract between media selection and Jianying export/install stages. Existing `projects/demo-scan/exports/rough_cut_plan.json` is a legacy evaluator input with `clips` and `test_assets`, not the formal R1 schema. Existing `projects/demo-scan/exports/draft_content.json` is a realistic Jianying output sample for future semantic exporter regression tests.

## Goals / Non-Goals

**Goals:**

- Commit fixture data that later R2/R3 work can consume without depending on user-local project paths.
- Define Pydantic v2 models for `RoughCutPlan` schema version `0.1`.
- Provide read/write helpers for stable JSON round-trips.
- Validate plan/cut-index consistency, timeline ranges, track overlap, asset identity, and text/media field rules.

**Non-Goals:**

- Do not create Jianying installer models or installation behavior.
- Do not export `draft_content.json` from a plan.
- Do not generate plans from `cut_index.json`.
- Do not add CLI commands.
- Do not implement LLM planning or VectCutAPI support.

## Decisions

- Keep `RoughCutPlan` in `src/tripclipper/roughcut/` so `src/tripclipper/models.py` remains the `cut_index.json` source of truth.
- Reuse `EditCandidateStatus` from `tripclipper.models` for `candidate_status_snapshot`; it is a review/validation snapshot, not an exporter selection input.
- Represent all timeline content as `timeline` segments. Text, BGM audio, image overlays, and transitions are not top-level fields.
- Use `(track_type, track_index)` as the overlap boundary. Segments may overlap across tracks; within the same concrete track they may not overlap.
- Treat `asset_id + asset_relative_path` as the primary media identity. `asset_path` is retained as a generation-time path snapshot and fallback.
- Store the user-provided realistic draft as a fixture with path strings rewritten away from `/Users/bytedance/...`; preserve Jianying's shape where image overlays can appear as `materials.videos[].type="photo"`.

## Risks / Trade-offs

- Fixture media can be dummy bytes rather than playable media. This is sufficient for R0/R1 path and JSON contract tests, but future exporter/installer tests may need richer media if a dependency inspects codecs.
- Pydantic model validation can catch structural errors, but cross-file asset existence and overlap checks belong in `validator.py` to keep model construction ergonomic for tests.
- The legacy sample is intentionally not converted by a reusable tool. That keeps R0 scoped, but a future migration utility would be separate work.
