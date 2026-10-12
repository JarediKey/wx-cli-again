//! Explicit macOS bootstrap using an isolated WeChat copy and startup observer.

use anyhow::{bail, Context, Result};
use std::fs;
use std::os::unix::fs::DirBuilderExt;
use std::process::Command;
use std::time::{SystemTime, UNIX_EPOCH};

pub fn cmd_bootstrap(timeout: u64, check: bool) -> Result<()> {
    if unsafe { libc::geteuid() } == 0 {
        bail!("请使用普通用户运行 wx key bootstrap，不要加 sudo");
    }
    let nonce = SystemTime::now().duration_since(UNIX_EPOCH)?.as_nanos();
    let staging = std::env::temp_dir().join(format!("wx-bootstrap-{}-{nonce}", std::process::id()));
    fs::DirBuilder::new().mode(0o700).create(&staging)?;
    let result = (|| -> Result<()> {
        fs::write(staging.join("bootstrap.py"), include_str!("../bootstrap/bootstrap.py"))?;
        fs::write(staging.join("capture.c"), include_str!("../bootstrap/capture.c"))?;
        let mut command = Command::new("/usr/bin/python3");
        command.arg(staging.join("bootstrap.py"))
            .arg("--config").arg(super::init::find_or_create_config_path())
            .arg("--timeout").arg(timeout.to_string());
        if check {
            command.arg("--check");
        }
        let status = command.status().context("启动 macOS bootstrap 失败（需要 Xcode Command Line Tools）")?;
        if !status.success() {
            bail!("bootstrap 未完成，退出状态: {status}");
        }
        if !check && crate::config::sock_path().exists() {
            let response = super::transport::send(crate::ipc::Request::ReloadConfig)?;
            if !response.ok {
                bail!("密钥已保存，但 daemon 重载失败：{}", response.error.unwrap_or_default());
            }
        }
        Ok(())
    })();
    let _ = fs::remove_dir_all(staging);
    result
}
