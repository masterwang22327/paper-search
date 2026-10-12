# 在新电脑恢复完整论文阅读服务

GitHub 保存服务代码：[masterwang22327/paper-search](https://github.com/masterwang22327/paper-search)。
ModelScope 的私有数据集保存完整快照：[masterwei22327/paper_reader](https://modelscope.cn/datasets/masterwei22327/paper_reader)。
只克隆 GitHub 不会带回个人资料；需要下载私有快照。

快照包含代码副本、全部任务及来源 PDF、归档源码和证据、研究历史、Reader 的三个数据库、
已保存的问题/回答、知识笔记、正文修订、阅读位置、重要性评分、页面解析和译文缓存，以及这些对话引用的
Codex 会话文件。它保留相对路径、文件权限和纳秒级修改时间。SQLite 使用在线备份接口生成一致副本。
`LATEST.json` 指向最近一次完成的备份；历史快照不会因上传新版本被删除。

API 密钥、登录 Cookie、认证文件和旧电脑的虚拟环境不在快照中。Codex 历史文本里的密钥形态字符串
会在备份副本中脱敏。新电脑需要自己的 ModelScope 访问令牌，并为新的 AI 请求配置凭据；
已有笔记、历史问题和缓存译文可以直接阅读。浏览器本地的主题、分栏宽度、未提交草稿等不会跨电脑迁移。

## 1. 安装基础环境

支持 macOS 和 Linux；Windows 使用 WSL2，按 Linux 步骤操作，然后在 Windows 浏览器打开服务。
需要 Python 3.11+、Git、Node.js（建议 22+）、Poppler，以及 Chrome、Edge 或其他现代桌面浏览器。

macOS（已安装 Homebrew）：

```bash
brew install python@3.13 node poppler git
npm install -g @openai/codex@0.162.0
```

Ubuntu / WSL2（以下 Python 版本适用于 Ubuntu 24.04；其他发行版安装 Python 3.11+）：

```bash
sudo apt update
sudo apt install python3 python3-venv git poppler-utils
# 安装 Node.js 22+ 后：
npm install -g @openai/codex@0.162.0
```

检查环境：

```bash
python3.13 --version  # Linux 可使用达到 3.11+ 的 python3
codex --version
pdftocairo -v
pdfinfo -v
pdftotext -v
```

Codex 固定为创建这次备份时使用的版本，减少历史会话格式变化；以后可在验证后升级。

## 2. 克隆代码并下载私有备份

```bash
git clone https://github.com/masterwang22327/paper-search.git
cd paper-search
python3.13 -m venv .backup-venv
.backup-venv/bin/python -m pip install -r tools/requirements-backup.txt
```

Linux 将上述 `python3.13` 换成 Python 3.11+ 的 `python3`。
macOS 若 pip 提示证书链错误，可设置 `export PIP_CERT=/etc/ssl/cert.pem` 后重试；保持证书验证开启。

在 ModelScope 的访问令牌设置页面创建或获取有权读取该私有数据集的令牌，然后在当前终端输入：

```bash
read -r -s MODELSCOPE_API_TOKEN
export MODELSCOPE_API_TOKEN
.backup-venv/bin/python tools/reader_backup.py restore --repo-dir "$PWD"
unset MODELSCOPE_API_TOKEN
```

执行 `read` 后粘贴令牌并按回车，输入不会显示，也不需要把令牌写进命令或仓库。
`restore` 下载 `LATEST.json` 指定的四个压缩包，校验 SHA-256 后恢复。
代码与已有文件内容相同才会写入；遇到不同的文件会停止，以保护更新过的个人数据。

若 GitHub 的最新版比备份更新，或者目标目录已有不同文件，可以先恢复到空目录，再在那边启动：

```bash
.backup-venv/bin/python tools/reader_backup.py restore --repo-dir ../paper-reader-restored
cd ../paper-reader-restored
```

恢复指定历史版本：

```bash
.backup-venv/bin/python tools/reader_backup.py restore \
  --snapshot-id <ModelScope-backups目录里的版本名> --repo-dir ../reader-history
```

## 3. 配置 AI 并启动

恢复工具把对应的 Codex 会话放到 `.reader-codex/`，同时生成不含密钥的 provider 配置。
`reader/serve.sh` 自动使用这个独立目录；不会覆盖你其他 Codex 会话和配置。
对于当前备份的自定义 Responses provider，配置使用环境变量 `READER_AI_API_KEY`：

```bash
read -r -s READER_AI_API_KEY
export READER_AI_API_KEY
./reader/serve.sh paper-research-base-knowledge-about-llm-20260717
```

浏览器打开 <http://127.0.0.1:8000>。首次启动安装锁定的 Reader 依赖；已有站点可复用，
输入发生变化时只重建展示站点，不会清空问题、笔记、修订或译文。
如果只阅读历史记录，可以暂不设置 `READER_AI_API_KEY`；新的模型请求需要有效凭据。
若使用官方账号登录，先调整 `.reader-codex/config.toml` 的 provider，再运行
`CODEX_HOME="$PWD/.reader-codex" codex login`。

服务启动器会自动寻找 Python 3.11+，也可以通过 `PYTHON_BIN=/path/to/python3.13` 明确指定。
AI 修订和问答沿用当前服务的 Codex 权限模式；需要 MCP 浏览器时，应在新电脑单独安装和配置，
旧电脑的 MCP 绝对路径不会复制进 provider 配置。

## 4. 验证记录

打开一份以前问过问题的论文，检查“知识问答”的历史对话、“研究笔记”、
“本页问过”、阅读位置、重要性评分和已有译文。数据库内容应与快照一致。
恢复清单保存在 `.reader-backup/manifest.json`，其中记录代码提交、所有文件哈希和备份时间。
重开终端时需要重新提供 AI 密钥，或通过自己的密钥管理方式注入环境变量。

## 后续备份

先提交当前服务代码，再生成新快照。上传工具只接受私有 ModelScope 数据集：

```bash
python3.13 tools/reader_backup.py snapshot --output ../backups/<唯一版本名>
.backup-venv/bin/python tools/reader_backup.py upload --snapshot-dir ../backups/<唯一版本名>
```

上传前在当前终端设置 `MODELSCOPE_API_TOKEN`。文件内容有变更会生成新的快照；
失败的上传可以对同一个快照重新执行，SDK 保留续传状态。
大约需要数 GiB 的下载空间，以及恢复目录所占空间；建议预留 10 GiB 以上。
