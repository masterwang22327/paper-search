# Nature Reader 借鉴与本地化记录

## 状态

- 决策状态：`accepted-for-incremental-adoption`
- 实现状态：`phase-1-partial`
- 记录日期：`2026-07-21`
- 上游仓库：<https://github.com/Yuan1z0825/nature-skills>
- 审查提交：`05305ab1a636e7794849181cb97f397b49ed498b`
- 上游许可证：Apache License 2.0

本文用于把一次性的仓库评估变成可追踪的本地设计输入。第一阶段的块级翻译契约、稳定页内 ID、source map、旧缓存兼容和基本前端展示已经实现；后续阶段仍不得把“拟采用”误报为“已经实现”。本文只总结并本地化设计思想，没有复制上游 Skill 文件；如果以后复制源码或文档，应同时保留适用的许可证与 NOTICE 信息。

## 本地系统定位

本地 Reader 的输入是 `../tasks/<TASK_ID>/` 中已经完成或正在积累的调研产物，而不是任意 DOI、网页或临时上传文件。其现有优势必须保留：

- `tasks/` 是只读事实来源，固定 PDF 和 SHA-256 用于校验版本。
- Markdown 精读、物理 PDF 页和视觉附件可以互相回查。
- PDF 翻译按物理页缓存，并维护独立 Session、术语表和审计历史。
- 知识问答支持正文选区校验、持久会话和人工确认后的 FAQ 固化。
- 阅读站、动态 API 和关键交互已有自动化测试。

上游 `nature-reader` 的价值主要在“原始论文到结构化双语材料”的输出契约。本地 Reader 的价值主要在“调研材料到可交互阅读与知识积累”。因此采用策略是扩展本地数据层，而不是替换本地应用。

## 决定借鉴的设计

### 1. 从页面级译文演进到可定位的块级译文

保留物理页作为缓存、并发和用户操作的基本单位，同时在每页内部增加稳定块。建议使用本地化 ID，而不是依赖全文前面页面的块数：

- `p0003-b001`：正文、标题、公式、脚注或参考文献块
- `p0003-c001`：图注或表注
- `p0003-f001`：图
- `p0003-t001`：表

这种 ID 在相同 PDF 哈希、提取协议和页面内阅读顺序下必须稳定。不要采用纯全文递增 ID，因为前页提取变化会导致后续所有锚点漂移。

目标块至少包含：

```json
{
  "id": "p0003-b001",
  "physical_page": 3,
  "type": "heading|paragraph|caption|table|table_row|equation|footnote|reference|other",
  "order": 1,
  "original_text": "",
  "translation": "",
  "confidence": "high|medium|low",
  "bbox": null,
  "refs": []
}
```

`bbox` 只有在版面工具能够复核坐标时才填写；不能为了满足格式让模型猜坐标。旧的整页 `source_text` 和 `translation` 在迁移期继续保留，保证现有前端和历史缓存可读。

### 2. 增加按固定 PDF 版本生成的 source map

为每个 `source_id` 生成机器可读 source map，至少记录：

- `source_id`、PDF SHA-256、页数和协议版本
- 每页块 ID、类型、阅读顺序、原文、译文和置信度
- 图、表、图注与正文块之间的关系
- 当前术语账本版本
- 缺页、OCR、双栏错序和裁剪不确定性

建议目标位置为：

```text
user-data/<TASK_ID>/translations.sqlite3（逻辑键：`<SOURCE_ID>/source-map.json`）
```

这是用户生成的翻译状态，不能写回只读 `tasks/`。当 PDF 哈希或 source-map 协议版本变化时必须失效或显式迁移，不能静默复用旧锚点。

### 3. 把术语表提升为术语账本

现有 glossary 的跨页一致性继续保留，并逐步增加：

- 原文术语及大小写规范
- 确认后的标准译名
- 首次出现位置
- 源文中出现过的变体
- `locked` 状态和人工/模型来源
- 冲突与待人工确认项

同一概念不应为了语言变化而频繁更换译名。模型可以提出新术语，但不能覆盖锁定译名；无法从论文消解的一词多义应标记冲突，而不是猜测。

### 4. 显式记录不确定性

不确定性不能只存在于自然语言提示中。块、页面以及将来的图表裁剪均应保存 `confidence` 和具体 warning。特别需要覆盖：

- 扫描件或缺失文本层
- 多栏阅读顺序
- 跨页断句
- 数学公式、上下标、单位和特殊符号
- 图表边界与图注归属
- 只能从摘要或元数据确认、没有全文支持的内容

低置信内容仍可显示，但界面和问答上下文必须能把它与高置信来源区分开。

### 5. 图表作为独立证据对象，但分阶段实现

目标模型为图、表和图注分配独立 ID，并记录它们首次被正文实质讨论的位置。展示时优先放在相关讨论附近，同时保留其真实物理页。

自动裁图不属于当前已实现能力。只有在以下条件满足后才能启用：

- 裁剪框由可验证的版面信息或经过测试的工具生成，而不是模型臆测。
- 每个资源都能回到固定 PDF、物理页和 SHA-256。
- 资源文件存在性、边界和图注关联有自动检查。
- 低置信裁剪明确标注，完整 PDF 页面仍是最终回查依据。

在此之前继续使用完整 PDF 页面和当前视觉问答，不因目标设计而降低现有可靠性。

### 6. 全文处理允许增量、停止和恢复

借鉴“不得把全文请求悄悄降级为摘要”的原则，但沿用本地按页缓存方式实现。长论文可以显示完成页、待处理页和失败页；中断后只处理未缓存或已失效页面。若用户只请求摘要或指定页，则以用户范围为准。

## 第一阶段已实现

- `schemas/translation-page.schema.json` 接受可选 `blocks`，并保留旧的整页 `translation` 字段。
- 服务端根据物理页、块类型和页内顺序生成稳定 ID，例如 `p0003-c001`、`p0003-b001`；模型不能伪造全局 ID。
- 每个 PDF 版本在 `user-data/<TASK_ID>/translations.sqlite3` 的 `<SOURCE_ID>/source-map.json` 逻辑键下保存已完成页、块内容、警告和术语快照。
- `GET /api/translation/source-map` 提供当前固定 PDF 版本的 source map；PDF SHA-256、页数和版本不匹配时不复用旧 map。
- 没有返回 `blocks` 的旧缓存会在读取时生成确定性的页面级兜底块，旧 Session 和页面译文不需要全部重做。
- PDF 翻译面板按块显示自然标签、稳定 ID 和置信度；点击块可回查对应物理页，有可靠 `bbox` 时显示 PDF 区域热点；没有块数据时仍显示原有整页布局。
- 页面翻译改为无状态 Responses API：固定页文本、图像、glossary 和相邻页摘录组成完整请求；知识问答继续独立保留持久 Codex Session。
- 表格块可携带 `table_data` 并渲染为原生 HTML 表格；图片块可携带整图说明、标签对照、流程步骤和核对提示，不修改原图像素。
- Skill 校验、JSON Schema、API persistence 和 Playwright 回归覆盖了新契约。

## 明确不采用的部分

- 不全局安装整个 `nature-skills` 仓库；宽泛触发词可能与本地阅读工作流冲突。
- 不让 Reader 直接承担 DOI/arXiv/出版商 HTML 获取；合法获取和长期调研仍属于上游研究流水线。
- 不把 `paper.md` 设为唯一主交付物；本地任务精读与交互站仍是主要阅读入口。
- 不移除持久问答或 FAQ。上游对 Markdown 交付物“不放问答组件”的限制不适用于本地应用。
- 不把工作流文档当作解析实现。审查提交中的 `nature-reader` 没有自己的 PDF 解析、OCR 或图表裁剪脚本。
- 暂不采用 `nature-academic-search`、`nature-literature-pipeline` 和 `nature-downloader`；它们与上游调研已有较多重叠，且下载器有额外 Node.js、浏览器和授权配置成本。

## 建议实现顺序

1. ~~为翻译响应增加可选 `blocks`，保留旧页面字段并编写 Schema/解析测试。~~ 已完成。
2. ~~用固定 Transformer PDF 覆盖段落、标题、公式、图注、表格和双栏页面，验证重复翻译时 ID 稳定。~~ 已完成基础 API/浏览器回归；真实模型的复杂版面样本仍待补充。
3. ~~生成 source map，并让知识问答可以引用物理页加块 ID。~~ 已完成 source map；问答引用块 ID 仍待下一阶段。
4. 扩展 glossary 为可锁定的术语账本，加入冲突与迁移测试。
5. ~~前端显示块级原文/译文和置信度，但继续提供完整页面回查。~~ 已完成；当前已增加自然标签、块点击回查和可选 bbox 热点。
6. 最后评估图表检测与裁剪；未达到验证门槛时保持禁用。

## 验收条件

- 同一 PDF SHA-256 和协议版本重复处理后，块 ID 与顺序稳定。（已覆盖服务端和回归夹具。）
- PDF 或协议变化不会静默命中旧缓存。
- 每个译文块能回到原文、`source_id` 和物理页。（当前通过 source map 和页面上下文；问答 UI 的块级引用待下一阶段。）
- 低置信或缺失内容可见，不会被自动补写成确定事实。
- 锁定术语不会被后续页面覆盖。（现有 glossary 规则保留；完整术语账本字段仍待下一阶段。）
- 旧页面级缓存仍可读取；迁移失败不会损坏历史数据。
- 任何图表资源都能通过存在性、来源页、图注关系和裁剪边界检查。
- 现有引用跳页、视觉问答、持久 Session、FAQ 和只读任务边界测试继续通过。

## 固定上游参考

以下链接固定到本次审查的提交，避免上游更新改变本地决策依据：

- [`nature-reader/SKILL.md`](https://github.com/Yuan1z0825/nature-skills/blob/05305ab1a636e7794849181cb97f397b49ed498b/skills/nature-reader/SKILL.md)
- [全文 source-map-first 工作流](https://github.com/Yuan1z0825/nature-skills/blob/05305ab1a636e7794849181cb97f397b49ed498b/skills/nature-reader/static/core/workflow.md)
- [输出契约](https://github.com/Yuan1z0825/nature-skills/blob/05305ab1a636e7794849181cb97f397b49ed498b/skills/nature-reader/static/core/output-contract.md)
- [`source_map.json` 建议结构](https://github.com/Yuan1z0825/nature-skills/blob/05305ab1a636e7794849181cb97f397b49ed498b/skills/nature-reader/references/output-spec.md)
- [图表提取与语义位置规则](https://github.com/Yuan1z0825/nature-skills/blob/05305ab1a636e7794849181cb97f397b49ed498b/skills/nature-reader/references/figure-extraction.md)
- [来源约束问答规则](https://github.com/Yuan1z0825/nature-skills/blob/05305ab1a636e7794849181cb97f397b49ed498b/skills/nature-reader/references/grounding-rules.md)
- [共享术语账本](https://github.com/Yuan1z0825/nature-skills/blob/05305ab1a636e7794849181cb97f397b49ed498b/skills/nature-shared/core/terminology-ledger.md)
- [Apache-2.0 许可证](https://github.com/Yuan1z0825/nature-skills/blob/05305ab1a636e7794849181cb97f397b49ed498b/LICENSE)
