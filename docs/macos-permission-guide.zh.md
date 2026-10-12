# macOS 权限与密钥初始化

[English](macos-permission-guide.md)

## 支持环境

`wx key bootstrap` 支持原生 Apple Silicon macOS 与官方微信
4.1.15 **270100 / 270102**。按已签名 `Info.plist` 中的版本和 build 检查；
更新源中的 `4.1.15.22` 不等于应用包版本。未知 build 会被拒绝。
需要 Xcode Command Line Tools 提供 Python 3 和 clang。

给调用程序（Terminal 或 AI 工具宿主）开启完全磁盘访问权限。
使用普通用户运行 bootstrap，不加 sudo，也不修改 SIP。

```bash
wx key bootstrap --check
# 下一条命令前，请从菜单正常退出微信。
wx key bootstrap --timeout 180
wx doctor
wx sessions --json
```

临时微信窗口可能要求允许访问 App 数据、点击“进入微信”、手机确认或扫码登录。
请在捕获期间完成这些操作。超时可设置为 15–600 秒。
`--check` 只检查前置条件。

## 初始化流程

1. 验证已安装微信的腾讯签名、精确 build、签名权限及数据库访问。
   多账号时，在选中的配置文件中明确设置 `db_dir`。
2. 将微信复制到 CLI 配置目录旁的私有、单次运行目录。
3. 只重签临时副本。保留 App Sandbox，移除不兼容的腾讯身份声明，
   添加调试和对应 build 所需的限定 Mach 服务权限，仅允许写入一个私有 FIFO。
4. 在副本的应用包内编译固定的 PBKDF2 捕获库。登录前开始捕获，
   通过当前用户拥有、权限为 `0600` 的 FIFO 传递有限数量的 32 字节候选。
5. 为每个数据库派生密钥，并通过第一页 SQLCipher 4 HMAC-SHA512 校验。
   只将有效密钥以 `0600` 权限原子写入。保留原先有效的密钥，
   捕获失败不替换配置。
6. 仅关闭内核可执行路径属于本次临时应用包的进程，清理临时副本，
   验证原应用签名，并请求重新启动原微信。

原始 `/Applications/WeChat.app` 不会被重签。
临时副本的运行时保护较少，仅用于显式初始化。
它访问同一账号数据，可能执行微信正常的登录和网络请求，
不是独立账号，也不是日常使用的替代客户端。

## 日常读取与完整性

`sessions`、`history`、`search` 等日常命令使用已保存的密钥，无需 sudo。
`doctor` 和响应中的 `meta.unknown_shards` 会报告缺失的分片密钥。
初始化成功仍可能有数据库缺钥；请检查输出的 `missing` 和 `wx doctor`，
再判断聊天记录是否完整。新建分片或密钥变化可能需要重新初始化。

原有 `sudo wx init` / `sudo wx key extract --hook-seconds 90` 内存扫描路径
在系统允许时仍可使用。完全磁盘访问控制文件访问；sudo 和“开发者工具”授权
**不保证**能附加到官方 Hardened Runtime 应用。
`task_for_pid` 失败不能证明数据库加密格式发生了变化。

## 排障

- `Unsupported WeChat version/build`：使用已检查的版本，或先审查新 build；
  不要只扩大版本白名单。
- 访问容器出现 `PermissionError`：给调用宿主开启完全磁盘访问权限，
  并按 macOS 提示重新打开。
- `Quit WeChat normally`：从菜单退出日常微信后重试。
- `observer_loaded=false`：检查临时应用的崩溃报告。
  macOS 27 上捕获库应放在应用包内，外部路径可能在窗口出现前就被沙盒阻止。
- `kdf_seen=false`：完成登录；若仍为 false，需要调查该系统和 build 的捕获位置。
- 没有有效密钥：核对配置的账号、登录状态和捕获诊断。
  不要在公开问题中贴密钥、数据库或完整聊天日志。

## 来源与验证

原生捕获库及 build 对应的权限策略借鉴
[chatlog-keeper](https://github.com/labazhou2024/chatlog-keeper)，MIT，
Copyright 2026 labazhou2024。许可保留于
[`src/bootstrap/LICENSE.chatlog-keeper`](../src/bootstrap/LICENSE.chatlog-keeper)。
macOS 27 适配使用直接链接的 CommonCrypto 引用，校验其系统库归属，
并将捕获库置于临时应用包内。

合成测试不使用个人数据，覆盖错误 MAC、逐库派生、受限 FIFO 解析、
密钥文件权限、未知签名权限拒绝，以及验证 PBKDF2 结果不变的原生编译探针：

```bash
/usr/bin/python3 -m unittest discover -s tests -p 'test_macos_bootstrap.py' -v
cargo check --locked
```
