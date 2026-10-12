# wx-cli

[简体中文](README.md)

Query local WeChat data from the command line: sessions, history, search,
contacts, group members and aliases, favorites, statistics, and export.
The Rust CLI uses a local daemon and persistent database caches. It reads
encrypted databases online where possible and refreshes decrypted caches using
database modification times and WAL changes where necessary. Chat data stays
on the local machine. Performance depends on database size and cache state.

## Installation and updates

This public checkout can be built from source:

```bash
git clone https://github.com/JarediKey/wx-cli-again.git
cd wx-cli-again
cargo build --release --locked
mkdir -p ~/.local/bin
cp target/release/wx ~/.local/bin/wx
wx --version
```

The package version is 0.6.3. The local macOS bootstrap adaptation is not an
upstream release. Windows builds produce `target\release\wx.exe`; put it on PATH.

The inherited upstream source/release links point to the private
[`botiverse/wx-cli`](https://github.com/botiverse/wx-cli). Anonymous raw downloads
and the old public npm package `@jackwener/wx-cli@0.3.0` do not deliver that private
repository's latest binaries. Its release assets and install scripts require
access to that repository. The documented asset names are `wx-macos-arm64`,
`wx-macos-x86_64`, `wx-linux-x86_64`, `wx-linux-arm64`, and `wx-windows-x86_64.exe`.

The fork remote `origin` points to `JarediKey/wx-cli-again`; `upstream` points to
[`jackwener/wx-cli-again`](https://github.com/jackwener/wx-cli-again). To synchronize
upstream, run `git fetch upstream`, review and merge `upstream/main`, preserving
this fork's bootstrap adaptation. To update from the fork, use `git pull`,
`cargo build --release`, and copy the resulting executable onto PATH. Preserve
local modifications before pulling. Install this fork's Agent Skill with
`npx skills add JarediKey/wx-cli-again` (add `-g` for a global installation), or
use Codex's Skill Installer on the repository root. It supports queries, summaries,
and complete archives with local media. See the [export and Skill guide](docs/chat-export.md)
for companion dependencies and usage.

## macOS initialization

For native Apple Silicon and official WeChat **4.1.15 builds 270100 / 270102**,
use the explicit temporary-copy bootstrap:

```bash
wx key bootstrap --check
# Quit WeChat normally, then run as your normal user, without sudo.
wx key bootstrap --timeout 180
wx doctor
wx sessions --json
```

The copy exists only for login-time key capture. It is cleaned up before the
original app is reopened. The installed WeChat retains its official signature
and SIP stays enabled. macOS 27.0.1 with build 270102 has passed a live validation
of 20 database keys, group/private history, contacts, and search. See the
[permissions and bootstrap guide](docs/macos-permission-guide.md) for exact
scope, prompts, failure handling, and limitations.

The older memory-scan path is available where macOS permits process debugging:

```bash
# Keep WeChat logged in; use a local GUI Terminal, not SSH.
sudo wx init
sudo wx key extract --hook-seconds 90
```

During the hook window, opening chats and older history can load cold shards.
The scanner checks cached hexadecimal key/salt strings and salt-adjacent keys,
then attaches LLDB to CommonCrypto AES calls to fill gaps. Official Hardened
Runtime apps may reject attachment despite sudo and Developer Tools permission.
Use bootstrap on supported builds instead of assuming those permissions suffice.
Do not preemptively re-sign the installed app: doing so can disrupt TCC,
screenshots, and article access. Some previously modified apps are already
ad-hoc signed; those may permit a user-mode LLDB hook.

Linux initializes with `sudo wx init`; Windows uses `wx init` in an elevated
PowerShell. Daily queries do not require sudo, and WeChat need not stay open to
read already downloaded local data.

## Diagnostics and keys

```bash
wx doctor
wx doctor --fix --json
wx key list
wx key extract --hook-seconds 90
wx key set message/message_1.db <64hex>
```

`key set` validates the supplied key. For the traditional scan path, prefer
`sudo wx key extract --hook-seconds 90` to an unexplained `init --force` retry.
For supported official macOS builds that reject attachment, use bootstrap.
Check `doctor` and `meta.unknown_shards` before treating history as complete.

## Sessions, messages, and search

```bash
wx sessions
wx unread
wx unread --filter private,group
wx new-messages
wx history "Alice"
wx history "Alice" -n 2000
wx history "Project group" --since 2026-04-01 --until 2026-04-15
wx search "keyword"
wx search "keyword" -n 500
wx search "meeting" --in "Project group" --since 2026-01-01
```

`history`, `search`, and `export` accept `-n` / `--limit`; defaults limit output,
not the total history available. `chat_type` distinguishes `private`, `group`,
`official_account`, and `folded`. Official accounts include subscription/service
accounts and system contacts such as `mphelper`; folded entries represent the
subscription and folded-group aggregate sessions.

Group sender names prefer group aliases, then contact remarks/nicknames/usernames.
History, search, new messages, attachments, and statistics also provide stable
`sender_username`, `sender_contact_display`, and `sender_group_nickname` when the
sender can be resolved. These fields are omitted when identity is unknown.

Message/session responses include `meta`:

- `status`: `ok`, `possibly_stale`, `possibly_stale_unknown_shards`, or `windowed`.
- `unknown_shards`: encrypted message shards without a known key.
- `chat_latest_timestamp` / `chat_latest_db`: newest available message and source.
- `session_last_timestamp`: WeChat's session timestamp; a newer value may indicate
  missing messages in the returned history.

Human-readable warnings go to stderr. `--with-meta` adds per-shard timestamps
and cache modes; hidden `--debug-source` additionally exposes actual shard paths.
Quoted messages include both the reply and quoted text. Link/file filters cover
app-message variants including links, files, forwarded chat records, and quotes;
search also matches decoded quoted text.

## Moments and articles

```bash
wx sns-notifications
wx sns-notifications --include-read -n 100
wx sns-feed
wx sns-feed --user "Alice"
wx sns-feed --since 2026-04-01 -n 100
wx sns-search "keyword"
wx sns-search "wedding" --user "Alice" --since 2023-01-01
wx biz-articles
wx biz-articles -n 200
wx biz-articles --account "Account name"
wx biz-articles --since 2026-05-01 --until 2026-05-10
wx biz-articles --unread
wx biz-articles --json | jq '.[].url'
```

Moments notifications expose like/comment type, sender, comment text, and original
post preview/author. Feed and search return post author, text, media, media count,
location, and timestamp. Media records include URL/thumb/key/token/md5/enc_idx/size
for downstream rendering; malformed XML produces a zero media count. Only posts
already fetched by the local WeChat app are available.

Articles live in separate `biz_message_*.db` shards. Results include account,
account username, title, URL, digest, cover URL, time, timestamp, and receive-time
string. Multi-article pushes are expanded. `--unread` selects one latest item per
account with unread messages.

## Image attachments

```bash
wx attachments "Alice"
wx attachments "Project group" --kind image -n 100
wx attachments "Project group" --since 2026-04-01 --until 2026-04-15
wx extract <attachment_id> -o ~/Desktop/photo.jpg
wx extract <attachment_id> -o /tmp/photo.jpg --overwrite
```

The attachment lookup combines local `.dat` files, `message_resource.db`, MD5,
and platform image keys. Results contain an opaque `attachment_id`, kind, type,
local ID, timestamp/time, and group sender identity. Currently the supported kind
is `image`. Extraction reports the input/output paths and sizes, MD5, detected
format, and decoder (`legacy_xor`, `v1_aes`, or `v2`).

Supported formats include legacy single-byte XOR; V1 fixed AES-128-ECB with key
`cfcd208495d565ef`; and V2 AES, raw segments, and XOR. On macOS, V2 derives the
image key from local `kvcomm` UIN metadata and the account identity, with a
24-bit UIN search when necessary: `md5(str(uin) + wxid)[:16]`, XOR `uin & 0xff`.
Windows scans candidate keys and validates against a ciphertext template.
Linux V2 extraction is unsupported. Output formats may include JPEG, PNG, GIF,
WebP, or HEVC depending on the local payload.

## Contacts, favorites, statistics, and export

```bash
wx contacts
wx contacts --query "Alice"
wx members "Project group"
wx favorites
wx favorites --type image
wx favorites --query "keyword"
wx stats "Project group"
wx stats "Project group" --since 2026-01-01
wx export "Alice" --format markdown -o chat.md
wx export "Alice" -n 2000 --format markdown -o chat.md
wx export "Project group" --since 2026-01-01 --format json
```

Member records contain username, preferred display name, contact display name,
group nickname (empty when unavailable), and owner status. Favorite filters
include text, image, article, card, and video.

## Output and daemon

Default output is YAML; use `--json` for JSON. History, search, sessions,
new messages, statistics, and attachments return wrappers with metadata.

```bash
wx sessions --json
wx search "keyword" --json | jq '.results[0].content'
wx history "Alice" --json | jq '.meta'
wx history "Alice" --json --with-meta | jq '.meta.cache_mode_per_shard'
wx daemon status
wx daemon stop
wx daemon logs --follow
```

The first query starts the daemon automatically. If it becomes unresponsive,
stop it and issue another query. The CLI communicates through a local socket.
Keys/config normally live in `~/.wx-cli/`; an existing config beside the CLI or
in the working directory enables portable operation. The same directory holds
the daemon socket, PID/log, and `cache/` with decrypted databases and mtime metadata.

WeChat 4.x uses SQLCipher 4 page encryption (AES-256-CBC and HMAC-SHA512).
Bootstrap derives per-database AES keys from captured PBKDF2 inputs and verifies
them before saving. Daily reads prefer online encrypted access; cache fallback
uses full decryption followed by mtime/WAL updates when needed.

## Acknowledgements and scope

The original project credits
[`ylytdeng/wechat-decrypt`](https://github.com/ylytdeng/wechat-decrypt) as research
and design inspiration. The local bootstrap observer and entitlement policy
derive from [`chatlog-keeper`](https://github.com/labazhou2024/chatlog-keeper);
its MIT notice is retained in `src/bootstrap/LICENSE.chatlog-keeper`.
The main project uses [Apache-2.0](LICENSE). Use local data that you own or are
authorized to access.
