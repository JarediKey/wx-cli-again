# macOS permissions and key bootstrap

[简体中文](macos-permission-guide.zh.md)

## Supported bootstrap environment

`wx key bootstrap` supports native Apple Silicon macOS and official WeChat
4.1.15 builds **270100 / 270102**. The signed `Info.plist` version/build pair is
checked; a Sparkle feed version such as `4.1.15.22` is not the bundle version.
Unknown builds are rejected. Xcode Command Line Tools provide Python 3 and clang.

Give the invoking application (Terminal or your agent host) Full Disk Access.
Run bootstrap as your normal user, without sudo. It does not change SIP.

```bash
wx key bootstrap --check
# Quit WeChat normally before the following command.
wx key bootstrap --timeout 180
wx doctor
wx sessions --json
```

The temporary WeChat window may ask for app-data access, “Enter WeChat”, phone
confirmation, or QR login. Complete those prompts while capture is running.
The timeout accepts 15–600 seconds. `--check` only inspects prerequisites.

## What bootstrap does

1. Verifies the installed Tencent signature, exact build, entitlements, and
   database access. With multiple accounts, set `db_dir` in the selected config.
2. Copies the app into a private, per-run directory beside the CLI config.
3. Re-signs only this copy. The copy retains App Sandbox, removes incompatible
   Tencent identity claims, adds debugging and the scoped Mach services required
   by these builds, and allows writing to one private FIFO.
4. Builds a fixed PBKDF2 observer inside the copy's app bundle. Before login it
   captures bounded 32-byte password candidates through a user-owned `0600` FIFO.
5. Derives per-database keys and verifies each against the first-page
   SQLCipher 4 HMAC-SHA512. Only verified keys are atomically persisted with
   `0600` permissions. Previously valid keys are retained; failed capture does
   not replace the configuration.
6. Closes only processes whose kernel executable path belongs to its unique
   temporary bundle, removes the temporary copy, verifies the original signature,
   and requests launch of the installed original app.

The original `/Applications/WeChat.app` is never re-signed. The temporary copy
has fewer runtime protections and is used only for this explicit bootstrap.
It accesses the same account data and may perform normal WeChat login/network
activity. It is not a separate account or a daily replacement client.

## Ordinary reads and coverage

Daily `sessions`, `history`, `search`, and other commands use saved keys without
sudo. `doctor` and response `meta.unknown_shards` report missing key coverage.
A successful bootstrap may still have missing databases; check the reported
`missing` list and `wx doctor` before assuming history is complete. New database
shards or changed keys may require bootstrap again.

The existing `sudo wx init` / `sudo wx key extract --hook-seconds 90` memory-scan
path remains available where macOS permits it. Full Disk Access controls file
access; Developer Tools authorization and sudo do **not** guarantee permission
to attach to an official Hardened Runtime app. A `task_for_pid` failure is not
proof that the database encryption format changed.

## Troubleshooting

- `Unsupported WeChat version/build`: use an inspected build or review the new
  build before extending the policy; do not merely widen the version check.
- `PermissionError` reading the container: enable Full Disk Access for the
  invoking host and reopen it if macOS requests that.
- `Quit WeChat normally`: close the daily client from its menu before retrying.
- `observer_loaded=false`: inspect the temporary app's crash report. The observer
  must reside inside the app bundle on macOS 27; external library paths may be
  blocked before the app presents a window.
- `kdf_seen=false`: finish login. If it remains false, the native capture boundary
  needs investigation for that OS/build.
- No verified keys: check the configured account and login, then inspect capture
  diagnostics. Do not post keys, database files, or full chat logs publicly.

## Sources and validation

The native observer and build-specific entitlement policy derive from
[chatlog-keeper](https://github.com/labazhou2024/chatlog-keeper), MIT,
Copyright 2026 labazhou2024. Its license is retained in
[`src/bootstrap/LICENSE.chatlog-keeper`](../src/bootstrap/LICENSE.chatlog-keeper).
The macOS 27 adaptation uses a direct linked CommonCrypto reference, verifies
its system-library owner, and keeps the observer inside the temporary bundle.

Synthetic validation (no personal data) includes first-page MAC failures,
per-database derivation, bounded FIFO parsing, key-file permissions, entitlement
rejection, and a compiled native probe verifying unchanged PBKDF2 output:

```bash
/usr/bin/python3 -m unittest discover -s tests -p 'test_macos_bootstrap.py' -v
cargo check --locked
```
