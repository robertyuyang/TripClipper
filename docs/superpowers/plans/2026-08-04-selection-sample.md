# 选片小样规格与实现计划

## 目标

在现有 `select-review.html` 顶部增加独立的连续播放小样，帮助人工快速验收选片顺序与节奏；保留原有单候选播放器、候选列表和分类筛选。功能完全离线、只读，只覆盖任务目录中的 `select-review.html`。

## 行为规格

- 队列仅包含可播放视频候选；图片、缺失素材和无效范围跳过，并显示跳过数。
- 冷开头精确匹配分类名“开头高能人物”，按 session 顺序、session 内 `asset_ids` 顺序、`start_sec` 排序；每条播放区间中间 1 秒，不足 1 秒使用完整区间。
- 正文包含全部可播放候选且每个候选只出现一次，按 session 顺序、session 内素材顺序、`start_sec` 排序；无 session 映射项最后按 `state.candidates` 原顺序排列。
- 冷开头候选仍可在正文完整出现。队列播到片段终点时自动切换并播放下一段，末段停止且不循环。
- 提供暂停/继续、从头播放、上一段、下一段，并展示冷开头/正文进度、候选、session 和范围。
- 小样与原单候选播放器互斥；分类筛选不改变小样队列。
- CLI 主入口为 `tripclipper sample <slug> <task-name> [--base-dir PATH]`，生成后始终尝试打开浏览器；`select-review` 保留兼容别名且同样始终打开，不再提供 `--open`。
- Agent 选片成功并生成页面后始终尝试打开；打开失败只报告错误，不回滚选片结果或删除 HTML。

## 最小实现计划

1. 在现有页面上下文中计算 session 映射、小样队列和跳过数，并用测试固定排序与中间 1 秒规则。
2. 在现有模板中直接新增顶部播放器及原生 JavaScript 控制；扩展脚本化 DOM harness 验证自动续播、末段停止和播放器互斥。
3. 将 CLI 改为 `sample` 主命令、`select-review` 兼容别名，统一“生成即打开”；让 `select` 成功路径打开已生成页面。
4. 运行关键测试与全量测试；最后用 `26shidu / 30秒欢快快剪` 核验目标队列、四个输入文件哈希及浏览器打开结果。

## 验收标准

真实数据中的队列依次为：冷开头 `candidate-001` 中间 1 秒；正文 `candidate-002`、`candidate-003`、`candidate-001`、`candidate-005`、`candidate-004`。生成前后 `state.json`、`events.jsonl`、`brief.md`、`cut_index.json` 哈希不变，页面保持打开。
