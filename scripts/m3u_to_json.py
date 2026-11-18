# -*- coding: utf-8 -*-
"""M3U -> kenpark76 同款 JSON 频道列表格式。

输出结构（与 kenpark76/koreatv.json 完全一致）：
[
  {
    "group": "...", "logo": "...", "name": "...", "title": "...",
    "uris": ["..."],
    "headers": {"user-agent": "..."}   # 无 UA 时省略
  }
]
"""
import json
import re

ATTR_RE = re.compile(r'([\w-]+)\s*=\s*"([^"]*)"')
EMOJI_RE = re.compile('[\U0001F000-\U0001FAFF\u2600-\u27BF\uFE0F\u200D\u2B00-\u2BFF]')
URL_OK = re.compile(r'^(https?|rtmp|rtsp)://', re.I)


def parse_m3u(text):
    items, pending = [], None
    for raw in text.splitlines():
        line = raw.strip().lstrip('\ufeff')
        if not line:
            continue
        if line.upper().startswith('#EXTINF'):
            attrs = dict(ATTR_RE.findall(line))
            name = line.split(',', 1)[1].strip() if ',' in line else ''
            pending = {'attrs': attrs, 'name': name, 'ua': ''}
            continue
        if line.upper().startswith('#EXTVLCOPT'):
            if pending and 'http-user-agent' in line:
                pending['ua'] = line.split('=', 1)[1].strip()
            continue
        if line.startswith('#'):
            continue
        if pending is not None:
            items.append((pending['attrs'], pending['name'], line.strip(), pending['ua']))
            pending = None
    return items


def build(m3u_text, keep_order=True):
    seen, out = set(), []
    for attrs, name, url, ua in parse_m3u(m3u_text):
        if not name or not URL_OK.match(url):
            continue
        key = re.sub(r'\s', '', url).lower()
        if key in seen:
            continue
        seen.add(key)

        group = EMOJI_RE.sub('', attrs.get('group-title', '')).strip() or '未分类'
        item = {
            'group': group,
            'logo': attrs.get('tvg-logo', '').strip(),
            'name': name,
            'title': name,
            'uris': [url],
        }
        if ua:
            item['headers'] = {'user-agent': ua}
        out.append(item)

    if keep_order:
        order, ranked = [], []
        for it in out:
            if it['group'] not in order:
                order.append(it['group'])
            ranked.append(it)
        out = sorted(ranked, key=lambda x: order.index(x['group']))

    text = json.dumps(out, ensure_ascii=False, indent='\t') + '\n'
    return text, len(out)
