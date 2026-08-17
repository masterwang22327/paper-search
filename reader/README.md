# Research Reader

该目录把 `../tasks/<TASK_ID>/` 中的只读调研成果生成成 MkDocs Material 阅读站。生成过程不会修改任务原稿。

## 本地阅读

```bash
cd /path/to/paper_search/reader
./serve.sh <task-id>
```

浏览器打开 <http://127.0.0.1:8000>。首次运行会在 `reader/.venv/` 安装隔离依赖。

专题精读在桌面宽屏下会自动显示右侧固定论文 PDF。点击正文中带 `PDF` 标记的页码引用，右侧面板会切换到对应论文和物理页；按住 Command/Ctrl 点击则保留普通链接行为，在新标签页打开。

PDF 阅读器顶部只保留“译文”开关；打开右侧译文栏后，可分别翻译本页、后台补齐全文和查看全文缓存状态。全文翻译只处理未缓存页面，全部缓存后按钮会变为“全文已缓存”并停止重复启动任务。“重新翻译”允许选择 `gpt-5.6-terra` 或 `gpt-5.6-sol`，以及 `medium/high/xhigh/max/ultra` 推理强度，选择保存在当前浏览器。翻译按物理页直接调用无状态 Responses API，不创建或续接 Codex Session；跨页一致性由本地 glossary 和相邻页摘录提供。译文块使用“正文第 1 段”等自然标签，点击块会回查对应 PDF 页，将匹配区域置于 PDF 视口中央；放大后可按住 PDF 内容拖拽平移视图。知识问答运行时不会持有 PDF/翻译共用的长时锁；PDF 标签隐藏后暂停状态轮询，恢复时保持原页码并重新检查当前页缓存。缓存位于 `user-data/<TASK_ID>/translations.sqlite3`（需要兼容旧工具时可用 `restore.sh` 恢复为目录）。左侧项目栏可通过页面左上方的 `‹/›` 按钮收起或展开，状态会在浏览器本地保存。

右侧使用固定在 `reader/content/vendor/` 的本地 PDF.js，不依赖浏览器内置 PDF Viewer。MathJax 与字体同样已本地化，阅读时不会向 CDN 请求资源。

## 知识问答与固化

`./serve.sh` 会启动只监听 `127.0.0.1:8000` 的本地动态服务，并调用本机已经登录的 Codex CLI。网页不会读取、复制或显示 Codex 凭据。

- 每份综合报告/专题精读可以保留多个独立 Codex 对话；同一时间只有一个对话可继续调用。
- 用户可把当前对话归档为只读历史，再新建一个干净的 Codex Session；刷新或退出后仍可切换查看所有历史对话。
- Codex 调用失败时，本轮问题和失败状态也会保存在当前对话中，不会因页面与底层 Session 状态分叉而丢失。
- 在正文的一个段落内选择文字，会出现“加入知识问答上下文”；后端使用块 ID、字符偏移和构建哈希重新验证选区。
- “加入当前 PDF 页图像”只发送来源 ID 与物理页；后端从固定 PDF 渲染完整 PNG，通过 Codex CLI 的 `--image` 加入当前会话，不信任前端文件路径或标题。
- 每轮视觉问答会附带精读文档标题/路径/哈希，以及论文标题、作者、官方记录、固定来源 ID、PDF 哈希和页码信息；这些元数据均从只读任务目录生成。
- 页面图像只存在于系统临时目录，Codex 返回或调用失败后都会自动删除，不进入仓库或运行时数据库。
- PDF 页面附件每次发送后即从输入区消耗；历史消息使用本地 PDF.js 按固定来源和物理页重新绘制缩略图，不会在下一轮自动重复发送。
- 每条助手回答可由用户主动保存为 FAQ；保存前可编辑标题、核心结论和个人备注，固化后在当前文档末尾的“我的个人备忘录”中默认折叠显示。个人 FAQ 由运行时加载，不再拼进生成后的 Markdown 或正文目录；系统也不会自动从整段对话发现候选。
- 已固化 FAQ 可以逐条删除；JSON、Markdown、页面内容和删除审计会同步更新。

个人数据持久化后只有三个文件：

```text
user-data/<TASK_ID>/
├── state.sqlite3         # 会话、聊天、FAQ、修订、设置、队列、审计及迁移的旧运行文件
├── translations.sqlite3  # manifest、术语、source-map、逐页译文与翻译审计记录
└── site.sqlite3          # HTML、JavaScript、样式、字体、图片及 canonical PDF 映射
```

SQLite 中仍以原相对路径作为主键保存每个工件的完整字节、权限、时间与 SHA-256。旧版聊天、FAQ、
修订、设置、日志与队列文件，以及 `translations/<SOURCE_ID>/...`，首次运行时都会先逐项导入并校验，
确认一致后才移除散文件。服务运行中直接读写数据库，不会重新生成这些 JSON、JSONL 或 Markdown；
`restore.sh` 可完整恢复兼容目录结构。

`user-data/` 已被 Git 忽略，也不会进入生成站点。Reader 的 `serve.sh` 和 `build.sh` 始终只读任务内容。
任务中的 canonical PDF 和论文 Markdown 保持普通文件；非 PDF 来源工件、已完成 handoff、历史 run 和 work
中间件可保存在 `tasks/<TASK_ID>/artifacts.sqlite3`。Reader 会按原逻辑路径直接查询该数据库。

翻译默认使用 `https://www.sevnx.one/v1/responses`、`gpt-5.6-terra` 和 `medium` reasoning effort。
重新翻译会忽略缓存，默认使用 `gpt-5.6-sol` 和 `high`；也可在译文栏切换到允许的模型与推理强度。翻译采用文本层确定覆盖范围、页面图像校准
公式与版面的双源流程，并在保存前复核易错数学符号。

当 Reader 的 Responses URL 与本机 Codex 当前 provider 的 `base_url + /responses` 精确匹配时，
Reader 会复用 Codex `auth.json` 中的 `OPENAI_API_KEY`。端点不匹配时不会转发该凭据，必须显式配置
目标端点自己的 `READER_TRANSLATION_API_KEY`。当 URL 为 `https://api.openai.com/v1/responses` 时，
也允许回退读取 `OPENAI_API_KEY` 或 Codex API Key。
密钥只存在于进程环境和请求头，不写入 Reader 文件。不要把密钥直接写进命令历史、README、配置文件
或 Git remote URL。

```bash
export READER_TRANSLATION_API_KEY
./serve.sh <task-id>
```

端点和常规翻译模型可通过 `READER_TRANSLATION_API_URL`、`READER_TRANSLATION_MODEL` 覆盖；重译配置可
通过 `READER_RETRANSLATION_MODEL`、`READER_RETRANSLATION_REASONING_EFFORT` 覆盖。

## 构建静态站点

```bash
./build.sh <task-id>
```

`build.sh` 在系统临时目录生成 Markdown 和 MkDocs 输出，逐项校验后写入
`user-data/<TASK_ID>/site.sqlite3`，随后自动清理临时目录。Reader 运行时直接从 SQLite 返回 HTML、
JavaScript、样式、字体和图片；PDF URL 则映射到 `tasks/` 中的 canonical 文件并支持 HTTP Range，
不产生 PDF 副本。项目内不会生成常驻 `docs/` 或 `site/` 目录。

`serve.sh` 会先比较任务内容、来源工件库、PDF 和 Reader 源码的输入指纹，并执行 SQLite 快速完整性检查。
指纹未变化时直接复用现有 `site.sqlite3`，启动过程也不会再生成临时 MkDocs 文件树；只有首次启动、输入变化
或数据库损坏时才重建。`build.sh` 始终用于显式强制重建。

需要显式收拢任务工件/重建运行时数据库，或恢复兼容目录时运行：

```bash
./compact.sh <task-id>
./restore.sh <task-id>
```

`compact.sh` 是显式维护操作：逐项导入并校验后，把非 PDF 来源文件、已完成 handoff、非当前 run 和 work
中间件收拢到任务级 `artifacts.sqlite3`，但不移动 canonical PDF、论文 Markdown 或当前 run 热状态。
`restore.sh` 会恢复原目录结构，只用于兼容或人工恢复，不是 Reader 启动前置步骤。

不展开文件树也可查看任意已归档工件：

```bash
python3 task_store.py list --task-dir ../tasks/<task-id> --key sources/<stable-id>
python3 task_store.py read --task-dir ../tasks/<task-id> --key sources/<stable-id>/evidence.md
```

`serve.sh` 和 `build.sh` 都要求显式提供 task ID，避免公开仓库意外绑定某个本机任务。

## 数据边界

- `../tasks/` 是唯一事实来源；Reader 直接读取 canonical 文件和 `artifacts.sqlite3` 中的逻辑文件。
- Markdown 与 MkDocs 输出只在首次或输入变化后的重建中短暂存在于系统临时目录；正常启动直接复用数据库。
- 站点数据库保存逻辑路径、压缩内容、MIME、大小、时间与 SHA-256；canonical PDF 只保存路径和哈希。
- 服务运行前、运行中和运行后都直接使用 SQLite，不会展开站点或个人数据文件树。
- 任务工件数据库保存原相对路径、完整字节、权限、时间与 SHA-256；当前 run 仍由普通热状态文件维护。
- 来源代码、模型、数据与中间运行文件不会执行。

## 回归测试

```bash
./test.sh
```

测试使用本机 Google Chrome 或 Microsoft Edge，不额外下载浏览器。它会验证 PDF 渲染、引用跳页、面板拖动、宽度持久化和无外部网络请求。

无法自动识别的引用可在 `citation-overrides.yml` 中人工校正；该文件只影响阅读副本，不修改原始研究 Markdown。

## 设计记录

- [`design/nature-reader-adoption.md`](design/nature-reader-adoption.md)：记录从开源 `nature-reader` 借鉴的块级双语、source map、术语账本和图表证据设计，以及本地不采用的范围和分阶段验收条件。第一阶段的块级翻译、稳定页内 ID 和 source map 已实现；图表裁剪与块级问答引用仍在后续阶段。
