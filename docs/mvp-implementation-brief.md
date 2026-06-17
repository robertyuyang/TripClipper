# TripClipper MVP 文档索引

原来的 MVP 实施简报同时包含产品需求和技术实现细节，现已拆分为两份文档：

- [MVP 产品需求文档](mvp-product-requirements.md)：说明 MVP 要解决什么问题、面向哪些场景、包含和不包含哪些产品能力，以及如何验收。
- [MVP 技术设计文档](mvp-technical-design.md)：说明本地架构、CLI/FastAPI 入口、数据包结构、分析流程、Eagle 适配器和工程验收方式。
- [拆分前的 MVP 实施简报原文](mvp-implementation-brief-original.md)：保留产品需求和技术实现合在一起的旧版本。

后续版本规划见 [TripClipper 后续版本需求路线图](future-version-requirements.md)。

## 原始上下文

原始需求文档路径：

```text
/Users/bytedance/Documents/New project/travel-material-agent-requirements.md
```

当前仓库路径：

```text
/Users/bytedance/Documents/TripClipper
```

## 推荐实现提示词

新开实现线程时，使用下面这段提示词：

```text
请进入 Goal 模式，并按以下两份文档实现 TripClipper MVP：
/Users/bytedance/Documents/TripClipper/docs/mvp-product-requirements.md
/Users/bytedance/Documents/TripClipper/docs/mvp-technical-design.md

请先读取产品需求，再读取技术设计，然后从 Python 项目骨架开始，依次实现 CLI、项目配置、Stage 1 扫描、真实模型 Stage 2 分析、可迁移导出、Eagle dry-run/apply，以及 FastAPI 本地启动页。

第一版必须安全：不删除、不移动、不覆盖原始素材；ffmpeg、Eagle 失败时都不能阻塞本地数据包导出；Stage 2 必须使用真实模型，模型配置缺失、密钥缺失或调用失败时必须明确失败并提示修正，不得生成替代性假分析结果。
```
