# Research Reader

该目录把 `../tasks/<TASK_ID>/` 中的只读调研成果生成成 MkDocs Material 阅读站。生成过程不会修改任务原稿。

## 本地阅读

```bash
cd /path/to/paper_search/reader
./serve.sh <task-id>
```

浏览器打开 <http://127.0.0.1:8000>。首次运行会在 `reader/.venv/` 安装隔离依赖。

专题精读在桌面宽屏下会自动显示右侧固定论文 PDF。点击正文中带 `PDF` 标记的页码引用，右侧面板会切换到对应论文和物理页；按住 Command/Ctrl 点击则保留普通链接行为，在新标签页打开。

PDF 工具栏支持“翻译当前页”和“翻译全文”。全文翻译只处理未缓存页面；译文面板中的“重译当前页”会忽略当前页缓存并重新调用一次翻译 API。翻译按物理页直接调用无状态 Responses API，不创建或续接 Codex Session；跨页一致性由本地 glossary 和相邻页摘录提供。译文与同一页原 PDF 左右对照，可拖动调整两栏宽度、显示提取原文进行核对；译文块使用“正文第 1 段”等自然标签，点击块会回查对应 PDF 页，并优先通过 PDF 文本层匹配原文区域。缓存位于 `user-data/<TASK_ID>/translations/`。左侧项目栏可通过页面左上方的 `‹/›` 按钮收起或展开，状态会在浏览器本地保存。

右侧使用固定在 `reader/content/vendor/` 的本地 PDF.js，不依赖浏览器内置 PDF Viewer。MathJax 与字体同样已本地化，阅读时不会向 CDN 请求资源。

## 知识问答与固化

`./serve.sh` 会启动只监听 `127.0.0.1:8000` 的本地动态服务，并调用本机已经登录的 Codex CLI。网页不会读取、复制或显示 Codex 凭据。

- 每份综合报告/专题精读可以保留多个独立 Codex 对话；同一时间只有一个对话可继续调用。
- 用户可把当前对话归档为只读历史，再新建一个干净的 Codex Session；刷新或退出后仍可切换查看所有历史对话。
- Codex 调用失败时，本轮问题和失败状态也会保存在当前对话中，不会因页面与底层 Session 状态分叉而丢失。
- 在正文的一个段落内选择文字，会出现“加入知识问答上下文”；后端使用块 ID、字符偏移和构建哈希重新验证选区。
- “加入当前 PDF 页图像”只发送来源 ID 与物理页；后端从固定 PDF 渲染完整 PNG，通过 Codex CLI 的 `--image` 加入当前会话，不信任前端文件路径或标题。
- 每轮视觉问答会附带精读文档标题/路径/哈希，以及论文标题、作者、官方记录、固定来源 ID、PDF 哈希和页码信息；这些元数据均从只读任务目录生成。
- 页面图像只存在于 `user-data/` 下的一次性临时目录，Codex 返回或调用失败后都会自动删除。
- PDF 页面附件每次发送后即从输入区消耗；历史消息使用本地 PDF.js 按固定来源和物理页重新绘制缩略图，不会在下一轮自动重复发送。
- 每条助手回答可由用户主动保存为 FAQ；保存前可编辑标题、核心结论和个人备注，固化后在当前文档末尾的“我的个人备忘录”中默认折叠显示。个人 FAQ 由运行时加载，不再拼进生成后的 Markdown 或正文目录；系统也不会自动从整段对话发现候选。
- 已固化 FAQ 可以逐条删除；JSON、Markdown、页面内容和删除审计会同步更新。

个人数据位于：

```text
user-data/<TASK_ID>/
├── sessions.json          # 文档 -> 多个对话线程与当前活动线程
├── chats/*.jsonl          # 旧版首个对话，兼容保留
├── chats/<DOC_KEY>/*.jsonl # 后续独立对话的聊天记录
├── faq/*.json             # FAQ 结构化数据
├── faq/*.md               # 可读备份
├── faq-history.jsonl      # 固化审计记录
└── translations/<SOURCE_ID>/
    ├── manifest.json      # 无状态翻译后端、模型与固定 PDF 版本
    ├── glossary.json      # 跨页术语表
    ├── source-map.json    # 按 PDF 版本固定的页/块/置信度映射
    ├── pages/*.json       # 逐物理页原文、译文与核对提示
    └── history.jsonl      # 翻译/重译审计记录
```

`user-data/` 已被 Git 忽略，也不会进入生成站点。原始 `tasks/` 文件始终只读。

翻译默认使用 `https://www.sevnx.one/v1/responses`、`gpt-5.6-terra` 和 `medium` reasoning effort。
“重译当前页”会忽略缓存，改用 `gpt-5.6-sol` 和 `high`。翻译采用文本层确定覆盖范围、页面图像校准
公式与版面的双源流程，并在保存前复核易错数学符号。

第三方翻译端点必须显式配置它自己的 `READER_TRANSLATION_API_KEY`。Reader 不会把通用
`OPENAI_API_KEY` 或本机 Codex `auth.json` 中的密钥发送给第三方域名；只有当
`READER_TRANSLATION_API_URL=https://api.openai.com/v1/responses` 时，才允许回退读取 OpenAI 凭据。
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
open site/index.html
```

`serve.sh` 和 `build.sh` 都要求显式提供 task ID，避免公开仓库意外绑定某个本机任务。

## 数据边界

- `../tasks/` 是唯一事实来源，脚本只读取它。
- `docs/` 是每次运行重新生成的阅读副本。
- `site/` 是 MkDocs 静态构建结果。
- PDF 优先以硬链接加入 `docs/`，失败时才复制；删除生成目录不会删除原始 PDF。
- 来源代码、模型、数据与中间运行文件不会执行。

## 回归测试

```bash
./test.sh
```

测试使用本机 Google Chrome 或 Microsoft Edge，不额外下载浏览器。它会验证 PDF 渲染、引用跳页、面板拖动、宽度持久化和无外部网络请求。

无法自动识别的引用可在 `citation-overrides.yml` 中人工校正；该文件只影响阅读副本，不修改原始研究 Markdown。

## 设计记录

- [`design/nature-reader-adoption.md`](design/nature-reader-adoption.md)：记录从开源 `nature-reader` 借鉴的块级双语、source map、术语账本和图表证据设计，以及本地不采用的范围和分阶段验收条件。第一阶段的块级翻译、稳定页内 ID 和 source map 已实现；图表裁剪与块级问答引用仍在后续阶段。
