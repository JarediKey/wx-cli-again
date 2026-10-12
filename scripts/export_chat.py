#!/usr/bin/env python3
"""Export one local WeChat chat to offline HTML, TXT, JSON, media, and ZIP."""
from __future__ import annotations
import argparse
import collections
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]


def run(args, timeout=180):
    result = subprocess.run([str(a) for a in args], capture_output=True, text=True, timeout=timeout)
    if result.returncode:
        raise RuntimeError(result.stderr.strip()[-1000:] or f'{Path(args[0]).name} failed')
    return result.stdout


def executable(name):
    found = shutil.which(name)
    local = Path.home() / '.local/bin' / name
    if found:
        return found
    if local.is_file():
        return str(local)
    raise RuntimeError(f'{name} is not installed; see SKILL.md')


def normalize(value):
    return ''.join(c for c in value.casefold() if c.isalnum())


def choose_chat(query, rows):
    unique = {r['username']: r for r in rows if r.get('username')}
    rows = list(unique.values())
    exact = [r for r in rows if query == r['username'] or normalize(query) == normalize(r.get('chat', r.get('display', '')))]
    candidates = exact or [r for r in rows if normalize(query) in normalize(r.get('chat', r.get('display', '')))]
    if len(candidates) != 1:
        labels = [r.get('chat', r.get('display', '')) for r in candidates]
        raise RuntimeError('Chat not found or ambiguous: ' + json.dumps(labels, ensure_ascii=False))
    return candidates[0]['username']


def resolve_chat(wx, query):
    if query.endswith('@chatroom') or query.startswith('wxid_'):
        return query
    limit = 200
    while True:
        rows = json.loads(run([wx, 'sessions', '-n', str(limit), '--json']))['sessions']
        if len(rows) < limit:
            break
        limit *= 2
    contacts = json.loads(run([wx, 'contacts', '--query', query, '-n', '10000', '--json']))
    if isinstance(contacts, dict):
        contacts = contacts.get('contacts', [])
    return choose_chat(query, rows + contacts)


def parse_time(value, timezone):
    """Require an explicit offset for ambiguous or nonexistent local times."""
    if value.isdigit():
        return int(value)
    parsed = dt.datetime.fromisoformat(value.replace('Z', '+00:00'))
    if parsed.tzinfo:
        return int(parsed.timestamp())
    early, late = parsed.replace(tzinfo=timezone, fold=0), parsed.replace(tzinfo=timezone, fold=1)
    if early.utcoffset() != late.utcoffset() or dt.datetime.fromtimestamp(early.timestamp(), timezone).replace(tzinfo=None) != parsed:
        raise ValueError('Ambiguous/nonexistent local time; provide an ISO timestamp with UTC offset')
    return int(early.timestamp())


def fetch_messages(wx, chat, start, end):
    limit = 500
    while True:
        args = [wx, 'history', chat, '--after', str(end + 1), '-n', str(limit), '--json', '--with-meta']
        if start:
            args += ['--before', str(start - 1)]
        data = json.loads(run(args))
        if len(data['messages']) < limit:
            break
        limit *= 2
    data['messages'].sort(key=lambda m: (m['timestamp'], m['local_id']))
    data['count'] = len(data['messages'])
    return data


def xml_root(value):
    if not isinstance(value, str):
        return None
    start = value.find('<msg')
    if start < 0:
        return None
    try:
        return ET.fromstring(value[start:])
    except ET.ParseError:
        return None


def quoted_text(raw, depth=0):
    if depth > 6:
        return str(raw)
    node = xml_root(raw)
    app = node.find('.//appmsg') if node is not None else None
    if app is None:
        return str(raw)
    title = app.findtext('title') or ''
    ref = app.find('refermsg')
    if ref is not None:
        return title + '\n  ↳ ' + (ref.findtext('displayname') or '') + ': ' + quoted_text(ref.findtext('content') or '', depth + 1)
    return '\n'.join(x for x in [title, app.findtext('des')] if x)


def file_matches(account, title):
    # File names from chat XML are untrusted: do not use them as paths/globs.
    if not title or Path(title).name != title or '/' in title or '\\' in title:
        return []
    matches = []
    for base in [account / 'msg/file', account / 'FileStorage/File']:
        if base.is_dir():
            for path in base.rglob('*'):
                if path.name == title and path.is_file() and not path.is_symlink() and path.resolve().is_relative_to(base.resolve()):
                    matches.append(path)
    return matches


def extract_media(wx, messages, account, out, start, end):
    target = out / 'attachments'
    target.mkdir(mode=0o700)
    attachments = []
    ffmpeg = shutil.which('ffmpeg')
    image_messages = [m for m in messages if m.get('type_id') == 'image']
    image_rows = []
    if image_messages:
        offset = 0
        while True:
            data = json.loads(run([wx, 'attachments', messages[0]['_chat'], '--kind', 'image', '-n', '500', '--offset', str(offset), '--json']))
            batch = data['attachments']
            image_rows.extend(r for r in batch if start <= r.get('timestamp', 0) <= end)
            if len(batch) < 500 or (batch and min(r.get('timestamp', 0) for r in batch) < start):
                break
            offset += len(batch)
    image_lookup = {(r['local_id'], r['timestamp']): r for r in image_rows}
    for i, message in enumerate(messages, 1):
        kind = message.get('type_id')
        if kind not in ('image', 'voice') and message.get('appmsg_type') != 6:
            continue
        record = {'index': i, 'local_id': message['local_id'], 'kind': 'file' if message.get('appmsg_type') == 6 else kind, 'status': 'unavailable'}
        stem = f'{i:06d}_{message["local_id"]}'
        raw = message.get('original', {})
        try:
            if kind == 'image':
                row = image_lookup.get((message['local_id'], message['timestamp']))
                if row is None:
                    raise RuntimeError('Image metadata not available locally')
                decoded = target / (stem + '.decoded')
                info = json.loads(run([wx, 'extract', row['attachment_id'], '-o', decoded, '--json']))
                fmt = info['format']
                native = decoded.with_suffix('.wxgf' if fmt == 'hevc' else '.' + fmt)
                decoded.rename(native)
                record.update(status='exported', original_file=str(native.relative_to(out)), format=fmt)
                if fmt == 'hevc' and ffmpeg:
                    preview = target / (stem + '.png')
                    run([ffmpeg, '-v', 'error', '-f', 'hevc', '-i', native, '-frames:v', '1', '-y', preview])
                    record['preview_file'] = str(preview.relative_to(out))
                elif fmt in ('jpg', 'jpeg', 'png', 'webp', 'gif'):
                    record['preview_file'] = str(native.relative_to(out))
                else:
                    record['preview_warning'] = 'Original retained; preview decoder unavailable'
            elif kind == 'voice':
                server_id = raw.get('server_id')
                if not server_id:
                    raise RuntimeError('Voice server ID unavailable')
                native = target / (stem + '.silk')
                run([wx, 'media', 'voice', server_id, '-o', native])
                record.update(status='exported', original_file=str(native.relative_to(out)))
                try:
                    import pilk
                except ImportError:
                    record['preview_warning'] = 'SILK retained; optional pilk decoder is not installed'
                else:
                    if ffmpeg:
                        pcm, preview = native.with_suffix('.pcm'), native.with_suffix('.mp3')
                        pilk.decode(str(native), str(pcm), pcm_rate=24000)
                        record['duration_seconds'] = pcm.stat().st_size / (24000 * 2)
                        run([ffmpeg, '-v', 'error', '-f', 's16le', '-ar', '24000', '-ac', '1', '-i', pcm, '-codec:a', 'libmp3lame', '-q:a', '3', '-y', preview])
                        pcm.unlink()
                        record['preview_file'] = str(preview.relative_to(out))
                    else:
                        record['preview_warning'] = 'SILK retained; FFmpeg is not installed'
            else:
                node = xml_root(raw.get('message_content'))
                title = node.findtext('.//appmsg/title') if node is not None else None
                record['name'] = title or 'file'
                matches = file_matches(account, title)
                if not matches:
                    raise RuntimeError('Shared file not downloaded locally')
                digests = {hashlib.sha256(p.read_bytes()).hexdigest() for p in matches}
                if len(digests) != 1:
                    raise RuntimeError('Multiple different files share this name; attachment omitted')
                destination = target / (stem + matches[0].suffix)
                shutil.copyfile(matches[0], destination)
                record.update(status='exported', original_file=str(destination.relative_to(out)))
        except Exception as error:
            record['warning'] = str(error)[-600:]
        attachments.append(record)
    return attachments


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--chat', required=True)
    parser.add_argument('--timezone', required=True, help='IANA zone, e.g. America/Los_Angeles')
    bounds = parser.add_mutually_exclusive_group(required=True)
    bounds.add_argument('--hours', type=float)
    bounds.add_argument('--start', help='Inclusive ISO timestamp or Unix seconds')
    bounds.add_argument('--all', action='store_true', help='All locally available history')
    parser.add_argument('--end', help='Inclusive ISO timestamp or Unix seconds; defaults to now')
    parser.add_argument('--out', type=Path, required=True, help='New output directory outside repositories')
    args = parser.parse_args()
    zone = ZoneInfo(args.timezone)
    end = parse_time(args.end, zone) if args.end else int(dt.datetime.now(dt.timezone.utc).timestamp())
    start = int(end - args.hours * 3600) if args.hours is not None else (parse_time(args.start, zone) if args.start else 0)
    if not 0 <= start <= end or (args.hours is not None and args.hours <= 0):
        parser.error('Invalid time interval')
    out = args.out.expanduser().absolute()
    if out.exists():
        parser.error('Output directory already exists; choose a new destination')
    wx, helper = executable('wx'), executable('wx-archive-data')
    chat = resolve_chat(wx, args.chat)
    data = fetch_messages(wx, chat, start, end)
    raw = json.loads(run([helper, '--chat', chat, '--start', str(start), '--end', str(end)]))
    lookup = collections.defaultdict(list)
    for row in raw['records']:
        lookup[(row['local_id'], row['timestamp'])].append(row)
    out.mkdir(mode=0o700, parents=True)
    warnings = []
    for message in data['messages']:
        candidates = lookup[(message['local_id'], message['timestamp'])]
        if len(candidates) == 1:
            message['original'] = candidates[0]
        else:
            message['original_candidates'] = candidates
            warnings.append(f'Raw row ambiguity for message {message["local_id"]}')
        message['_chat'] = chat
    attachments = extract_media(wx, data['messages'], Path(raw['account_dir']), out, start, end)
    for message in data['messages']:
        message.pop('_chat', None)
    missing = sorted(set(data.get('meta', {}).get('unknown_shards', []) + raw['missing_shards']))
    data['export'] = {'start': start, 'end': end, 'timezone': args.timezone, 'attachments': attachments,
                      'missing_shards': missing, 'warnings': warnings,
                      'generated_at': dt.datetime.now(dt.timezone.utc).isoformat()}
    from archive_render import render_archive
    outputs = render_archive(data, out)
    print(json.dumps({'chat': data['chat'], 'messages': len(data['messages']), **outputs,
                      'missing_shards': missing, 'warnings': warnings,
                      'unavailable_attachments': sum(a['status'] != 'exported' for a in attachments)}, ensure_ascii=False))


if __name__ == '__main__':
    os.umask(0o077)
    try:
        main()
    except Exception as error:
        print(json.dumps({'error': str(error)}, ensure_ascii=False), file=sys.stderr)
        raise SystemExit(1)
