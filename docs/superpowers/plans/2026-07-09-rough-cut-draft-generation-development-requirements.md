# Rough Cut Draft Generation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Break rough-cut and Jianying draft generation into independently executable development requirements that can each be completed in a separate Codex conversation.

**Architecture:** The center contract is `rough_cut_plan.json`. Development proceeds from reusable fixtures and schema, to Jianying installation, to draft export, to planning, then CLI orchestration. Each requirement produces a testable artifact and should be committed before starting the next requirement.

**Tech Stack:** Python 3.10+, Pydantic v2, Click, pytest, standard-library `json`/`pathlib`/`shutil`, optional `pyJianYingDraft` adapter, no required `VectCutAPI` dependency in the first pass.

## Global Constraints

- Source specs: `docs/superpowers/specs/2026-07-09-rough-cut-draft-generation-design.md` and `docs/superpowers/specs/2026-07-09-rough-cut-draft-generation-technical.md`.
- Do not modify, move, or overwrite original media files.
- Do not write into a user’s existing Jianying draft directory except by creating a new uniquely named draft directory.
- Install/create run installation checks by default and stop before creating a draft when checks fail.
- `rough_cut_plan.json` expresses edit intent and timeline plan; it must not contain Jianying-specific file structure.
- `JianyingDraftExporter` must not read `cut_index.json` to do second-pass material selection.
- `Jianying10Installer` must not understand media content or change edit order.
- `pyJianYingDraft` is optional or runtime-detected; it must not become a required core dependency in the first pass.
- `VectCutAPIAdapter` is optional follow-up work and must not block the first working chain.
- Keep changes scoped. Ignore unrelated untracked files such as `docs/review-html-*.md`.

---

## How To Use This Plan

Open one fresh conversation per requirement. Start with the matching “Conversation starter” block. Do not ask that conversation to implement later requirements unless the requirement explicitly says it depends on them.

Recommended order:

```text
R0 fixture pack
R1 RoughCutPlan schema
R2 Jianying10Installer
R3 JianyingDraftExporter + PyJianYingDraftAdapter
R4 Heuristic RoughCutPlanner
R5 CLI orchestration
R6 Optional adapters and LLM planner
```

The running product order is `planner -> exporter -> installer`, but the development order is intentionally different. It validates stable contracts and Jianying write behavior before adding automatic planning.

## Shared File Map

Create these directories as the relevant requirement needs them:

```text
src/tripclipper/roughcut/
  __init__.py
  models.py
  io.py
  validator.py
  planner.py

src/tripclipper/jianying/
  __init__.py
  models.py
  draft_exporter.py
  installer.py
  paths.py
  adapters/
    __init__.py
    base.py
    pyjianyingdraft.py
    vectcutapi.py

tests/fixtures/roughcut/
tests/fixtures/jianying/
```

Existing files likely modified later:

```text
src/tripclipper/cli.py
src/tripclipper/paths.py
pyproject.toml
```

---

### Requirement R0: Fixture Pack And Validation Samples

**Goal:** Create the minimal local fixture set that later requirements can use without depending on real user projects.

**Depends On:** Current specs only.

**Files:**
- Create: `tests/fixtures/roughcut/minimal_rough_cut_plan.json`
- Create: `tests/fixtures/roughcut/minimal_cut_index.json`
- Create: `tests/fixtures/jianying/minimal_draft_content.json`
- Create: `tests/fixtures/jianying/template_draft/`
- Create: `tests/fixtures/media/`
- Test: `tests/test_roughcut_fixture_contract.py`

**Produces:**
- Small media fixture files or documented generated dummy files.
- A minimal `cut_index.json` with at least two video assets and one image asset.
- A minimal `rough_cut_plan.json` that references fixture assets.
- A minimal `draft_content.json` that installer tests can consume.
- A minimal Jianying template draft directory with the files installer expects.

**Acceptance Criteria:**
- `pytest tests/test_roughcut_fixture_contract.py -v` passes.
- Fixture paths are relative to the repository or pytest tmp path where possible.
- No fixture references `/Users/bytedance/...` absolute paths.
- Fixture plan contains seconds-based time ranges.
- Fixture draft content contains media references that installer can rewrite later.

**Out Of Scope:**
- Do not implement schema models.
- Do not implement exporter.
- Do not implement installer.

**Suggested Steps:**

- [ ] Create fixture directories under `tests/fixtures/`.
- [ ] Add tiny media stand-ins that are safe to commit, or generate them in tests using standard-library file writes.
- [ ] Add `minimal_cut_index.json` with `schema_version`, `project`, `assets`, `default_candidates`, and empty arrays for unrelated top-level fields.
- [ ] Add `minimal_rough_cut_plan.json` using the planned schema fields from the technical spec.
- [ ] Add `minimal_draft_content.json` with enough `materials.videos`, `materials.audios`, or `materials.images` entries to test path rewriting.
- [ ] Add a minimal `template_draft/` skeleton with `project.json`, `timeline_layout.json`, `draft_meta_info.json`, and `Timelines/`.
- [ ] Add tests that load each JSON fixture and assert the expected top-level keys exist.
- [ ] Run `pytest tests/test_roughcut_fixture_contract.py -v`.
- [ ] Commit with `test: add rough cut draft fixtures`.

**Conversation Starter:**

```text
按 docs/superpowers/plans/2026-07-09-rough-cut-draft-generation-development-requirements.md 的 Requirement R0 实现 fixture pack。只做 R0，不实现 schema/exporter/installer/planner。完成后运行 R0 验收测试并提交。
```

---

### Requirement R1: RoughCutPlan Schema, IO, And Validator

**Goal:** Define the durable `rough_cut_plan.json` contract and local validation helpers.

**Depends On:** R0 fixture pack.

**Files:**
- Create: `src/tripclipper/roughcut/__init__.py`
- Create: `src/tripclipper/roughcut/models.py`
- Create: `src/tripclipper/roughcut/io.py`
- Create: `src/tripclipper/roughcut/validator.py`
- Test: `tests/test_roughcut_models.py`
- Test: `tests/test_roughcut_validator.py`

**Interfaces:**
- Produces: `ROUGH_CUT_PLAN_SCHEMA_VERSION = "0.1"`.
- Produces: `TimeRange`, `RoughCutProjectRef`, `RoughCutIntent`, `RoughCutSourceSnapshot`, `RoughCutSegment`, `TextOverlay`, `BgmPlan`, `TransitionPlan`, `UnusedAsset`, `PlanWarning`, `RoughCutPlan`.
- Produces: `read_rough_cut_plan(path) -> RoughCutPlan`.
- Produces: `write_rough_cut_plan(path, plan) -> None`.
- Produces: `validate_rough_cut_plan(plan, cut_index) -> None`.
- Produces: `RoughCutValidationError`.

**Acceptance Criteria:**
- `pytest tests/test_roughcut_models.py tests/test_roughcut_validator.py -v` passes.
- Valid fixture plan round-trips without data loss.
- Invalid time ranges fail.
- Missing asset ids fail when validating against `cut_index.json`.
- Main-video timeline overlap fails.
- `source_candidate_status="excluded"` fails unless `selection_override_reason` is present.

**Out Of Scope:**
- Do not generate plans from `cut_index.json`.
- Do not export Jianying draft content.
- Do not install Jianying drafts.

**Suggested Steps:**

- [ ] Add failing model round-trip tests using `tests/fixtures/roughcut/minimal_rough_cut_plan.json`.
- [ ] Add failing validator tests for invalid time range, missing asset id, overlapping main-video segments, and excluded-without-reason.
- [ ] Implement Pydantic models in `src/tripclipper/roughcut/models.py`.
- [ ] Implement JSON read/write helpers in `src/tripclipper/roughcut/io.py`.
- [ ] Implement validation in `src/tripclipper/roughcut/validator.py`.
- [ ] Export public names from `src/tripclipper/roughcut/__init__.py`.
- [ ] Run `pytest tests/test_roughcut_models.py tests/test_roughcut_validator.py -v`.
- [ ] Run existing `pytest tests/test_models.py tests/test_cut_index.py -v` to confirm no regression in core models.
- [ ] Commit with `feat: add rough cut plan schema`.

**Conversation Starter:**

```text
按 docs/superpowers/plans/2026-07-09-rough-cut-draft-generation-development-requirements.md 的 Requirement R1 实现 RoughCutPlan schema/io/validator。只做 R1。依赖 R0 fixture。完成后运行 R1 验收测试并提交。
```

---

### Requirement R2: Jianying10Installer

**Goal:** Install an existing `draft_content.json` into a new Jianying 10 draft directory safely and repeatably.

**Depends On:** R0 fixture pack.

**Files:**
- Create: `src/tripclipper/jianying/__init__.py`
- Create: `src/tripclipper/jianying/models.py`
- Create: `src/tripclipper/jianying/paths.py`
- Create: `src/tripclipper/jianying/installer.py`
- Test: `tests/test_jianying_installer.py`

**Interfaces:**
- Produces: `DraftInstallRequest`.
- Produces: `InstallValidationItem`.
- Produces: `DraftInstallResult`.
- Produces: `DraftInstallError`.
- Produces: `Jianying10Installer.install(request: DraftInstallRequest) -> DraftInstallResult`.

**Acceptance Criteria:**
- `pytest tests/test_jianying_installer.py -v` passes.
- Installer refuses missing `draft_content_path`, missing template dir, missing library dir, unreadable media, and unavailable hardlink mode.
- Installer creates a unique draft directory.
- Installer generates a new `timeline_id`.
- Installer copies or hardlinks media into draft-local `assets/`.
- Installer rewrites at least:
  - `materials.videos[].path`
  - `materials.videos[].remote_url`
  - `materials.audios[].path`
  - `materials.audios[].remote_url`
  - `materials.images[].path`
  - `materials.images[].remote_url`
- Installer writes these seven key files with consistent content:
  - `draft_content.json`
  - `draft_content.json.bak`
  - `template-2.tmp`
  - `Timelines/<timeline_id>/draft_content.json`
  - `Timelines/<timeline_id>/draft_content.json.bak`
  - `Timelines/<timeline_id>/template.tmp`
  - `Timelines/<timeline_id>/template-2.tmp`
- Installer updates `project.json`, `timeline_layout.json`, and `draft_meta_info.json`.
- Installer failure after directory creation cleans up the incomplete draft directory and leaves an install report.

**Out Of Scope:**
- Do not generate `draft_content.json`.
- Do not parse `rough_cut_plan.json`.
- Do not call `pyJianYingDraft`.
- Do not open or automate Jianying UI.

**Manual Verification:**
- Use a real Jianying 10 template directory and a known-good `draft_content.json`.
- Install into a temporary Jianying library copy first.
- Then install into the real Jianying draft library only after fixture tests pass.
- Open Jianying 10 and confirm the new draft appears, opens, keeps media linked, and reopens after save.

**Suggested Steps:**

- [ ] Add failing tests for installation pre-check failures.
- [ ] Add failing test for successful install into a pytest tmp library dir.
- [ ] Add failing test for media path rewriting.
- [ ] Add failing test for seven key file writes.
- [ ] Add failing test that a partial install is cleaned up on write failure.
- [ ] Implement request/result models in `src/tripclipper/jianying/models.py`.
- [ ] Implement path helpers in `src/tripclipper/jianying/paths.py`.
- [ ] Implement installer in `src/tripclipper/jianying/installer.py`.
- [ ] Export public names from `src/tripclipper/jianying/__init__.py`.
- [ ] Run `pytest tests/test_jianying_installer.py -v`.
- [ ] Commit with `feat: add jianying draft installer`.

**Conversation Starter:**

```text
按 docs/superpowers/plans/2026-07-09-rough-cut-draft-generation-development-requirements.md 的 Requirement R2 实现 Jianying10Installer。只做 R2。输入是已有 draft_content.json fixture，不实现 exporter/planner/CLI。完成后运行 R2 验收测试并提交。
```

---

### Requirement R3: JianyingDraftExporter And PyJianYingDraftAdapter

**Goal:** Convert a hand-written `rough_cut_plan.json` into a new `draft_content.json`, then verify that installer can install it.

**Depends On:** R1 RoughCutPlan schema and R2 Jianying10Installer.

**Files:**
- Create: `src/tripclipper/jianying/draft_exporter.py`
- Create: `src/tripclipper/jianying/adapters/__init__.py`
- Create: `src/tripclipper/jianying/adapters/base.py`
- Create: `src/tripclipper/jianying/adapters/pyjianyingdraft.py`
- Modify: `src/tripclipper/jianying/models.py`
- Test: `tests/test_jianying_exporter.py`
- Test: `tests/test_jianying_pyjianyingdraft_adapter.py`

**Interfaces:**
- Consumes: `RoughCutPlan`.
- Produces: `DraftExportResult`.
- Produces: `JianyingDraftExporter.export(plan, output_dir, engine="pyjianyingdraft") -> DraftExportResult`.
- Produces: `JianyingDraftAdapter.export(plan, output_dir) -> DraftExportResult`.
- Produces: `AdapterCapabilities`.
- Produces: `DraftExportError`.

**Acceptance Criteria:**
- `pytest tests/test_jianying_exporter.py tests/test_jianying_pyjianyingdraft_adapter.py -v` passes.
- Exporter writes only inside `output_dir`.
- Exporter never modifies source media or the input plan.
- Adapter receives one `RoughCutPlan` and does not read `cut_index.json`.
- Export result includes `engine`, `draft_content_path`, optional `draft_meta_info_path`, `media_paths`, and `warnings`.
- Unsupported-but-safe features are recorded in `warnings`.
- A generated `draft_content.json` from the fixture plan can be handed to R2 installer tests.

**Out Of Scope:**
- Do not implement heuristic planning.
- Do not implement LLM planning.
- Do not implement `VectCutAPIAdapter`.
- Do not add final CLI orchestration.

**Manual Verification:**

```text
minimal_rough_cut_plan.json
  -> JianyingDraftExporter
  -> generated draft_content.json
  -> Jianying10Installer
  -> Jianying 10 opens new draft
```

The generated draft does not need to byte-match any existing `draft_content.json`. Validate semantic equivalence instead: media count, order, approximate source ranges, timeline order, text overlays, BGM handling, and installability.

**Suggested Steps:**

- [ ] Add failing exporter test using `minimal_rough_cut_plan.json`.
- [ ] Add failing test that exporter does not read `cut_index.json`; use a fake adapter that would fail if asked for a cut index.
- [ ] Add failing adapter capability warning test.
- [ ] Add failing integration-style test: export fixture plan into tmp output dir, then pass generated `draft_content.json` to installer fixture.
- [ ] Implement adapter protocol and capability model.
- [ ] Implement `DraftExportResult` and `DraftExportError`.
- [ ] Implement exporter engine dispatch.
- [ ] Implement minimal `PyJianYingDraftAdapter` with runtime dependency detection and a clear error if unavailable.
- [ ] Run `pytest tests/test_jianying_exporter.py tests/test_jianying_pyjianyingdraft_adapter.py tests/test_jianying_installer.py -v`.
- [ ] Commit with `feat: add jianying draft exporter`.

**Conversation Starter:**

```text
按 docs/superpowers/plans/2026-07-09-rough-cut-draft-generation-development-requirements.md 的 Requirement R3 实现 JianyingDraftExporter + PyJianYingDraftAdapter。只做 R3。依赖 R1/R2。完成后验证“手写 rough_cut_plan.json -> exporter -> installer”链路并提交。
```

---

### Requirement R4: Heuristic RoughCutPlanner

**Goal:** Generate a first-pass `rough_cut_plan.json` from real `cut_index.json` and project intent without using LLM.

**Depends On:** R1 RoughCutPlan schema.

**Files:**
- Create: `src/tripclipper/roughcut/planner.py`
- Modify: `src/tripclipper/roughcut/__init__.py`
- Test: `tests/test_roughcut_planner.py`

**Interfaces:**
- Consumes: `read_cut_index(path) -> CutIndex`.
- Consumes: `RoughCutPlan`, `RoughCutIntent`, `RoughCutSegment`.
- Produces: `RoughCutPlanRequest`.
- Produces: `HeuristicRoughCutPlanner.plan(request: RoughCutPlanRequest) -> RoughCutPlan`.

**Acceptance Criteria:**
- `pytest tests/test_roughcut_planner.py tests/test_roughcut_validator.py -v` passes.
- Planner defaults to `edit_candidate_status=default_selected`.
- Planner excludes `needs_review` and `excluded` by default.
- Planner can include `alternate` only when configured or when default candidates are insufficient.
- Planner uses `clip_suggestions` when present.
- Planner produces segments with `reason`.
- Planner output validates with `validate_rough_cut_plan`.
- Total timeline duration is close to `target_duration_sec` without exceeding it by more than one selected segment duration.

**Out Of Scope:**
- Do not call LLM.
- Do not export `draft_content.json`.
- Do not install Jianying drafts.
- Do not implement final CLI orchestration.

**Suggested Steps:**

- [ ] Add failing tests for default candidate selection.
- [ ] Add failing tests that `needs_review` and `excluded` are skipped by default.
- [ ] Add failing tests for `include_alternates=True`.
- [ ] Add failing tests that `clip_suggestions` become `source_range`.
- [ ] Add failing test that every segment has a non-empty `reason`.
- [ ] Implement `RoughCutPlanRequest`.
- [ ] Implement `HeuristicRoughCutPlanner`.
- [ ] Run `pytest tests/test_roughcut_planner.py tests/test_roughcut_validator.py -v`.
- [ ] Commit with `feat: add heuristic rough cut planner`.

**Conversation Starter:**

```text
按 docs/superpowers/plans/2026-07-09-rough-cut-draft-generation-development-requirements.md 的 Requirement R4 实现启发式 RoughCutPlanner。只做 R4，不做 LLM/exporter/installer/CLI 串联。完成后运行 R4 验收测试并提交。
```

---

### Requirement R5: CLI Commands And End-To-End Orchestration

**Goal:** Expose the rough-cut and Jianying pipeline through clear Click commands, including one-shot `jianying create`.

**Depends On:** R1, R2, R3, and R4.

**Files:**
- Modify: `src/tripclipper/cli.py`
- Modify: `src/tripclipper/paths.py`
- Test: `tests/test_cli_roughcut.py`
- Test: `tests/test_cli_jianying.py`

**Interfaces:**
- Consumes: `HeuristicRoughCutPlanner.plan`.
- Consumes: `write_rough_cut_plan`.
- Consumes: `JianyingDraftExporter.export`.
- Consumes: `Jianying10Installer.install`.
- Produces: `tripclipper roughcut plan <slug> --target-duration 90`.
- Produces: `tripclipper jianying export <slug> --engine pyjianyingdraft`.
- Produces: `tripclipper jianying install --draft-content <path> --name <draft_name>`.
- Produces: `tripclipper jianying create <slug> --target-duration 90 --engine pyjianyingdraft`.

**Acceptance Criteria:**
- `pytest tests/test_cli_roughcut.py tests/test_cli_jianying.py -v` passes.
- `roughcut plan` writes `projects/<slug>/rough_cut_plan.json`.
- `jianying export` writes `projects/<slug>/exports/jianying/<draft_id>/draft_content.json`.
- `jianying install` installs an existing `draft_content.json` and reports the new draft directory.
- `jianying create` runs `plan -> export -> install`.
- Any failed stage stops the chain and leaves earlier successful artifacts.
- CLI errors follow existing style: no raw stack traces, exit code 2 for user input errors, exit code 1 for business failures.

**Out Of Scope:**
- Do not add LLM planner.
- Do not add `VectCutAPIAdapter`.
- Do not add UI.

**Suggested Steps:**

- [ ] Add failing CLI tests for `roughcut plan`.
- [ ] Add failing CLI tests for `jianying export`.
- [ ] Add failing CLI tests for `jianying install`.
- [ ] Add failing CLI tests for `jianying create` stopping after export failure.
- [ ] Add roughcut and jianying Click command groups to `src/tripclipper/cli.py`.
- [ ] Add path helpers for roughcut and jianying export artifacts in `src/tripclipper/paths.py`.
- [ ] Wire command error handling to existing CLI conventions.
- [ ] Run `pytest tests/test_cli_roughcut.py tests/test_cli_jianying.py -v`.
- [ ] Run `pytest tests/test_cli_export.py tests/test_project.py tests/test_paths.py -v` for adjacent CLI/path regression.
- [ ] Commit with `feat: add rough cut jianying cli`.

**Conversation Starter:**

```text
按 docs/superpowers/plans/2026-07-09-rough-cut-draft-generation-development-requirements.md 的 Requirement R5 实现 CLI 命令和 create 串联。只做 R5。依赖 R1-R4 已完成。完成后运行 R5 验收测试并提交。
```

---

### Requirement R6: Optional LLM Planner And VectCutAPIAdapter

**Goal:** Add optional enhanced planning and alternate draft export paths after the main chain works.

**Depends On:** R1-R5.

**Files:**
- Modify: `src/tripclipper/roughcut/planner.py`
- Create: `src/tripclipper/roughcut/llm_planner.py`
- Modify: `src/tripclipper/jianying/adapters/vectcutapi.py`
- Test: `tests/test_roughcut_llm_planner.py`
- Test: `tests/test_jianying_vectcutapi_adapter.py`

**Interfaces:**
- Consumes: `RoughCutPlan` schema and validator.
- Produces: optional planner engine selection such as `--planner heuristic|llm`.
- Produces: optional export engine selection `--engine vectcutapi`.

**Acceptance Criteria:**
- LLM planner output must pass `validate_rough_cut_plan`.
- LLM planner failure must not write an invalid plan file.
- VectCutAPI adapter must consume the same `RoughCutPlan` as PyJianYingDraftAdapter.
- VectCutAPI adapter must not duplicate rough-cut business logic.
- Missing optional dependencies must produce clear CLI errors.

**Out Of Scope:**
- Do not make LLM planner the default until heuristic planner and end-to-end create are stable.
- Do not make VectCutAPI a required dependency.

**Suggested Steps:**

- [ ] Add LLM planner tests with a fake provider response that returns valid JSON.
- [ ] Add LLM planner tests with invalid JSON and verify no plan file is written.
- [ ] Implement `LLMRoughCutPlanner` behind an explicit planner option.
- [ ] Add VectCutAPI adapter tests using a fake client.
- [ ] Implement `VectCutAPIAdapter` as a thin adapter over `RoughCutPlan`.
- [ ] Run `pytest tests/test_roughcut_llm_planner.py tests/test_jianying_vectcutapi_adapter.py -v`.
- [ ] Commit with `feat: add optional rough cut engines`.

**Conversation Starter:**

```text
按 docs/superpowers/plans/2026-07-09-rough-cut-draft-generation-development-requirements.md 的 Requirement R6 实现可选 LLM planner 和 VectCutAPIAdapter。只做 R6。依赖 R1-R5 已完成。不要改变默认主链路。
```

---

## Final Integration Check

Run this only after R1-R5 are complete:

- [ ] `pytest -q`
- [ ] Generate a plan from a fixture project with `tripclipper roughcut plan <slug> --target-duration 90`.
- [ ] Export the plan with `tripclipper jianying export <slug> --engine pyjianyingdraft`.
- [ ] Install the generated `draft_content.json` into a temporary Jianying library copy.
- [ ] Manually open Jianying 10 and confirm the new draft appears, opens, keeps media linked, and reopens after save.

Expected final chain:

```text
cut_index.json + project.yaml
  -> tripclipper roughcut plan
  -> rough_cut_plan.json
  -> tripclipper jianying export
  -> draft_content.json
  -> tripclipper jianying install
  -> Jianying 10 opens new draft
```

## Self-Review Notes

- Spec coverage: R1 covers `RoughCutPlan`; R2 covers `Jianying10Installer`; R3 covers `JianyingDraftExporter`; R4 covers `RoughCutPlanner`; R5 covers CLI; R6 covers optional LLM/VectCutAPI.
- Scope split: each requirement has its own test file, file boundary, dependencies, and conversation starter.
- Installation-check policy: install/create use built-in checks, with no separate user-facing preview mode.
- Dependency policy: optional adapters remain optional.
