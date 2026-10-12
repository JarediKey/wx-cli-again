# Chat export and the Codex Skill

[简体中文](chat-export.zh.md)

The repository root contains the `wx-cli` Skill. It supports conversation lookup,
exact-time history reads, summaries, and offline archives. Its instructions use
this public fork and the macOS temporary-copy bootstrap. Existing working keys
are reused; a normal query does not trigger initialization.

## Install

Install the repository root as the skill named `wx-cli` with Codex's Skill
Installer. It copies the skill, scripts, template, and source resources into
`~/.codex/skills/wx-cli` (or `$CODEX_HOME/skills/wx-cli`). It becomes available on
the next turn. Invoke it explicitly as `$wx-cli`, or ask naturally for WeChat
chat history, summaries, or exports. Automatic selection remains enabled.

The CLI must already be installed and initialized. For full archives, build its
read-only companion from the same checkout:

```bash
cargo build --release --locked --example archive-data
install -m 755 target/release/examples/archive-data ~/.local/bin/wx-archive-data
```

Python 3.9+ is required. FFmpeg provides HEVC image previews and MP3 output. The
optional `pilk` package decodes local SILK voice data. On macOS:

```bash
brew install ffmpeg
/usr/bin/python3 -m venv ~/.local/share/wx-cli-skill/venv
~/.local/share/wx-cli-skill/venv/bin/python -m pip install pilk
```

Without optional decoders, original media files are preserved and preview
limitations appear in the export. Installing the skill does not install model
weights or upload media for transcription.

## Use

From the installed skill directory or a source checkout, run:

```bash
~/.local/share/wx-cli-skill/venv/bin/python scripts/export_chat.py \
  --chat "Project group" --hours 24 --timezone America/Los_Angeles \
  --out "$HOME/Downloads/wechat-project-export"
```

Use an actual timezone for the user. `--hours` subtracts elapsed hours from one
fixed end timestamp. For a previous summary's exact range, pass inclusive
`--start` and `--end` as Unix seconds or ISO timestamps. `--all` selects all locally
available history. Local times that fall in a daylight-saving overlap or gap
require an explicit UTC offset. The output directory must be new.

The exporter resolves a unique chat through sessions/contacts, expands the query
limit until the time window is complete, and matches raw fields read from the
same chat's encrypted message tables. It never exposes database keys. It writes:

- `chat.html`: offline reader with search, sender/date filters, images, audio,
  and downloadable files embedded directly in the HTML.
- `chat.txt` and `messages.json`: complete text and structured query/raw records.
- `attachments/`: original local image/voice/file attachments and available previews.
- `manifest.json`: file sizes, SHA-256 checksums, attachment status, and coverage warnings.
- A sibling `.zip` containing the full directory.

Images use `wx attachments` / `wx extract`. Voice uses its preserved server ID
with `wx media voice`. Shared files are copied only when a matching local file
exists; ambiguous names with differing content are reported, not guessed.
Missing keys or raw-record ambiguities are shown explicitly. Stickers preserve
message records without sticker images. Recalled/deleted content and attachments
that were never downloaded cannot be reconstructed.

Keep exports outside source and installed-skill directories. Open the HTML as a
local file. No local HTTP service, cloud upload, or external media request is
part of the exporter. Previously installed skills are copies; after updating
this fork, rebuild the companion if it changed and reinstall the skill to pick
up new instructions and scripts.

## Validation

```bash
cargo check --locked --examples
python3 -m unittest discover -s tests -p 'test_chat_export.py' -v
```

Synthetic tests cover ambiguous group lookup, same-second messages at a query
limit, daylight-saving boundaries, untrusted filenames, escaped HTML content,
media embedding, coverage warnings, and ZIP integrity. The raw companion and
full exporter have also been validated against an authorized local time window.

Full-media archive validation currently covers macOS 27.0.1 and WeChat 4.1.15
build 270102. Linux/Windows builds were not validated on this host because their
Rust target toolchains were unavailable.
