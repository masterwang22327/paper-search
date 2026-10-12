# Research Reader

该目录把 `../tasks/<TASK_ID>/` 中的只读调研成果生成成 MkDocs Material 阅读站。生成过程不会修改任务原稿。

使用范围是 Mac 上的桌面浏览器论文阅读。布局与验收围绕桌面窗口、浏览器缩放、鼠标和键盘操作，以及可拖动的正文/PDF/译文分栏展开。

在没有本地文件的新电脑上，按 [完整恢复指南](../docs/reader-migration.md) 从 GitHub 和 ModelScope
私有备份恢复。个人记录和缓存按原路径保存；启动器支持 Python 3.11+，首次安装使用锁定的依赖版本。

## 本地阅读

```bash
cd /Users/4paradigm/Desktop/knowledge_factory/paper_search/reader
./serve.sh paper-research-base-knowledge-about-llm-20260717
```

浏览器打开 <http://127.0.0.1:8000>。首次运行会在 `reader/.venv/` 安装隔离依赖。

专题精读在桌面宽屏下会自动显示右侧固定论文 PDF。点击正文中带 `PDF` 标记的页码引用，右侧面板会切换到对应论文和物理页；按住 Command/Ctrl 点击则保留普通链接行为，在新标签页打开。

PDF 阅读器顶部提供“解析”和“译文”开关；打开右侧译文栏后，可分别翻译本页、后台补齐全文和查看全文缓存状态。全文翻译只处理未缓存页面，全部缓存后按钮会变为“全文已缓存”并停止重复启动任务。“重新翻译”允许选择 `gpt-6-astra` 和 `gpt-6.1-sol`，推理强度随模型切换，选择保存在当前浏览器。翻译按物理页直接调用无状态 Responses API，不创建或续接 Codex Session；跨页一致性由本地 glossary 和相邻页摘录提供。译文块使用“正文第 1 段”等自然标签，点击块会回查对应 PDF 页，将匹配区域置于 PDF 视口中央；放大后可按住 PDF 内容拖拽平移视图。知识问答运行时不会持有 PDF/翻译共用的长时锁；PDF 标签隐藏后暂停状态轮询，恢复时保持原页码并重新检查当前页缓存。缓存位于 `user-data/<TASK_ID>/translations.sqlite3`（需要兼容旧工具时可用 `restore.sh` 恢复为目录）。左侧项目栏可通过页面左上方的 `‹/›` 按钮收起或展开，状态会在浏览器本地保存。

左侧文档列表中的 `☆` 可设置个人重要性（1–5 分，5 分最高），再次点击 `★分数` 可以修改或清除。
“我的重要性”支持查看全部文档、4–5 分的优先复习文档或所有已评分文档；筛选时自动展开匹配的分组。
评分以文档路径为标识，保存在当前任务的 `state.sqlite3` 中，独立于正文、阅读进度和站点构建；同一本地服务的不同浏览器共享评分。
`GET /api/document-importance` 读取评分，`POST /api/document-importance` 接受 `document_id` 与 `score`（1–5，0 清除），沿用来源及 `X-Reader-Token` 校验。

阅读工作台默认同时显示文档正文、PDF 和译文三栏，右侧通过同一行工具栏切换“解析、译文、知识问答、研究笔记”。重复点击当前入口收起右栏；右上角“布局”分段按钮可一次点击切换单栏、双栏、三栏，当前布局高亮，单栏恢复精读正文位置，三栏恢复上次右栏内容。四个入口使用简洁文字与细下划线，右栏以浅底色和分隔线适度区分，解析、译文和问答的模型参数统一在右栏标题下折叠显示，选择参数后保持展开，由用户手动收起。两条分隔线可分别拖动或用方向键调宽，双击复位；文档宽度和 PDF/右栏比例独立记忆。切换保留 PDF 阅读点、右栏滚动位置和问答草稿。PDF 栏内的专属工具栏可翻页、缩放、搜索和选择原文，不占用三栏共享导航。

对运行中的服务执行 `./.venv/bin/python tests/test_reader_studio.py` 可验证 PDF 专属工具栏、设置手动收起、四栏切换、阅读点/草稿恢复、返回正文和窄窗口布局。解析缓存请求使用测试数据，测试不会调用模型或修改聊天记录。

## 当前页知识解析

解析围绕当前页通常输出 2～4 个关键观点，默认先看动机、核心认识和适用范围，并区分实验观察、条件性证明、方法设计、作者假设/主张与背景知识。默认阅读层以约 300～600 中文字为目标，解释与推导手动展开；保留原文定位。请求同时附上当前页与前后各两页的原始 PDF 图片及带物理页码的文本（文档边界自动裁减），只有当前页用于生成解析块和区域。点击位置标签可框选原文：模型估计的归一化图像区域须经 PDF.js 文本锚点核对，失败则回退到摘录位置，不宣称像素精确。跨栏单元可使用多个框。

在右栏标签中打开“解析”，选择模型、推理强度，再点击“解析本页知识”。只有这个按钮会触发模型调用；打开面板、停留和翻页都不会自动生成。已有结果可“重新解析”，失败时保留旧结果。解析与译文、聊天记录独立，模型选择分别保存在浏览器中。侧栏支持拖拽调整宽度和双击复位。

知识解析复用下述 Responses 端点和认证配置，必带当前页原始 PNG 和文本层，并提供前一页最多 14000 字、后一页最多 10000 字、首页最多 6000 字，以及邻近前文最多 32000 字（至多回溯 13 页）。辅助文本标记物理页，不冒充本页证据。每次解析携带服务端当日日期、时区和论文发表时间。“放到今天怎么看”独立说明当代知识背景；具体后续研究用 Responses web_search 核验，链接须与 API 返回的搜索来源/引用相符，缺失或不匹配的来源不能冒充核验成功。搜索不受支持时回退到本页解释，并明确标注后续研究未核验。搜索接口参考 [OpenAI Docs](https://developers.openai.com/api/docs/guides/tools-web-search)。

提示词在 [`prompts/page-insight.md`](prompts/page-insight.md)，输出契约在 [`schemas/page-insight.schema.json`](schemas/page-insight.schema.json)。调整任一文件后旧版结果失效。缓存存入 `state.sqlite3` 的逻辑 `page-insights/` 路径，按 PDF 内容哈希、物理页、模型、推理强度、阅读日期和提示词/契约哈希区分；跨日须手动重新生成，避免把旧结果当作当日核验。

`GET /api/pdf/page-insight?source_id=...&page=...&model=...&reasoning_effort=...` 只读缓存；`POST /api/pdf/page-insight` 使用相同字段生成，`force: true` 重新生成。POST 需要与其他 Reader 操作相同的来源和 `X-Reader-Token` 校验。默认使用 `gpt-6.1-sol / medium`，模型和推理强度沿用服务现有的允许列表。

知识问答和“AI 修订”通过本机 Codex CLI 调用，复用 `codex login` 的认证状态与当前
`~/.codex/config.toml` provider；修订使用临时会话和 JSON Schema，不把 Codex 凭据复制到 Reader。
所有通过 Codex CLI 新建或恢复的会话使用 `--dangerously-bypass-approvals-and-sandbox`，关闭 Codex 沙箱和权限确认，
允许命令联网、读写文件及执行程序；实际权限由运行 Reader 的系统账号决定。
PDF 翻译是独立的无状态 Responses API 管线，仍按下述端点匹配规则读取专用凭据。

右侧使用固定在 `reader/content/vendor/` 的本地 PDF.js，不依赖浏览器内置 PDF Viewer。MathJax 与字体同样已本地化，阅读时不会向 CDN 请求资源。

## 知识问答与固化

「论文问答」统一使用全文探查逻辑（兼容旧对话）：针对当前打开的 PDF，一次提交多个问题或想法，Codex 按需搜索并读取完整分页文本（包含附录），逐项给出解释、查阅范围及原文证据。回复中的 `[证据N]` 显示为带页码的行内高亮标签，点击跳转 PDF 物理页并保留问答面板；悬停可查看原文摘录，不再展开证据卡片。历史回复未标注位置的引用以紧凑标签补在文末。后端按 PDF SHA-256 缓存分页文本，并核对引用的物理页和连续原文；无法核验的引用不提供跳转。引用支持章节/公式/图表编号；点击后使用已核验摘录匹配 PDF 文字层并逐行框选，跨行连字符与常见连字会归一化。无法唯一匹配时仅跳页并明确提示，不做模糊框选。扫描 PDF 无可靠文本时提示先进行 OCR，目前不自动 OCR。

论文问答使用原有模型配置，以独立临时 Codex 进程运行并携带最近对话；结果保存在当前对话，可刷新恢复。联网搜索使用 `web_search="live"`，本论文证据、外部来源和推断须分开说明。搜索配置参考 [OpenAI 官方文档](https://developers.openai.com/codex/config-reference/)。长任务可能需要几分钟，目前展示等待状态而非实时工具日志。回归测试：`reader/.venv/bin/python reader/tests/test_paper_exploration.py`（隔离用户数据，不调用模型）。

PDF 框顶部的“本页问过”随物理页切换，展开可点击历史问题，定位到原对话并高亮该问题；“有问题的页”可直接跳到讨论过的页面。关联涵盖当前精读文档的全部对话（包括归档），删除对话后同步移除。只统计实际附加了该页 PDF 图像的问题，纯文本追问和仅记录阅读位置的问题不计入。索引实时从保存的记录生成，刷新后保留；读取和跳转不会调用模型。

知识问答、AI 修订、页面解析和 PDF 翻译只提供 `gpt-6-astra` 和 `gpt-6.1-sol`，默认使用 `gpt-6.1-sol`。旧模型设置在读取时回退到默认模型，已保存的 Astra 选择继续沿用。各设置框旁显示“模型名称”和“推理强度”。
两个模型均提供 `low/medium/high/xhigh/max`，旧设置中的 `ultra` 在读取时归一为 `max`；新请求不接受 `ultra`。
模型名称与推理强度参考 OpenAI Docs 的 [GPT-6.1 Sol](https://developers.openai.com/api/docs/models/gpt-6.1-sol) 和 [Astra](https://developers.openai.com/api/docs/models/gpt-6-astra) 页面。

`./serve.sh` 会启动只监听 `127.0.0.1:8000` 的本地动态服务，并调用本机已经登录的 Codex CLI。网页不会读取、复制或显示 Codex 凭据。

- 每份综合报告/专题精读可以保留多个独立 Codex 对话；同一时间只有一个对话可继续调用。
- 知识问答以当前论文和本地调研内容为证据基线；遇到最新状态、官方 API、源码实现或相关论文问题时，会按问题需要使用可用的联网、搜索、浏览器和 MCP 工具，并在回答中标明外部来源。
- 新建对话不会自动归档之前的对话，未归档对话可随时切回继续；只有主动点击“归档”才变为只读历史。刷新或退出后仍可切换查看所有历史对话。
- Codex 调用失败时，本轮问题和失败状态也会保存在当前对话中，不会因页面与底层 Session 状态分叉而丢失。
- 在正文的一个段落内选择文字，会出现“加入知识问答上下文”；后端使用块 ID、字符偏移和构建哈希重新验证选区。
- 选择“AI 修订”后只需用自然语言描述修改目标，系统直接生成一份可审阅的正文候选，不再对修改意图额外分类。需要完全控制文本时使用“手动修改”。
- AI 修订显示在右侧面板，生成期间仍可滚动、选择和阅读原文；点击“收起”可保留请求与草稿。候选返回后在面板提示，不自动展开或跳转阅读位置，点击“展开”查看并继续追问。
- 技术追问默认按“明确回答、机制、具体例子、适当图解、可核验依据与边界”展开。后端传入选区的章节路径、所属章节（含表格/代码）、有界的文章正文及固定来源清单；源码问题要求主动查原始实现，不能只复述原段落。纯措辞修改仍保持用户指定范围。
- 修订提示词在 [`prompts/document-revision.md`](prompts/document-revision.md)，每次请求读取，修改该文件无需重启。正文上限为 24,000 字符（不是目标字数），交互图仍使用隔离的 `visual_html`。候选记录提示词哈希、上下文策略版本与截断情况，连续追问保留先前正文和图解。无效 JSON/图结构会自动尝试一次格式修复，保留已有讲解；再次失败则明确报错。上下文组装见 [`revision_context.py`](revision_context.py)，回归测试为 `tests/test_revision_context.py`。
- “加入当前 PDF 页图像”只发送来源 ID 与物理页；后端从固定 PDF 渲染完整 PNG，通过 Codex CLI 的 `--image` 加入当前会话，不信任前端文件路径或标题。
- 每轮视觉问答会附带精读文档标题/路径/哈希，以及论文标题、作者、官方记录、固定来源 ID、PDF 哈希和页码信息；这些元数据均从只读任务目录生成。
- 页面图像只存在于系统临时目录，Codex 返回或调用失败后都会自动删除，不进入仓库或运行时数据库。
- PDF 页面附件每次发送后即从输入区消耗；历史消息使用本地 PDF.js 按固定来源和物理页重新绘制缩略图，不会在下一轮自动重复发送。
- 每条助手回答可由用户主动保存为“研究笔记”（原 FAQ）；保存前可编辑标题、核心结论和个人备注，固化后在当前文档末尾的“我的个人备忘录”中默认折叠显示。个人 FAQ 由运行时加载，不再拼进生成后的 Markdown 或正文目录；系统也不会自动从整段对话发现候选。
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

AI 修订在生成期间显示模型处理阶段、已等待时间及最近活动时间。修订生成与格式修复共用30分钟等待上限；超时会显示明确错误并保留输入，允许重试。进度连接短暂中断不会重新提交问题，也不会中断正在生成的回答。
任务中的 canonical PDF 和论文 Markdown 保持普通文件；非 PDF 来源工件、已完成 handoff、历史 run 和 work
中间件可保存在 `tasks/<TASK_ID>/artifacts.sqlite3`。Reader 会按原逻辑路径直接查询该数据库。

翻译端点默认读取 `$CODEX_HOME/config.toml`（未设置时为 `~/.codex/config.toml`）中当前
`model_provider` 的 Responses 配置，并使用其 `base_url + /responses`。代码中不内置备用 API URL；
配置缺失、无效或当前 provider 不是 `wire_api = "responses"` 时，直连翻译会返回明确的配置错误。
每次无状态请求前都会重新读取 provider 与 Key，因此运行中切换 Codex 端点或轮换 API Key 也会自动生效。
常规翻译默认使用 `gpt-6.1-sol` 和 `medium` reasoning effort。
重新翻译会忽略缓存，默认使用 `gpt-6.1-sol` 和 `high`；也可在译文栏切换到允许的模型与推理强度。翻译采用文本层确定覆盖范围、页面图像校准
公式与版面的双源流程，并在保存前复核易错数学符号。

当 Reader 的 Responses URL 与本机 Codex 当前 provider 的 `base_url + /responses` 精确匹配时，
Reader 会按 provider 的认证方式读取 Codex `auth.json` 中的 `OPENAI_API_KEY`，或读取 `env_key` 指定的
环境变量。端点不匹配时不会转发该凭据，必须显式配置
目标端点自己的 `READER_TRANSLATION_API_KEY`。
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

- 阅读工作台顶栏由 `overrides/partials/reader-studio.html` 直接生成，页面解析时恢复本标签页的栏数和工具选择，前端脚本只绑定交互。文档切换保留整页导航，确保 PDF 和问答上下文随文档重新初始化；不要单独启用 `navigation.instant`，其文档状态生命周期尚未适配。可用 `.venv/bin/python tests/test_reader_navigation.py http://127.0.0.1:8000` 验证延迟脚本时的首屏和布局恢复。
- [`design/nature-reader-adoption.md`](design/nature-reader-adoption.md)：记录从开源 `nature-reader` 借鉴的块级双语、source map、术语账本和图表证据设计，以及本地不采用的范围和分阶段验收条件。第一阶段的块级翻译、稳定页内 ID 和 source map 已实现；图表裁剪与块级问答引用仍在后续阶段。
