//! Read raw fields for one chat and time interval; never print database keys.
#![allow(dead_code)]
#[path = "../src/config.rs"]
mod config;
#[path = "../src/crypto/sqlcipher.rs"]
mod sqlcipher;

use anyhow::{Context, Result};
use clap::Parser;
use rusqlite::{params, types::ValueRef};
use serde_json::{json, Value};
use std::fs;

#[derive(Parser)]
struct Args {
    /// Exact WeChat username, not a display name.
    #[arg(long)]
    chat: String,
    #[arg(long)]
    start: i64,
    #[arg(long)]
    end: i64,
}

fn content(row: &rusqlite::Row<'_>, column: usize) -> rusqlite::Result<String> {
    Ok(match row.get_ref(column)? {
        ValueRef::Null => String::new(),
        ValueRef::Text(value) => String::from_utf8_lossy(value).into_owned(),
        ValueRef::Blob(value) => {
            let decoded = zstd::stream::decode_all(value).ok();
            String::from_utf8_lossy(decoded.as_deref().unwrap_or(value)).into_owned()
        }
        _ => String::new(),
    })
}

fn message_db(name: &str) -> bool {
    name.strip_prefix("message_")
        .and_then(|s| s.strip_suffix(".db"))
        .map(|s| !s.is_empty() && s.bytes().all(|b| b.is_ascii_digit()))
        .unwrap_or(false)
}

fn main() -> Result<()> {
    let args = Args::parse();
    anyhow::ensure!(args.start <= args.end, "Start must not follow end");
    let cfg = config::load_config()?;
    let keys: Value = serde_json::from_str(&fs::read_to_string(&cfg.keys_file)?)?;
    let table = format!("Msg_{:x}", md5::compute(args.chat.as_bytes()));
    let mut records = Vec::new();
    let mut missing = Vec::new();
    for entry in fs::read_dir(cfg.db_dir.join("message"))? {
        let entry = entry?;
        let name = entry.file_name().to_string_lossy().into_owned();
        if !message_db(&name) || !entry.file_type()?.is_file() {
            continue;
        }
        let rel = format!("message/{name}");
        let key = keys[&rel]["enc_key"].as_str().or_else(|| keys[&rel].as_str());
        let Some(key) = key else { missing.push(rel); continue; };
        let conn = sqlcipher::open_encrypted_readonly(&entry.path(), key)
            .with_context(|| format!("Cannot read {rel}"))?;
        let exists: bool = conn.query_row(
            "SELECT EXISTS(SELECT 1 FROM sqlite_master WHERE type='table' AND name=?1)",
            [&table], |row| row.get(0),
        )?;
        if !exists { continue; }
        let mut stmt = conn.prepare(&format!(
            "SELECT local_id,server_id,local_type,create_time,message_content,compress_content,source \
             FROM [{table}] WHERE create_time>=?1 AND create_time<=?2 ORDER BY create_time,local_id"
        ))?;
        let rows = stmt.query_map(params![args.start, args.end], |row| {
            Ok(json!({
                "database": rel, "local_id": row.get::<_,i64>(0)?,
                "server_id": row.get::<_,i64>(1)?.to_string(),
                "local_type": row.get::<_,i64>(2)?, "timestamp": row.get::<_,i64>(3)?,
                "message_content": content(row,4)?, "compress_content": content(row,5)?,
                "source": content(row,6)?,
            }))
        })?;
        for row in rows { records.push(row?); }
    }
    records.sort_by_key(|row| (row["timestamp"].as_i64(),row["local_id"].as_i64()));
    println!("{}", serde_json::to_string(&json!({
        "records": records, "missing_shards": missing,
        "account_dir": cfg.db_dir.parent().context("Missing account directory")?,
    }))?);
    Ok(())
}
