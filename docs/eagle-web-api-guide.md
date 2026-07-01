# Eagle Web API — 使用指南（M6 沉淀）

> 这份文档记录的是我们在 M6 (Eagle 同步) 阶段通过真机 (Eagle 4.x, macOS)
> 反复探测得到的一手结论，覆盖 [src/tripclipper/eagle_sync.py](file:///Users/bytedance/Documents/TripClipper_Trae/src/tripclipper/eagle_sync.py)
> 里 `EagleV2Client` 和 `EagleSyncRunner` 依赖的所有 API 行为。
> Eagle 官方文档只覆盖了很小的子集，且不区分 V1/V2；下面标 **[实测]** 的结论
> 都能用文档末尾的 curl 复现，请以实测为准。
>
> 版本基线：Eagle **4.0 Build 21+**（macOS）。低版本没有 V2 端点。

---

## 1. 一句话概览

Eagle 是一个本地图片/视频/文件资源管理软件。它在本机 41595 端口起了一个
HTTP 服务，我们通过这个 HTTP 服务把 cut_index 里的字段以 tag/rating/note 的
形式写入 Eagle 的当前"资源库"(library)。

- **Host root**：`http://localhost:41595`（127.0.0.1 也可）
- **鉴权方式**：`?token=<uuid>` 查询参数（**不是** `Authorization` 头）
- **响应封装**：`{"status": "success"|"error", "data": ...}`
- **API 家族**：Eagle 4.x 同时暴露 V1 (`/api/*`) 和 V2 (`/api/v2/*`)，**混用**

---

## 2. 混合 V1/V2 端点路由（关键坑）

**[实测]** Eagle 4.x 的 V2 家族**只覆盖了一部分能力**，item 的读写没搬到 V2。
如果整个客户端只指向 `/api/v2/`，`item/addFromPath` 和 `item/moveToTrash`
都会返回 404 `"method not allowed"`。

因此我们的 [EagleV2Client](file:///Users/bytedance/Documents/TripClipper_Trae/src/tripclipper/eagle_sync.py#L106-L322)
里 `base_url` 只保留 host root，**每个方法内部按端点自己拼 `/api/v2/` 或 `/api/` 前缀**。

| 客户端方法 | HTTP | 实际路径 | 家族 |
|---|---|---|---|
| `fetch_library()` / `health_check()` | GET | `/api/v2/library/info` | **V2** |
| `add_from_path(...)` | POST | `/api/item/addFromPath` | **V1** |
| `update_item(...)` | POST | `/api/v2/item/update` | **V2** |
| `move_to_trash(item_ids)` | POST | `/api/item/moveToTrash` | **V1** |
| `tag_group_create(name, tags)` | POST | `/api/v2/tagGroup/create` | **V2** |
| `tag_group_update(id, ...)` | POST | `/api/v2/tagGroup/update` | **V2** |
| `tag_group_remove(ids)` | POST | `/api/v2/tagGroup/remove` | **V2** |

**为什么这样分**：Eagle 官方的思路是"V2 只暴露 V1 里做得不好的部分"——library
元信息、标签组体系是 V2 新增的；item 的原子操作还是走 V1 老路。这不是我们能
选的，是服务端硬性的。

**兼容旧配置**：`EagleV2Client.__init__` 里的 `base_url` 会容忍 `/api/v2/` 或
`/api/` 后缀（用 `.rstrip("/")` 后剥离），所以老 `project.yaml` 里带后缀的配置
也不会 break。

---

## 3. 鉴权：查询参数，不是 Header

**[实测]** Eagle 只认 `?token=<uuid>` 查询参数。把 token 放到
`Authorization: Bearer <token>` 头里请求会得到 401；放在 `X-API-Token` 里也不行。

我们的 `_with_token(params)` 每次请求都会合并到 query params 里，POST 也一样
（POST 时 body 走 JSON，token 仍走 query）。

**Token 从哪来**：Eagle 应用 → 偏好设置 → 开发者 → 打开 API server → 复制 token。
如果 Eagle **没开** API server，端口 41595 直接连接被拒（`httpx.ConnectError`，我们
映射成 `EagleUnavailableError`）。**API server 开着但 token 未设置**时，可以裸调，
所以本地开发一般不需要 token；生产/远程访问才建议开。

---

## 4. 响应封装

Eagle 所有 API 都返回 JSON，封装成：

```json
{"status": "success", "data": <payload>}
```

失败时：

```json
{"status": "error", "data": null}
```

或者 HTTP 层直接 4xx/5xx。**关键坑**：Eagle 有些"业务失败"用 200 + `status:"error"`
表达（而不是 HTTP 500），所以客户端必须**同时看 status_code 和 payload.status**。
[EagleV2Client._unwrap()](file:///Users/bytedance/Documents/TripClipper_Trae/src/tripclipper/eagle_sync.py#L165-L176)
做了这两层检查。

---

## 5. 各端点详解

### 5.1 `GET /api/v2/library/info` — 库快照（我们的一号数据源）

Eagle 4.x **没有独立的 `tagGroup/list` 端点**（V1 V2 都没有）。要拿到当前库
所有 tag group 的 id / name / tags，唯一的官方路径就是 `library/info`。

**响应关键字段**（我们真的用到的）：

```json
{
  "status": "success",
  "data": {
    "path": "/Users/.../demo.library",   // ★ 库绝对路径
    "library": null,                      // 老字段，可能不存在
    "name": "demo",
    "tagsGroups": [                       // ★ 全部 tag group 快照
      {
        "id": "MR1UMMVJAARQM",
        "name": "tc:project",
        "tags": ["tc:project:demo-scan"]
      },
      ...
    ]
  }
}
```

**注意事项 [实测]**：
- V2 里的 `data.path` 就是老 V1 里的 `data.library`。V2 之后 `library` 字段
  在部分版本上返回 `null`，**读库路径必须优先 `data.path`，回落 `data.library`**。
  [fetch_library()](file:///Users/bytedance/Documents/TripClipper_Trae/src/tripclipper/eagle_sync.py#L201-L237) 就是这么写的。
- `tagsGroups[i].tags` 是**该 group 当前包含的全部 tag**，是一个字符串数组，
  不带 id、只带字面 tag 名。
- 请求 `library/info` 时 Eagle 会返回**当前打开的库**——不是任意库。切库只能在
  Eagle App UI 上做，API **不提供** switch library 的能力（V1 有一个
  `library/switch`，但 V2 未提供且行为不稳定，M6 决定不用）。
- 该端点极轻量（无 IO），可以放心做启动期 health check。

**M6 里的用法**：
1. 启动期第一次调用，同时做 (a) 版本探测（404 → 太老）(b) 拿库路径 (c) 建 tag
   group name→id 索引（幂等所需）。
2. 用户传了 `--library-path` 时，把返回的 `data.path` 和期望路径比对——不一致
   直接 exit 2，不让把素材写错库。

---

### 5.2 `POST /api/item/addFromPath` — 从本地路径导入素材（V1）

**Request body**：

```json
{
  "path": "/abs/path/to/file.mp4",       // 必填，绝对路径
  "name": "航拍样片01.mp4",              // ★ 见下方注意
  "tags": ["tc:project:demo-scan", ...],
  "annotation": "自由文本",              // Eagle 里叫 note
  "star": 5                              // 可选，rating，1-5，不传就没星
}
```

**响应**：

```json
{"status": "success", "data": {"id": "MR1UMMU3XNCDF"}}
```

**[实测] 关键行为**：

1. **服务端不做重复检测**。同一个 `path` 连续调两次，会创建**两个不同 id 的 item**。
   Eagle App UI 上有一个 "hash + 尺寸相同视为重复" 的弹窗，那个弹窗**只走 UI 拖拽
   路径**，API 层完全不触发。所以幂等必须由客户端保证（我们靠 `asset.eagle_item_id`
   本地游标：只要它非空，就走 `item/update` 分支）。
2. **Eagle 自动砍扩展名**。传 `name="IMG_4306.mov"`，Eagle 内部存成
   `name="IMG_4306"` + `ext="mov"`。所以 `name` 字段传"含扩展名"或"不含扩展名"
   在 UI 上看起来一样，但严格 assert 时要注意扩展名会被单独抠出去。
3. **`path` 必须是绝对路径**且**当前用户可读**。相对路径 / 网络路径 / 不存在的
   路径会返回 200 + `status:"error"`。
4. **`path` 不会写进 metadata**。Eagle 拿到文件后会 hash+复制到库内部的
   `images/<id>.info/` 目录，**从此不再保留原始来源路径**（metadata.json 里没有
   `sourcePath`、`importedPath` 之类字段）。这意味着：**通过 API 无法用"原始路径"反查
   Eagle 里是否已有此素材**——只能靠本地游标 (`cut_index.eagle_item_id`) 记账。
5. `tags` 可以直接传数组，Eagle 会按需要把 tag 追加到库的全局 tag 列表里，但**不会
   把这些 tag 归入任何 tag group**——tag group 的归属要**单独**通过 `tagGroup/create`
   或 `tagGroup/update` 来维护（见 5.6）。
6. 传空的 `annotation`（`""`）Eagle 接受；不传该字段也行；传 `null` 会 400。

---

### 5.3 `POST /api/v2/item/update` — 局部覆盖 item 属性（V2）

**Request body**（只传要改的字段，其它字段不动）：

```json
{
  "id": "MR1UMMU3XNCDF",       // 必填
  "tags": ["tc:project:demo-scan", ...],  // 可选，全量覆盖
  "star": 4,                    // 可选，rating
  "annotation": "新的备注"      // 可选，note，全量覆盖
}
```

**响应**：`{"status": "success", "data": null}`（无 payload）

**[实测] 关键行为**：

1. **字段级"全量覆盖" + 端点级"部分更新"**：只要出现在 body 里的字段就会被
   完全覆盖（tags 数组会被整个替换，不是 append）；没出现的字段不动。
2. 传 `"tags": []` 会**清空** tags。传 `"tags": null` 会 400。所以我们在
   [update_item()](file:///Users/bytedance/Documents/TripClipper_Trae/src/tripclipper/eagle_sync.py#L273-L288)
   里对可选字段用 `is None` 判断，不用 `or {}`。
3. 不能通过 `item/update` 换绑文件、改 path、改 hash——那些是导入期决定的，
   之后就只读了。
4. 找 item 的**唯一 key 是 `id`**（Eagle 内部的 13 位字符串，例如
   `MR1UMMU3XNCDF`）。没有"按 path 找 item" / "按 filename 找 item"的官方端点。

---

### 5.4 `POST /api/item/moveToTrash` — 移到回收站（V1）

**Request body**：

```json
{"itemIds": ["MR1UMMU3XNCDF", "MR1UMMU3YXY01"]}
```

支持批量。**响应**：`{"status": "success", "data": null}`。

**[实测] 关键行为**：

1. **不是真删**，只是移到 Eagle 库的回收站。要清空回收站得手动在 Eagle UI 里做
   （`Menu → File → Empty Trash`），或调 `/api/item/emptyTrash`（我们没用）。
2. 已 moveToTrash 的 item 通过 `item/update` 更新一般会成功，但从 UI 上是灰的。
   所以 `--reset` 里必须先 moveToTrash **再**清本地 `eagle_item_id` 游标，让下一次
   走 addFromPath 重建，不然容易操作到回收站里的僵尸 item。

---

### 5.5 `POST /api/v2/tagGroup/create` — 创建 tag group（V2）

**Request body**：

```json
{
  "name": "tc:project",
  "tags": ["tc:project:demo-scan"]
}
```

**响应**：

```json
{"status": "success", "data": {"id": "MR1UMMVJAARQM"}}
```

**[实测] ★★ 严重坑 ★★**：

> **Eagle 服务端不对 tag group name 做去重。**

连续 3 次 create `{"name":"tc:project"}` → 你会得到**三个不同 id 的 tag group**，
Eagle App UI 左侧会同时显示 3 个"tc:project"分组。这是我们最初真机同步失败之后
在 `testku.library` 里遗留 14 条重复 `tc:*` group 的**根因**。

**幂等策略（M6 采纳）**：
1. 启动期从 `library/info.tagsGroups` 构建 `name → {id, tags}` 快照。
2. 需要落 tag group 时先查快照：
   - **不存在** → `tagGroup/create` + 把新 id 回填快照
   - **已存在** → `tagGroup/update(id, tags=<全量>)` **全量覆盖**

代码见 [EagleSyncRunner.run() 里 tag group 段](file:///Users/bytedance/Documents/TripClipper_Trae/src/tripclipper/eagle_sync.py#L889-L920)。

---

### 5.6 `POST /api/v2/tagGroup/update` — 更新 tag group（V2）

**Request body**：

```json
{
  "id": "MR1UMMVJAARQM",   // 必填
  "name": "新的组名",       // 可选，改组名
  "tags": [                // 可选，全量覆盖
    "tc:project:demo-scan",
    "tc:project:2026-japan-trip"
  ]
}
```

**[实测] 关键行为**：

1. `tags` 字段是**全量覆盖**，不是 append。传 `["a"]` 会把原来的
   `["a","b","c"]` 变成 `["a"]`（丢掉 b、c）。所以每次 update 前**必须先合并**
   现有的和新增的，再传全量。
2. 不存在的 `id` 返回 200 + `status:"error"`。
3. **不能**通过 `tagGroup/update` 添加 tag 到全局 tag 索引里——tag 必须先存在（一般
   由 item 上带过来）。传一个从没在任何 item 上出现过的 tag 到 tagGroup/update.tags 里
   在 UI 上不会报错，但那个 tag 在库全局的 tag 面板里可能显示为"孤儿"。

**曾经的误区**：Eagle 文档里提过一个 `tagGroup/addTags` 端点（`{"id","newTags"}`），
我们最初也写了 `tag_group_add_tags()` 方法。**[实测]** 该端点在 4.0 Build 21 上
返回 404，改用 `tagGroup/update` 全量覆盖后一切工作。M6 的客户端里已经**删除**了
`tag_group_add_tags` 方法。

---

### 5.7 `POST /api/v2/tagGroup/remove` — 删除 tag group（V2）

**Request body**：

```json
{"itemIds": ["MR1UMMVJAARQM", "MR1UMMVXABCDE"]}
```

**★ 坑**：字段名是 `itemIds`，不是 `groupIds` 或 `ids`——Eagle 复用了
item/moveToTrash 的字段名。传 `groupIds` 会 200+`status:"error"`。这个是靠
反复实测抠出来的，官方文档里没写。

**[实测] 行为**：
- 删的是 tag group 本身（分组容器），**不删** group 里的 tag。也就是说，group 删掉
  之后，那些 tag 仍然存在于 item 上、以及库的全局 tag 列表里，只是从"分组视图"里
  拿掉了。这也是幂等策略选"update 全量覆盖"而非"remove + create"的原因之一——后者
  会导致 tag 短暂脱离分组。
- 批量支持。空数组会 400。

---

## 6. Item metadata.json 的可见字段（**不用于同步**）

`<library>/images/<item_id>.info/metadata.json` 里 Eagle 存的 item 全部字段
（实测拉出来的 key 列表）：

```
id, name, size, btime, mtime, ext, tags, folders,
isDeleted, url, annotation, modificationTime,
width, height, resolutionWidth, resolutionHeight,
duration, lastModified, palettes
```

- **没有** `sourcePath` / `importedPath` / `originalPath` — 见 5.2 第 4 点。
- `star`（rating）字段在 API 层叫 star，但在 metadata.json 里我不确定它在哪个 key
  下——暂未观察到独立 star 字段，可能被合并到别的对象里。**M6 不读 metadata.json**，
  它是 Eagle App 自己内部持久化的产物，我们只走 API。

---

## 7. 常见错误 & 排错清单

| 症状 | 根因 | 解法 |
|---|---|---|
| 端口 41595 `ConnectError` | Eagle 没开 / API server 关着 | 打开 Eagle App，偏好 → 开发者 → 开 API |
| 所有请求返回 404 "not found" | 端点走了错的家族（V2→V1 或反过来）| 见第 2 节的路由表 |
| `library/info` 返回 401 | 设置了 token 但没带 `?token=` | 走 `_with_token()` |
| addFromPath 返回 200+error | path 相对 / 不存在 / 无读权限 | 检查绝对路径可读 |
| 同步跑第二次库里 item 翻倍 | 客户端没维护本地游标(eagle_item_id) | 见 5.2 第 1 点 |
| 库里 `tc:project` 有 5 份 | 每次 apply 都 tagGroup/create | 见 5.5，改成 create-or-update |
| item 名字末尾少了 `.mov` | Eagle 砍扩展名 | 见 5.2 第 2 点，UI 上其实还是显示 `IMG_4306.mov` |
| 同步跑完素材去了错的库 | Eagle 里当时打开的库不是目标库 | 传 `--library-path` 门禁 |

---

## 8. curl 复现小抄

假设 token 是 `X`（没设置就把 `?token=X` 去掉）：

```bash
# 库快照 + tagsGroups
curl -s "http://localhost:41595/api/v2/library/info?token=X" | jq

# 导入本地文件
curl -s -X POST "http://localhost:41595/api/item/addFromPath?token=X" \
  -H "Content-Type: application/json" \
  -d '{"path":"/abs/x.mp4","name":"x","tags":["tc:demo"],"annotation":"","star":4}' | jq

# 更新 item
curl -s -X POST "http://localhost:41595/api/v2/item/update?token=X" \
  -H "Content-Type: application/json" \
  -d '{"id":"MR1U...","tags":["tc:new"],"annotation":"new note"}' | jq

# 移到回收站（批量）
curl -s -X POST "http://localhost:41595/api/item/moveToTrash?token=X" \
  -H "Content-Type: application/json" \
  -d '{"itemIds":["MR1U...","MR1V..."]}' | jq

# 创建 tag group
curl -s -X POST "http://localhost:41595/api/v2/tagGroup/create?token=X" \
  -H "Content-Type: application/json" \
  -d '{"name":"tc:project","tags":["tc:project:demo-scan"]}' | jq

# 更新 tag group（全量覆盖 tags）
curl -s -X POST "http://localhost:41595/api/v2/tagGroup/update?token=X" \
  -H "Content-Type: application/json" \
  -d '{"id":"MR1U...","tags":["tc:project:demo-scan","tc:project:next"]}' | jq

# 删除 tag group（注意字段名是 itemIds）
curl -s -X POST "http://localhost:41595/api/v2/tagGroup/remove?token=X" \
  -H "Content-Type: application/json" \
  -d '{"itemIds":["MR1U..."]}' | jq
```

---

## 9. 版本 & 兼容性

| 检查项 | 要求 | 现象（不满足） |
|---|---|---|
| Eagle 版本 | ≥ **4.0 Build 21** | `/api/v2/library/info` 返回 404 → 我们抛 `EagleVersionError` |
| API server 开着 | 是 | 41595 端口 `ConnectRefused` → `EagleUnavailableError` |
| 当前打开的库 | 是目标库 | `library/info.data.path` 不匹配 → CLI 加 `--library-path` 做门禁 |

低于 Build 21 的 Eagle 只有 V1 API，`tagGroup/*` 家族完全不存在，M6 无法工作。
不做向下兼容——我们直接在 fetch_library 阶段 404 抛版本错误。

---

## 10. 相关代码

- 客户端封装：[src/tripclipper/eagle_sync.py — EagleV2Client](file:///Users/bytedance/Documents/TripClipper_Trae/src/tripclipper/eagle_sync.py#L106-L322)
- 幂等策略：[src/tripclipper/eagle_sync.py — Runner tag group 段](file:///Users/bytedance/Documents/TripClipper_Trae/src/tripclipper/eagle_sync.py#L889-L920)
- CLI 门禁：[src/tripclipper/cli.py — sync-eagle 命令](file:///Users/bytedance/Documents/TripClipper_Trae/src/tripclipper/cli.py#L529-L685)
- 设计决策背景：[ADR-004 Eagle 同步作为薄映射层](file:///Users/bytedance/Documents/TripClipper_Trae/docs/adr/ADR-004-eagle-sync-as-thin-mapping-layer.md)
- 端到端 mock 测试：[tests/test_eagle_client.py](file:///Users/bytedance/Documents/TripClipper_Trae/tests/test_eagle_client.py)、[tests/test_eagle_sync_runner.py](file:///Users/bytedance/Documents/TripClipper_Trae/tests/test_eagle_sync_runner.py)
