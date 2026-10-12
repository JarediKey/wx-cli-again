"""Bootstrap local WeChat keys through an explicitly launched private app copy.

The entitlement policy and native observer are adapted from chatlog-keeper
(MIT, Copyright 2026 labazhou2024; see LICENSE.chatlog-keeper).
Only Python's standard library and Xcode Command Line Tools are required.
"""
from __future__ import annotations

import argparse
import ctypes
import fcntl
import hashlib
import hmac
import json
import os
from pathlib import Path
import platform
import plistlib
import select
import shutil
import signal
import stat
import struct
import subprocess
import tempfile
import time


APP = Path('/Applications/WeChat.app')
APP_ID = '5A4RE8SF68.com.tencent.xinWeChat'
TEAM = '5A4RE8SF68'
SUPPORTED = {('4.1.15', '270100'), ('4.1.15', '270102')}
CONTAINER = Path.home() / 'Library/Containers/com.tencent.xinWeChat/Data'
LSREGISTER = '/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister'


def report(event, **fields):
    print(json.dumps({'event': event, **fields}, ensure_ascii=False), flush=True)


def run(args, timeout=60):
    result = subprocess.run([str(a) for a in args], capture_output=True, timeout=timeout)
    if result.returncode:
        raise RuntimeError(f'{Path(args[0]).name} failed: '
                           + result.stderr.decode(errors='replace')[-1200:])
    return result.stdout


def entitlements(app):
    return plistlib.loads(run(['/usr/bin/codesign', '-d', '--entitlements', ':-', app]))


def copy_entitlements(original, version):
    """Apply only the inspected 4.1.15 policies; reject unknown identities."""
    if version not in SUPPORTED:
        raise RuntimeError(f'Unsupported WeChat version/build: {version}')
    identities = [original[k] for k in ('application-identifier', 'com.apple.application-identifier')
                  if k in original]
    if (not identities or any(value != APP_ID for value in identities)
            or original.get('com.apple.security.app-sandbox') is not True
            or original.get('com.apple.security.application-groups') != [APP_ID]
            or original.get('com.apple.developer.team-identifier', TEAM) != TEAM):
        raise RuntimeError('Unexpected Tencent signing identity or sandbox entitlements')
    result = dict(original)
    for key in ('application-identifier', 'com.apple.application-identifier',
                'com.apple.developer.team-identifier', 'com.apple.security.application-groups'):
        result.pop(key, None)
    if any(k.startswith(('com.apple.developer.', 'com.apple.private.'))
           or k in ('keychain-access-groups', 'com.apple.security.keychain-access-groups') for k in result):
        raise RuntimeError('Unreviewed identity-bound entitlement')
    result['com.apple.security.temporary-exception.mach-register.global-name'] = [
        f'{APP_ID}.MachPortRendezvousServer.*',
        f'{APP_ID}.MMMojo.MachPortRendezvousServer.*',
        f'{APP_ID}.XPlayerMachPortRendezvousServer.*',
    ]
    result['com.apple.security.get-task-allow'] = True
    return result


def pages(root):
    result = {}
    for path in sorted(root.rglob('*.db')):
        if path.is_symlink():
            continue
        with path.open('rb') as handle:
            page = handle.read(4096)
        if len(page) == 4096 and page[:16] != b'SQLite format 3\0':
            result[path.relative_to(root).as_posix()] = page
    if not result:
        raise RuntimeError('No encrypted databases found')
    return result


def verified(key, page):
    """Verify the SQLCipher 4 first-page MAC, not just a decrypted header."""
    if len(key) != 32 or len(page) != 4096:
        return False
    mac_salt = bytes(value ^ 0x3a for value in page[:16])
    mac_key = hashlib.pbkdf2_hmac('sha512', key, mac_salt, 2, 32)
    actual = hmac.new(mac_key, page[16:4032] + struct.pack('<I', 1), hashlib.sha512).digest()
    return hmac.compare_digest(actual, page[4032:4096])


def match_candidate(candidate, database_pages, found):
    """The observer captures a PBKDF2 password, not a per-database AES key."""
    derived = {}
    for name, page in database_pages.items():
        if name in found:
            continue
        salt = page[:16]
        if salt not in derived:
            derived[salt] = hashlib.pbkdf2_hmac('sha512', candidate, salt, 256000, 32)
        key = derived[salt]
        if verified(key, page):
            found[name] = {'enc_key': key.hex()}


def existing_keys(path, database_pages):
    if not path.exists():
        return {}
    source = json.loads(path.read_text())
    if not isinstance(source, dict):
        raise RuntimeError('Invalid existing key file')
    found = {}
    for name, entry in source.items():
        value = entry.get('enc_key') if isinstance(entry, dict) else entry
        try:
            key = bytes.fromhex(value)
        except (TypeError, ValueError):
            continue
        if name in database_pages and verified(key, database_pages[name]):
            found[name] = {'enc_key': key.hex()}
    return found


def atomic_json(path, value):
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix='.wx-write-', dir=str(path.parent))
    try:
        with os.fdopen(fd, 'w') as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def signature(app):
    result = subprocess.run(['/usr/bin/codesign', '-dvv', str(app)], capture_output=True, check=True)
    return result.stderr


def owned_processes(app):
    """Use kernel executable paths; never signal a process by its display name."""
    libproc = ctypes.CDLL('/usr/lib/libproc.dylib')
    libproc.proc_pidpath.argtypes = [ctypes.c_int, ctypes.c_void_p, ctypes.c_uint32]
    libproc.proc_pidpath.restype = ctypes.c_int
    found = []
    for value in run(['/bin/ps', '-axo', 'pid=']).split():
        pid = int(value)
        buffer = ctypes.create_string_buffer(4096)
        if libproc.proc_pidpath(pid, buffer, len(buffer)) > 0:
            if os.fsdecode(buffer.value).startswith(str(app) + '/'):
                found.append(pid)
    return found


def close_copy(app):
    for sig, seconds in ((signal.SIGTERM, 4), (signal.SIGKILL, 2)):
        for pid in owned_processes(app):
            # Recheck immediately; the unique temporary bundle bounds ownership.
            if pid in owned_processes(app):
                try:
                    os.kill(pid, sig)
                except ProcessLookupError:
                    pass
        deadline = time.monotonic() + seconds
        while owned_processes(app) and time.monotonic() < deadline:
            time.sleep(0.1)
        if not owned_processes(app):
            return
    raise RuntimeError('Temporary WeChat is still running; close it manually')


class Frames:
    """Decode bounded atomic native FIFO records without logging secrets."""
    def __init__(self):
        self.buffer = bytearray()
        self.status = set()
        self.seen = set()
        self.received = 0

    def feed(self, data):
        self.received += len(data)
        if self.received > 65536:
            raise RuntimeError('Capture record limit exceeded')
        self.buffer.extend(data)
        candidates = []
        while len(self.buffer) >= 4:
            magic = bytes(self.buffer[:4])
            size = {b'WXK1': 36, b'WXS1': 16}.get(magic)
            if size is None:
                raise RuntimeError('Invalid capture record')
            if len(self.buffer) < size:
                break
            record = bytes(self.buffer[:size])
            del self.buffer[:size]
            if magic == b'WXS1':
                self.status.add(record[4])
            elif record[4:] not in self.seen:
                self.seen.add(record[4:])
                candidates.append(record[4:])
        return candidates


def prepare_capture(copy, working, rights):
    """Place executable code inside the bundle; permit only the private FIFO."""
    library = copy / 'Contents/Frameworks/wx_bootstrap_capture.dylib'
    library.parent.mkdir(parents=True, exist_ok=True)
    run(['/usr/bin/xcrun', 'clang', '-dynamiclib', '-arch', 'arm64', '-O2',
         '-Wall', '-Wextra', '-Werror', str(Path(__file__).with_name('capture.c')),
         '-o', library])
    run(['/usr/bin/codesign', '--force', '--sign', '-', library])
    run(['/usr/bin/codesign', '--verify', '--strict', library])
    fifo = working / 'capture.fifo'
    os.mkfifo(fifo, 0o600)
    right = 'com.apple.security.temporary-exception.files.absolute-path.read-write'
    rights[right] = list(rights.get(right, [])) + [str(fifo)]
    return library, fifo


def capture(copy, library, fifo, database_pages, found, timeout):
    fd = os.open(fifo, os.O_RDWR | os.O_NONBLOCK | os.O_NOFOLLOW)
    frames = Frames()
    try:
        run(['/usr/bin/open', '-n', '-a', copy, '--env', f'DYLD_INSERT_LIBRARIES={library}',
             '--env', f'WX_CLI_KEY_FIFO={fifo}'])
        report('login_required', message='请在临时微信窗口确认登录；如弹出数据访问提示，请允许。')
        deadline = time.monotonic() + timeout
        next_progress = time.monotonic() + 10
        while time.monotonic() < deadline:
            if select.select([fd], [], [], 0.25)[0]:
                for candidate in frames.feed(os.read(fd, 65536)):
                    match_candidate(candidate, database_pages, found)
                if len(found) == len(database_pages):
                    break
            if time.monotonic() >= next_progress:
                report('capture_progress', verified=len(found), total=len(database_pages),
                       observer_loaded=1 in frames.status, kdf_seen=6 in frames.status)
                next_progress = time.monotonic() + 15
                if not owned_processes(copy):
                    raise RuntimeError('Temporary WeChat exited before capture completed')
        report('capture_finished', verified=len(found), total=len(database_pages),
               observer_loaded=1 in frames.status, kdf_seen=6 in frames.status)
        if not found:
            raise RuntimeError('No verified keys; confirm login and temporary-app data access')
    finally:
        os.close(fd)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', required=True, type=Path)
    parser.add_argument('--timeout', type=int, default=180)
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    if platform.system() != 'Darwin' or platform.machine() != 'arm64' or os.geteuid() == 0:
        raise RuntimeError('Run as your normal user on native Apple Silicon macOS, without sudo')
    if not 15 <= args.timeout <= 600:
        raise RuntimeError('Timeout must be between 15 and 600 seconds')
    run(['/usr/bin/codesign', '--verify', '--deep', '--strict', APP])
    before = signature(APP)
    if f'TeamIdentifier={TEAM}'.encode() not in before:
        raise RuntimeError('Expected an unmodified official Tencent WeChat app')
    info = plistlib.loads((APP / 'Contents/Info.plist').read_bytes())
    version = (info.get('CFBundleShortVersionString'), info.get('CFBundleVersion'))
    rights = copy_entitlements(entitlements(APP), version)
    config_path = args.config.absolute()
    config = json.loads(config_path.read_text()) if config_path.exists() else {}
    if config.get('db_dir'):
        root = Path(config['db_dir']).resolve(strict=True)
    else:
        roots = list((CONTAINER / 'Documents/xwechat_files').glob('*/db_storage'))
        if len(roots) != 1:
            raise RuntimeError('Expected one account; configure db_dir explicitly for multiple accounts')
        root = roots[0].resolve(strict=True)
    database_pages = pages(root)
    key_path = Path(config.get('keys_file', 'all_keys.json'))
    if not key_path.is_absolute():
        key_path = config_path.parent / key_path
    report('preflight_ok', version=version[0], build=version[1], databases=len(database_pages))
    if args.check:
        return
    if subprocess.run(['/usr/bin/pgrep', '-x', 'WeChat'], capture_output=True).returncode == 0:
        raise RuntimeError('Quit WeChat normally, then run wx key bootstrap again')
    config_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    lock_path = config_path.parent / '.bootstrap.lock'
    with lock_path.open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        found = existing_keys(key_path, database_pages)
        with tempfile.TemporaryDirectory(prefix='wx-bootstrap-', dir=str(config_path.parent)) as working:
            copy = Path(working) / 'WeChat.app'
            try:
                run(['/usr/bin/ditto', APP, copy], timeout=600)
                library, fifo = prepare_capture(copy, Path(working), rights)
                rights_path = Path(working) / 'entitlements.plist'
                rights_path.write_bytes(plistlib.dumps(rights))
                run(['/usr/bin/codesign', '--force', '--sign', '-', '--entitlements', rights_path, copy])
                run(['/usr/bin/codesign', '--verify', '--deep', '--strict', copy])
                if entitlements(copy) != rights or b'(runtime)' in signature(copy):
                    raise RuntimeError('Temporary signature or entitlements verification failed')
                capture(copy, library, fifo, database_pages, found, args.timeout)
                # Revalidate against the current database pages before persisting.
                current = pages(root)
                found = {name: value for name, value in found.items()
                         if name in current and verified(bytes.fromhex(value['enc_key']), current[name])}
                if not found:
                    raise RuntimeError('Database keys changed during bootstrap; existing state preserved')
                atomic_json(key_path, found)
                config.update(db_dir=str(root), keys_file=str(key_path))
                config.setdefault('decrypted_dir', 'decrypted')
                atomic_json(config_path, config)
                report('keys_saved', verified=len(found), total=len(current),
                       missing=[name for name in current if name not in found])
            finally:
                close_copy(copy)
                subprocess.run([LSREGISTER, '-u', str(copy)], capture_output=True)
                run(['/usr/bin/codesign', '--verify', '--deep', '--strict', APP])
                if signature(APP) != before:
                    raise RuntimeError('Original signature changed unexpectedly')
                run(['/usr/bin/open', '-a', APP])
                report('original_restored', signature_unchanged=True)


if __name__ == '__main__':
    os.umask(0o077)
    try:
        main()
    except KeyboardInterrupt:
        report('interrupted')
        raise SystemExit(130)
    except Exception as error:
        report('error', message=str(error))
        raise SystemExit(1)
