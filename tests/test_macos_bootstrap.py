"""Synthetic tests for bootstrap: no account data or WeChat process required."""
import hashlib
import hmac
import importlib.util
import json
import os
from pathlib import Path
import platform
import struct
import subprocess
import tempfile
import unittest
from unittest.mock import patch

SOURCE = Path(__file__).resolve().parents[1] / 'src/bootstrap'
spec = importlib.util.spec_from_file_location('bootstrap', SOURCE / 'bootstrap.py')
bootstrap = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bootstrap)


def page_for(key, salt):
    page = bytearray(salt + bytes([17]) * (4096 - 16))
    mac_key = hashlib.pbkdf2_hmac('sha512', key, bytes(x ^ 0x3a for x in salt), 2, 32)
    page[4032:] = hmac.new(mac_key, page[16:4032] + struct.pack('<I', 1), hashlib.sha512).digest()
    return bytes(page)


class BootstrapTests(unittest.TestCase):
    def test_master_password_is_derived_per_database_and_authenticated(self):
        master = bytes([7]) * 32
        salts = [bytes([8]) * 16, bytes([9]) * 16]
        keys = [hashlib.pbkdf2_hmac('sha512', master, salt, 256000, 32) for salt in salts]
        pages = {str(i): page_for(key, salt) for i, (key, salt) in enumerate(zip(keys, salts))}
        found = {}
        bootstrap.match_candidate(master, pages, found)
        self.assertEqual([found[str(i)]['enc_key'] for i in range(2)], [x.hex() for x in keys])
        self.assertFalse(bootstrap.verified(master, pages['0']))
        damaged = bytearray(pages['0'])
        damaged[200] ^= 1
        self.assertFalse(bootstrap.verified(keys[0], damaged))

    def test_wrong_candidate_cannot_replace_previously_verified_keys(self):
        key = bytes([4]) * 32
        page = page_for(key, bytes([3]) * 16)
        found = {'one.db': {'enc_key': key.hex()}}
        bootstrap.match_candidate(bytes([0]) * 32, {'one.db': page, 'two.db': page}, found)
        self.assertEqual(found, {'one.db': {'enc_key': key.hex()}})

    def test_policy_keeps_sandbox_and_adds_only_scoped_mach_services(self):
        original = {'com.apple.application-identifier': bootstrap.APP_ID,
                    'com.apple.security.app-sandbox': True,
                    'com.apple.security.application-groups': [bootstrap.APP_ID],
                    'com.apple.security.device.camera': True}
        changed = bootstrap.copy_entitlements(original, ('4.1.15', '270102'))
        self.assertTrue(changed['com.apple.security.app-sandbox'])
        self.assertTrue(changed['com.apple.security.device.camera'])
        self.assertNotIn('com.apple.application-identifier', changed)
        self.assertIn('com.apple.application-identifier', original)
        services = changed['com.apple.security.temporary-exception.mach-register.global-name']
        self.assertEqual(len(services), 3)
        self.assertTrue(services[-1].endswith('.XPlayerMachPortRendezvousServer.*'))
        for version in [('4.1.15', '270103'), ('4.1.15.22', '270102')]:
            with self.assertRaises(RuntimeError):
                bootstrap.copy_entitlements(original, version)
        with self.assertRaises(RuntimeError):
            bootstrap.copy_entitlements({**original, 'keychain-access-groups': ['unexpected']},
                                        ('4.1.15', '270102'))

    def test_fifo_handles_split_records_deduplicates_and_rejects_invalid_magic(self):
        frames = bootstrap.Frames()
        key_record = b'WXK1' + bytes([7]) * 32
        status = b'WXS1' + bytes([6]) + bytes(11)
        self.assertEqual(frames.feed(key_record[:3]), [])
        self.assertEqual(frames.feed(key_record[3:] + status + key_record), [bytes([7]) * 32])
        self.assertIn(6, frames.status)
        with self.assertRaises(RuntimeError):
            frames.feed(b'nope')

    def test_atomic_key_file_permissions_and_validation(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'keys.json'
            key = bytes([6]) * 32
            bootstrap.atomic_json(path, {'db': {'enc_key': key.hex()}, 'bad': {'enc_key': 'broken'}})
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertEqual(bootstrap.existing_keys(path, {'db': page_for(key, bytes(16))}),
                             {'db': {'enc_key': key.hex()}})

    def test_capture_library_is_bundled_and_only_fifo_gets_write_exception(self):
        with tempfile.TemporaryDirectory() as tmp:
            working = Path(tmp)
            copy = working / 'WeChat.app'
            rights = {'com.apple.security.app-sandbox': True}
            with patch.object(bootstrap, 'run'):
                library, fifo = bootstrap.prepare_capture(copy, working, rights)
            self.assertTrue(str(library).startswith(str(copy / 'Contents/Frameworks') + '/'))
            self.assertEqual(rights['com.apple.security.temporary-exception.files.absolute-path.read-write'],
                             [str(fifo)])
            self.assertEqual(fifo.stat().st_mode & 0o777, 0o600)
            self.assertTrue(rights['com.apple.security.app-sandbox'])

    @unittest.skipUnless(platform.system() == 'Darwin' and platform.machine() == 'arm64', 'macOS arm64')
    def test_native_observer_preserves_pbkdf2_and_emits_private_fifo_candidate(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            dylib = root / 'capture.dylib'
            exe = root / 'probe'
            program = root / 'probe.c'
            program.write_text('''#include <CommonCrypto/CommonKeyDerivation.h>
#include <stdio.h>
#include <string.h>
int main(void) {
    char password[32]; memset(password, 7, 32);
    unsigned char salt[16]; memset(salt, 8, 16);
    unsigned char output[32];
    int result = CCKeyDerivationPBKDF(kCCPBKDF2, password, 32, salt, 16,
        kCCPRFHmacAlgSHA512, 256000, output, 32);
    if (result) return 1;
    for (int i = 0; i < 32; ++i) printf("%02x", output[i]);
    return 0;
}
''')
            bootstrap.run(['/usr/bin/xcrun', 'clang', '-dynamiclib', '-arch', 'arm64',
                           '-Wall', '-Wextra', '-Werror', SOURCE / 'capture.c', '-o', dylib])
            bootstrap.run(['/usr/bin/xcrun', 'clang', '-arch', 'arm64', program, '-o', exe])
            fifo = root / 'capture.fifo'
            os.mkfifo(fifo, 0o600)
            fd = os.open(fifo, os.O_RDWR | os.O_NONBLOCK)
            try:
                result = subprocess.run([str(exe)], capture_output=True, timeout=10,
                                        env={**os.environ, 'DYLD_INSERT_LIBRARIES': str(dylib),
                                             'WX_CLI_KEY_FIFO': str(fifo)})
                self.assertEqual(result.returncode, 0, result.stderr.decode(errors='replace'))
                expected = hashlib.pbkdf2_hmac('sha512', bytes([7]) * 32, bytes([8]) * 16, 256000, 32)
                self.assertEqual(result.stdout.decode(), expected.hex())
                frames = bootstrap.Frames()
                self.assertEqual(frames.feed(os.read(fd, 65536)), [bytes([7]) * 32])
                self.assertIn(4, frames.status)
                self.assertIn(8, frames.status)
            finally:
                os.close(fd)


if __name__ == '__main__':
    unittest.main()
