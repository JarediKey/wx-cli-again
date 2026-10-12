# wx-cli Agent Rules

## Validation

- Run `cargo check` immediately after changing Rust files. Do not commit when it fails.
- For shared cross-platform changes, also run:
  - `cargo check --target x86_64-unknown-linux-gnu`
  - `cargo check --target x86_64-pc-windows-msvc`
- Report unavailable target toolchains explicitly; a macOS-only check does not establish cross-platform compatibility.
- After changing the package version, run `cargo update --workspace` and include the lockfile update before tagging.
- For changes to the macOS bootstrap helper or observer, run:
  `python3 -m unittest discover -s tests -p 'test_macos_bootstrap.py' -v`

## Portability

- Under `#[cfg(unix)]`, prefer `std::io::Error::last_os_error()` over the macOS-only `libc::__error()`.
- Put common Cargo dependencies before target-specific dependency tables.
- Use `std::os::windows::process::CommandExt` for Windows process extensions.

## Repository and publishing

- `origin`: `git@github.com:JarediKey/wx-cli-again.git` (this maintained fork).
- `upstream`: `https://github.com/jackwener/wx-cli-again.git` (the original public snapshot).
- Do not redirect pushes to the inherited private `botiverse/wx-cli` repository.
- Preserve this fork's bootstrap adaptation when reviewing and merging upstream changes.
- Use `JarediKey <JarediKey@users.noreply.github.com>` as author and committer for this fork's commits, and verify both before pushing.
- Push commits to this fork when the user has authorized publishing. Create release tags only when requested.
- Never commit local database keys, account configuration, decrypted databases, chat exports, or real-data logs. Synthetic fixtures are sufficient for automated tests.
