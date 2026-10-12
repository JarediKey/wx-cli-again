# 聊天记录导出与 Codex Skill

[English](chat-export.md)

仓库根目录提供 `wx-cli` Skill，支持定位会话、按精确时间读取历史、总结和离线导出。
说明使用本公开 fork 和 macOS 临时副本初始化流程。已有有效密钥会直接复用，
普通查询不会触发重新初始化。

## 安装

使用 Codex 的 Skill Installer，将本仓库根目录安装为名为 `wx-cli` 的 Skill。
安装器将说明、脚本、模板和源码资源复制到 `~/.codex/skills/wx-cli`
（或 `$CODEX_HOME/skills/wx-cli`）。下一轮对话即可使用。
可以显式输入 `$wx-cli`，也可以自然语言要求查询、总结或导出微信记录；自动识别保持开启。

CLI 应已安装并初始化。完整导出还需要从同一份源码构建只读辅助程序：

```bash
cargo build --release --locked --example archive-data
install -m 755 target/release/examples/archive-data ~/.local/bin/wx-archive-data
```

需要 Python 3.9+。FFmpeg 用于 HEVC 图片预览及 MP3 输出，
可选的 `pilk` 用于解码本地 SILK 语音。macOS 安装示例：

```bash
brew install ffmpeg
/usr/bin/python3 -m venv ~/.local/share/wx-cli-skill/venv
~/.local/share/wx-cli-skill/venv/bin/python -m pip install pilk
```

没有可选解码器时，仍保留原始媒体文件，并在导出中说明预览限制。
安装 Skill 不会下载语音模型，也不会把媒体上传到外部转录服务。

## 使用

在已安装的 Skill 目录或源码目录运行：

```bash
~/.local/share/wx-cli-skill/venv/bin/python scripts/export_chat.py \
  --chat "项目群" --hours 24 --timezone America/Los_Angeles \
  --out "$HOME/Downloads/wechat-project-export"
```

时区应使用用户实际选择。`--hours` 从一个固定结束时间减去对应的真实小时数。
要重用之前总结的精确范围，传入包含端点的 `--start` 与 `--end`，支持 Unix 秒或
ISO 时间。`--all` 选择本机全部可读取历史。夏令时重复或不存在的本地时间，
必须明确提供 UTC 偏移。输出目录必须是新目录。

脚本从会话和联系人中定位唯一聊天，扩大查询条数直至完整覆盖时间范围，
并匹配从同一聊天加密消息表读取的原始字段。它不会输出数据库密钥。产物包括：

- `chat.html`：离线阅读版，支持搜索、发送者和日期筛选，直接嵌入图片、语音和可下载文件。
- `chat.txt` 与 `messages.json`：完整文本，以及查询结果和原始字段。
- `attachments/`：本地图片、语音、文件的原始格式与可生成的预览。
- `manifest.json`：文件大小、SHA-256、附件状态和完整性提示。
- 旁边的 `.zip`：包含整个导出目录。

图片通过 `wx attachments` / `wx extract` 提取；语音使用保留的服务端消息 ID，
通过 `wx media voice` 导出。共享文件仅在本机已有匹配文件时复制，
同名但内容不同的文件会报告歧义，不会猜选。
缺失密钥和无法唯一匹配的原始记录会明确提示。
表情保留消息记录，不含表情图片；无法恢复撤回、已删除正文或从未下载过的附件。

导出应放在源码和已安装 Skill 目录之外。以本地文件方式打开 HTML。
导出脚本不包含 HTTP 托管、云端上传或外部媒体请求。
已安装的 Skill 是一份副本；更新 fork 后，如果辅助程序有改动，应重新编译，
并重新安装 Skill，才能获得新的说明和脚本。

## 验证

```bash
cargo check --locked --examples
python3 -m unittest discover -s tests -p 'test_chat_export.py' -v
```

合成测试覆盖群名歧义、条数上限处同秒消息、夏令时边界、不可信文件名、
HTML 内容转义、媒体嵌入、完整性提示和 ZIP 校验。
原始字段辅助程序和完整导出脚本也经过已授权本地时间范围的实测。

完整媒体导出的实测范围为 macOS 27.0.1 与微信 4.1.15 build 270102。
本机缺少 Linux/Windows Rust 目标工具链，尚未完成这些平台的编译验证。
