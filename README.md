# Paper Search

这是一个面向长期个人知识沉淀、证据可追溯论文调研的 Codex CLI 工作区。`TASK_ID` 由用户声明并标识
唯一的报告、来源树、精读文档与 Reader 知识库；当前关注方向、追问和学习目标可以在同一 ID 下持续
变化。使用方式只有一个：修改
[`VIBE_RESEARCH_PROMPT.md`](VIBE_RESEARCH_PROMPT.md) 的用户配置区，将完整 Prompt 粘贴到新开的
YOLO 模式 Codex CLI，按一次 Enter。

## 公开仓库边界

仓库跟踪控制代码、研究规范、个人学习画像、Reader 源码和已审核的共享 `library/`。以下内容只属于
本机运行状态，不会进入 Git：

- `tasks/`：长期研究任务、下载来源和报告正文；仓库只保留 `tasks/.gitkeep`；
- `reader/user-data/`：聊天、Codex Session、FAQ、修订和翻译缓存；
- `reader/docs/`、`reader/site/`：Reader 的生成目录；
- `reader/.venv/`：本地 Python 环境；
- `.env*`、认证 JSON、私钥和证书。

个人学习画像 [docs/learning-profile.md](docs/learning-profile.md) 是有意公开并纳入版本控制的长期配置。
其他个人内容进入仓库前应先做单独审查。凭据处理和泄漏后的处置见 [SECURITY.md](SECURITY.md)。

## 环境要求

- Python 3.11 或更高版本；
- 已安装并登录的 Codex CLI；
- 元数据校验需要 PyYAML 和 jsonschema；
- Reader 需要 Poppler 的 `pdftocairo`、`pdfinfo`、`pdftotext`；浏览器回归测试需要 Chrome 或 Edge。

```bash
git clone https://github.com/masterwang22327/paper-search.git
cd paper-search
python3 -m pip install 'PyYAML>=6.0' 'jsonschema>=4.0'
```

## 一次启动

首次使用时，先把 `VIBE_RESEARCH_PROMPT.md` 中的 `REPOSITORY_ROOT` 改为当前仓库的绝对路径。然后在
仓库根目录启动你平时使用的 YOLO 模式，并开启实时搜索：

```bash
cd /path/to/paper_search
codex --dangerously-bypass-approvals-and-sandbox \
  --search \
  --enable goals
```

然后：

1. 打开 `VIBE_RESEARCH_PROMPT.md`。
2. 只有你决定新建知识库时才修改 `TASK_ID`；每次可按当前关注更新 `RESEARCH_QUESTION`、长期学习目标、
   用户画像和其他课题级配置。
3. 复制代码块中的完整 Prompt，粘贴到 Codex，按一次 Enter。

`--enable goals` 用于显式启用持久 Goal，避免依赖不同 Codex CLI 版本的默认开关。

Prompt 会让 Codex 为每个 run 创建一个持久 Goal。Goal 负责本次有界执行的自动续回合；任务文件负责
跨 run、上下文压缩或意外中断后的长期恢复。`TASK_ID` 标识长期知识库，`RUN_ID` 与 Goal 共同标识一次
不可变的截止/Token 合同。

## 下次运行改什么

| 参数 | 默认值/默认行为 | 新课题/新 run 怎么处理 |
| --- | --- | --- |
| `TASK_ID` | 当前 LLM 知识库 ID | **只有用户决定新建知识库时修改**；Agent 不会因方向变化派生新 ID |
| `RESEARCH_QUESTION` | 当前 LLM 基础与代表工作 | 同一 ID 下可随关注点补充、收窄、转向或重写 |
| 长期学习目标、用户画像 | NLP/LLM 知识沉淀、工程理解与面试能力 | 新追问或偏好出现时长期维护并保留历史 |
| 范围、排除、交付、完成证据、种子来源 | 当前完整调研约束 | 按当前阶段更新，不改变知识库身份 |
| `HARD_DEADLINE` / `RUN_DURATION_DAYS` | `AUTO` / `1` 天 | 每个新 run 确认；活跃 run 不能改，终止后可设新值 |
| `GOAL_TOKEN_BUDGET` | `200000000` | 每个 run/Goal 独立；活跃 run 不能改 |
| 外部额度阈值/检查/等待参数 | `$1` / `20` 分钟 / `60` 秒 | 通常不改 |
| 仓库、语言、深度、并行策略 | 当前仓库 / 中文 / deep / auto | 通常不改 |

除首次使用必须设置的 `REPOSITORY_ROOT` 外，其他配置都有明确默认值，不会因残留 `[必填]` 占位符而
停下。恢复活跃 run 时不要修改它的
截止与 Token 合同，`AUTO` 会复用固化的绝对截止，不会在重启时偷偷延长；当前关注、画像或学习目标
仍可更新并追加到任务历史。旧 run 终止后同 TASK_ID 再用 `AUTO`，会原地创建一个新的一天 run/Goal。

## 什么时候停止

每个 run/Goal 的自动终止阈值只有：

- 到达该 run 固化的绝对截止时间（`HARD_DEADLINE=AUTO` 时默认为 run 创建后 1 天）；
- Codex Goal 的产品级 Token 预算自然耗尽；

你仍可明确取消当前 run 或整个长期知识库；这是用户控制命令，不是第三个自动阈值。初稿完成、当前
关注变化、普通阻塞和外部每日额度不足都不会自动终止 run。

`GOAL_TOKEN_BUDGET` 是当前 run 的 Codex Goal 总采样 Token 上限，用于自动续回合，预算用尽时当前
Goal/run 会结束；截止到达时也会封存该 run 并结束绑定的 Goal。下一时段用同一 `TASK_ID`、新的截止和
Token 预算创建 continuation run/Goal，继续写唯一知识库。它与
`check_token.py` 查询的 nf.video 今日 Token/美元额度不是同一个概念。产品级 Goal Token 预算如果先
耗尽，Codex 无法继续自动回合，但必须留下断点；下一 run 可有新预算，这不能被伪装成研究完成。

截止时间与外部额度由 [`tools/research_runtime.py`](tools/research_runtime.py) 在每个有界工作单元前
检查。外部额度的新鲜快照降到阈值时返回 `WAIT_QUOTA`，不会结束 Goal：Agent 先保存断点，再运行
低资源等待器；北京时间次日 `00:00` 后强制刷新，恢复额度便继续研究，仍不足则等到再下一个午夜。
等待期间如果先到总截止时间才返回 `STOP_DEADLINE`。监控失败不等于额度耗尽。

这里的“后台等待”是从研究任务角度暂停：等待器在同一个 Codex 会话中运行，不做搜索，也不消耗
论文调研调用。为了让原会话在午夜后可靠续接，Terminal/Codex 进程必须保持运行，所以不会用 `&` 或
`nohup` 把等待器脱离会话。

## 文件结构

```text
paper_search/
├── VIBE_RESEARCH_PROMPT.md       # 唯一需要编辑和粘贴的长 Prompt
├── docs/
│   ├── research-standard.md      # 来源、证据、调研循环和保存协议
│   ├── learning-profile.md       # 你的知识背景和个性化讲解要求
│   ├── research-roadmap.md       # 人工选题参考，不会自动扩张当前任务
│   └── library-index.md          # 共享资料索引
├── tools/
│   ├── research_runtime.py       # 创建课题、恢复/续建 run，检查截止时间和外部额度
│   └── validate_library.py       # 候选入库元数据校验
├── templates/
│   ├── review.md                 # 深度单篇精读纲要
│   └── metadata.yml              # 候选入库元数据模板
├── schemas/paper.schema.json
├── reader/                      # 本地 MkDocs/PDF 阅读器与知识问答服务
├── tasks/<task-id>/              # 每个长期课题唯一工作区，可包含多个 run
├── library/                      # 已审核共享知识；普通调研只读
├── reading_queue/inbox.md
└── SECURITY.md                   # 凭据、隐私目录和安全报告约定
```

任务目录由 Prompt 自动创建：

```text
TASK.md                            # 当前长期目标、画像、关注问题与课题级配置
TASK_HISTORY.md                    # 关注方向、需求和画像的追加式版本历史
STATUS.md                          # 当前进展、队列、守卫结果和下一步
REPORT.md                          # 持续整合的最终报告
SOURCES.md                         # 稳定 ID、版本、证据位置和本地路径
RUN_HISTORY.md                     # 所有不可变 run 合同和终止记录
papers/                            # 重要论文的单篇笔记
sources/                           # PDF、文本、元数据和工件证据
state/current-run.json             # 当前 RUN_ID 指针
state/runtime.json                 # 兼容指针；真实状态位于 run 目录
state/runs/<run-id>/runtime.json   # 当前 run 的截止/Goal/额度控制状态
state/runs/<run-id>/quota.json     # 当前 run 最近一次外部额度快照
state/runs/<run-id>/events.jsonl   # 当前 run 守卫决策记录
state/handoffs/                    # 可选原生 subagent 交接
```

旧格式任务第一次执行 `init`、`status`、`gate` 或 `validate` 时会自动迁移 runtime/quota/events；原有
REPORT/SOURCES/papers/sources 不移动、不复制。旧 TASK.md 中可能残留的首 run 截止/预算只作历史快照；
新 run 以 RUN_HISTORY.md 和 `state/runs/<run-id>/runtime.json` 为准。

## 人工查看

无需进入 Codex 即可查看一个任务：

```bash
python3 tools/research_runtime.py status <task-id>
python3 tools/research_runtime.py validate <task-id>
sed -n '1,220p' tasks/<task-id>/STATUS.md
```

手动刷新外部额度和下一步决策：

```bash
python3 tools/research_runtime.py gate <task-id> --force-quota
```

手动进入与 Prompt 相同的跨天等待（一般无需人工执行）：

```bash
python3 tools/research_runtime.py wait-quota <task-id> --poll-seconds 60
```

守卫会尝试调用仓库父目录中的私有 `check_token.py`。该文件和额度认证不属于公开仓库；缺失时运行时
会记录 quota monitor unavailable，但不会把“监控不可用”误判为额度耗尽。不要在两个 Codex 窗口中
同时使用同一个 TASK_ID。

用户明确取消当前 run 时可运行：

```bash
python3 tools/research_runtime.py close-run <task-id> --reason STOP_USER
```

产品明确报告 Goal Token 自然耗尽时使用 `STOP_GOAL_TOKENS`。该命令只关闭当前 run，不关闭长期课题。

## 启动 Reader

Reader 只读取已经存在的任务，因此必须明确传入 task ID：

```bash
./reader/serve.sh <task-id>
```

服务只监听 `http://127.0.0.1:8000`。详细的构建、翻译凭据和个人数据边界见
[reader/README.md](reader/README.md)。

## 约束与现实边界

- YOLO 模式意味着 Codex 有很高的本机权限，因此长 Prompt 明确限制了写入目录、凭据、来源指令、
  嵌套 Codex 和共享 library 写入。
- Goals 是当前 Codex 的持久目标/自动续回合能力。若客户端崩溃、电脑休眠、网络断开或产品预算耗尽，
  任何 Prompt 都无法保证进程继续；任务文件保证重新粘贴同一 Prompt 后可以恢复。
- 额度跨天恢复要求 Terminal、Codex CLI 和电脑保持运行；macOS 休眠会暂停进程，唤醒后等待器会重新
  检查硬截止和额度，但关闭 Terminal/CLI 后必须手动重启并粘贴同一 Prompt。
- 截止时间和 Goal Token 是当前 run “不能越过”的两个自动边界；以后续研新增 run/Goal，不改写旧合同，
  不分裂主报告，也不因关注方向变化派生任务 ID。

## 验证

```bash
cd /path/to/paper_search
python3 -m unittest -q
python3 -m py_compile tools/research_runtime.py tools/validate_library.py
```
