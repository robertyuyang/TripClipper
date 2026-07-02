# Session Splitting 验收清单

## 如何手动验证本模块

> 本 change 无独立 CLI 入口；验收靠：**重跑 demo 项目** + **检查 `cut_index.json` 字段** + **Eagle folder 视觉核对** + **测试套件**。

```bash
# 0) 前置：ffmpeg/ffprobe 与 .env 就绪；Eagle 已启动
export PATH="/opt/homebrew/bin:$PATH"
ffprobe -version
curl -s http://localhost:41595/api/v2/application/info | head -c 200

# 1) 清掉旧 demo，重新初始化
rm -rf projects/demo-scan
tripclipper init --config projects/demo-scan/project.yaml

# 2) 重跑 scan
tripclipper scan demo-scan
# 期望：日志包含 "切分为 N 个 session（gap=1h）"

# 3) 查 cut_index.json
python -c "import json; d = json.load(open('projects/demo-scan/cut_index.json')); \
  print('sessions:', len(d.get('sessions', []))); \
  print('assets with session_id:', sum(1 for a in d['assets'] if a.get('session_id')))"

# 4) 跑一次 analyze
tripclipper analyze demo-scan --stage sample
tripclipper analyze demo-scan --stage full

# 5) Eagle 同步 dry-run（应显示 Sessions preview）
tripclipper sync-eagle demo-scan --dry-run
# 期望：输出末尾有 "Sessions preview (gap=1h):" 段

# 6) Eagle 正式同步
tripclipper sync-eagle demo-scan --apply
# 期望：Eagle 里出现 "TripClipper: demo-scan" 父 folder，其下有 session_XX 子 folder
```

## 验收项

### 数据契约

- [ ] `Asset.session_id: Optional[str]` 字段存在且默认为 `None`
- [ ] `Session` 模型存在，包含 `session_id / asset_ids / started_at / ended_at / asset_count`
- [ ] `CutIndex.sessions: list[Session]` 字段存在且默认空 list
- [ ] `SCHEMA_VERSION` **未 bump**（保持 "0.3"）
- [ ] 旧 cut_index.json（无 `sessions` 字段）可正常读取，读出 `sessions=[]`

### session_splitter 模块

- [ ] 新增 `src/tripclipper/session_splitter.py`
- [ ] 常量 `SESSION_GAP_HOURS = 1.0` 定义在模块顶部
- [ ] `split_sessions(assets, *, gap_hours=SESSION_GAP_HOURS)` 是纯函数（无 IO、无 LLM、无外部依赖）
- [ ] `apply_sessions(assets, sessions)` 把 `session_id` 写回 asset
- [ ] `modified_time=None` 的 asset 归入 `session_00_unknown`
- [ ] 无 `modified_time` 缺失时不输出 `session_00_unknown` session

### scan 集成

- [ ] scan 完成时自动调 `split_sessions` + `apply_sessions`
- [ ] scan 日志包含 `切分为 N 个 session` 摘要行
- [ ] scan 后的 `cut_index.json` 每个 asset 有 `session_id`（除非 modified_time=None，归 `session_00_unknown`）
- [ ] scan 后 `cut_index.sessions` 非空（假设 demo 素材有效）

### Eagle 同步集成

- [ ] `EagleClient.folder_create(name, parent_id=None) -> str` 存在
- [ ] `EagleClient.add_from_path` 新增 `folder_id` 可选参数
- [ ] `sync-eagle --apply` 时 Eagle 里**不**创建 `TripClipper: <slug>` 父 folder（Q13）
- [ ] 每个 session 对应一个独立 folder，名字格式为 `{slug} · session_XX · YYYY-MM-DD HH:MM`
- [ ] `session_00_unknown` 也有独立 folder，名字为 `{slug} · session_00_unknown`（无时间部分）
- [ ] 每个 asset 落到对应 session folder 里
- [ ] 已有 `eagle_item_id` 的 asset 跳过 folder 归属并写 warning
- [ ] 多项目场景：不同项目的 folder 因 slug 前缀不同不会撞名

### CLI 参数

- [ ] `scan` 命令**没有** `--gap-hours` / `--session-gap-hours` 参数
- [ ] `analyze` 命令**没有** `--stage session` 选项
- [ ] `sync-eagle` 命令**没有** `--split-by-session` 开关

### dry-run 输出

- [ ] `sync-eagle --dry-run` 输出末尾包含 `Sessions preview (gap=1h):` 段
- [ ] preview 显示每个 session 的 `session_id / 起止时间 / 素材数`
- [ ] session 数 > 12 时中间省略号截断

### review.html Session 视图

- [ ] 顶栏有 `扁平视图 / Session 视图` 切换 tab，默认扁平视图
- [ ] 扁平视图表格新增 `session` 列，显示 `session_id`（`session_00_unknown` 灰色徽章）
- [ ] Session 视图按 `session_id` 分组显示卡片，卡片头含 `session_XX · 起止时间 · N 张`
- [ ] Session 卡片头展示前 6 张缩略图 + 溢出计数
- [ ] Session 卡片可折叠/展开，顶栏有 `全部折叠 / 全部展开` 按钮
- [ ] `session_00_unknown` 卡片排在最末，标注"时间信息缺失"
- [ ] 过滤器行 新增 `filter-session` 下拉，两种视图下均生效
- [ ] 视图切换保留过滤器状态
- [ ] overview 头部有 `共 N 个 session（含 unknown X 张）` 摘要
- [ ] `tests/test_exporter.py` 补充 session 视图 HTML 断言（有 tab、有卡片、有 session 列）

### 兼容与降级

- [ ] 旧项目 `sessions=[]` 时 sync-eagle 完全跳过 folder 逻辑（不建任何 folder），asset 直接平铺入 Eagle 根目录
- [ ] 全部 asset `modified_time=None` 时全部归入 `session_00_unknown` 一段

### 测试

- [ ] `tests/test_session_splitter.py` 覆盖 5 个基础用例
- [ ] `tests/test_scan.py` 补充 session 相关断言
- [ ] `tests/test_eagle_sync.py` 补充 folder_create + folder_id 传递断言
- [ ] `pytest` 全绿
