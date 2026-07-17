## 1. R0 Fixture Package

- [x] 1.1 Create rough-cut, Jianying, and media fixture directories.
- [x] 1.2 Add `minimal_cut_index.json` with video, image, and audio assets.
- [x] 1.3 Add `legacy_eval_rough_cut_source.json` from the demo rough cut sample with portable paths.
- [x] 1.4 Add `realistic_draft_content.json` from the demo draft sample with portable media paths.
- [x] 1.5 Add formal `minimal_rough_cut_plan.json` covering video, image, audio, and text timeline segments.
- [x] 1.6 Add `minimal_template_draft/` shell files required by later installer tests.
- [x] 1.7 Add and pass `tests/test_roughcut_fixture_contract.py`.

## 2. R1 RoughCutPlan Schema, IO, and Validator

- [x] 2.1 Add failing model and IO tests in `tests/test_roughcut_models.py`.
- [x] 2.2 Add failing validator tests in `tests/test_roughcut_validator.py`.
- [x] 2.3 Implement `src/tripclipper/roughcut/models.py`.
- [x] 2.4 Implement `src/tripclipper/roughcut/io.py`.
- [x] 2.5 Implement `src/tripclipper/roughcut/validator.py`.
- [x] 2.6 Export public names from `src/tripclipper/roughcut/__init__.py`.
- [x] 2.7 Run R1 acceptance tests plus adjacent model regressions.
