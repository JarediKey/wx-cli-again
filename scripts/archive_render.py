"""Render an offline chat archive. Treat all message content as untrusted text."""
from __future__ import annotations
import base64
import collections
import datetime as dt
import hashlib
import html
import json
import mimetypes
from pathlib import Path
import re
import zipfile
from zoneinfo import ZoneInfo
from export_chat import quoted_text, xml_root

ROOT = Path(__file__).resolve().parents[1]


def escape(value):
    return html.escape(str(value), quote=True)


def data_uri(path):
    mime = mimetypes.guess_type(str(path))[0] or 'application/octet-stream'
    return 'data:' + mime + ';base64,' + base64.b64encode(path.read_bytes()).decode('ascii')


def local_asset(out, relative):
    path = out / relative
    if path.is_symlink() or not path.resolve().is_relative_to(out.resolve()):
        raise ValueError('Attachment path escapes the export directory')
    return path


def render_archive(data, out):
    zone = ZoneInfo(data['export']['timezone'])
    attachments = {a['index']: a for a in data['export']['attachments']}
    rows, plain = [], []
    days = set()
    senders = sorted({m.get('sender') or '系统' for m in data['messages']})
    previous = None
    for index, message in enumerate(data['messages'], 1):
        stamp = dt.datetime.fromtimestamp(message['timestamp'], zone)
        day = stamp.strftime('%Y-%m-%d')
        days.add(day)
        sender = message.get('sender') or '系统'
        body = message.get('content', '')
        raw = message.get('original', {}).get('message_content')
        node = xml_root(raw)
        links = []
        if message.get('appmsg_type') == 57 and node is not None:
            body = quoted_text(raw)
        if node is not None:
            app = node.find('.//appmsg')
            if app is not None and message.get('appmsg_type') == 5:
                for key in ['url', 'lowurl']:
                    value = app.findtext(key)
                    if value and value.startswith(('https://', 'http://')) and value not in links:
                        links.append(value)
                description = app.findtext('des')
                if description and description not in body:
                    body += '\n' + description
        url = message.get('url')
        if url and url.startswith(('https://', 'http://')) and url not in links:
            links.append(url)
        content = '<div class="body">' + escape(body) + '</div>'
        for url in links:
            content += '<a class="link" href="' + escape(url) + '" target="_blank" rel="noopener noreferrer">打开分享链接</a>'
        attachment = attachments.get(index)
        if attachment and attachment.get('preview_file'):
            asset = local_asset(out, attachment['preview_file'])
            if attachment['kind'] == 'image':
                content += '<a class="picture" href="#" download="' + escape(asset.name) + '"><img loading="lazy" src="' + data_uri(asset) + '" alt="消息 ' + str(index) + ' 的图片"></a>'
            elif attachment['kind'] == 'voice':
                content += '<div class="audio"><audio controls preload="none" src="' + data_uri(asset) + '"></audio><span>' + str(round(attachment.get('duration_seconds', 0), 1)) + ' 秒</span></div>'
        if attachment and attachment.get('original_file') and (attachment['kind'] == 'file' or not attachment.get('preview_file')):
            asset = local_asset(out, attachment['original_file'])
            name = attachment.get('name') or asset.name
            content += '<a class="file" href="' + data_uri(asset) + '" download="' + escape(name) + '">📎 下载 ' + escape(name) + '</a>'
        if attachment and attachment.get('warning'):
            content += '<span class="hint">附件状态：' + escape(attachment['warning']) + '</span>'
        if message.get('type_id') == 'sticker':
            content += '<span class="hint">表情记录已保留；表情图片本体未导出。</span>'
        if day != previous:
            rows.append('<h2 class="day" id="day-' + day + '">' + day + '</h2>')
            previous = day
        rows.append('<article class="message" id="msg-' + str(index) + '" data-day="' + day + '" data-sender="' + escape(sender) + '"><div class="meta"><strong>' + escape(sender) + '</strong><a href="#msg-' + str(index) + '"><time>' + stamp.strftime('%H:%M:%S %z') + '</time></a><span class="number">#' + str(index) + '</span></div>' + content + '</article>')
        message['export_text'] = body
        plain.append(f'[{stamp:%Y-%m-%d %H:%M:%S %z}] {sender}\n{body}' + ''.join('\n' + link for link in links) + ('\n附件：' + str(attachment.get('preview_file') or attachment.get('original_file') or attachment['status']) if attachment else '') + '\n')
    count = len(data['messages'])
    participants = len({m.get('sender_username') or m.get('sender') for m in data['messages'] if m.get('sender')})
    media_counts = collections.Counter(a['kind'] for a in attachments.values() if a['status'] == 'exported')
    data['export']['coverage'] = {'messages': count, 'participants': participants, 'media': dict(media_counts),
                                  'sticker_images_exported': False, 'recalled_content_recovered': False}
    start, end = data['export']['start'], data['export']['end']
    start_text = dt.datetime.fromtimestamp(start, zone).isoformat() if start else '全部本机历史'
    end_text = dt.datetime.fromtimestamp(end, zone).isoformat()
    window = start_text + ' — ' + end_text
    (out / 'messages.json').write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    (out / 'chat.txt').write_text(f'{data["chat"]}\n{window}\n{data["export"]["timezone"]}\n{count} 条消息\n\n' + '\n'.join(plain), encoding='utf-8')
    warnings = data['export']['warnings'] + [f'Missing database key: {name}' for name in data['export']['missing_shards']]
    values = {
        'TITLE': escape(data['chat']), 'WINDOW': escape(window), 'TIMEZONE': escape(data['export']['timezone']), 'COUNT': str(count),
        'BADGES': ''.join('<span class="badge">' + escape(value) + '</span>' for value in [f'{count} 条消息', f'{participants} 位参与者', f'{media_counts["image"]} 张图片', f'{media_counts["voice"]} 条语音', f'{media_counts["file"]} 个文件']),
        'SENDERS': ''.join('<option value="' + escape(sender) + '">' + escape(sender) + '</option>' for sender in senders),
        'DATES': ''.join('<option>' + day + '</option>' for day in sorted(days)),
        'MESSAGES': '\n'.join(rows), 'WARNINGS': ''.join('<p class="note">' + escape(w) + '</p>' for w in warnings),
    }
    template = (ROOT / 'assets/chat_archive.html').read_text(encoding='utf-8')
    rendered = re.sub(r'\{\{([A-Z_]+)\}\}', lambda match: values[match[1]], template)
    (out / 'chat.html').write_text(rendered, encoding='utf-8')
    manifest = {'chat': data['chat'], 'window': window, 'timezone': data['export']['timezone'], 'messages': count,
                'attachments': data['export']['attachments'], 'warnings': warnings, 'files': []}
    for path in sorted(out.rglob('*')):
        if path.is_file() and path.name != 'manifest.json':
            manifest['files'].append({'path': str(path.relative_to(out)), 'bytes': path.stat().st_size,
                                      'sha256': hashlib.sha256(path.read_bytes()).hexdigest()})
    (out / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    archive = out.parent / (out.name + '.zip')
    if archive.exists():
        raise FileExistsError('Archive already exists; refusing to replace it')
    with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as stream:
        for path in sorted(out.rglob('*')):
            if path.is_file():
                stream.write(path, str(path.relative_to(out.parent)))
    with zipfile.ZipFile(archive) as stream:
        if stream.testzip() is not None:
            raise RuntimeError('Archive integrity check failed')
    return {'html': str(out / 'chat.html'), 'json': str(out / 'messages.json'),
            'text': str(out / 'chat.txt'), 'zip': str(archive)}
