# -*- coding: utf-8 -*-
"""kenpark76 的 koreatv.json（JSON 频道列表）-> 标准纯 M3U。

输入：koreatv.json（[{group, logo, name, title, uris[], headers}]）
      koreatvEPG.xml（可选，用于补 tvg-id）
输出：koreatv.m3u（#EXTM3U + 每频道 #EXTINF + 地址；有 UA 时附 #EXTVLCOPT）

也可被 sync_playlists.py 复用：build(json_text, epg_text) -> (m3u_text, stats)
"""
import json
import os
import re
import sys
import xml.etree.ElementTree as ET

HERE = os.path.dirname(os.path.abspath(__file__))
JSON_PATH = os.path.join(HERE, 'koreatv.json')
EPG_PATH = os.path.join(HERE, 'koreatvEPG.xml')
OUT_PATH = os.path.join(HERE, 'koreatv.m3u')
EPG_URL = 'https://kenpark76.github.io/koreatvEPG.xml'

GROUP_ORDER = [
    '한국-지상파', '한국-종합편성', '한국-기타', '한국-영화',
    '中国-央视', '中国-卫视', '中国-港台', 'ENGLISH',
]
URL_OK = re.compile(r'^(https?|rtmp|rtsp)://', re.I)


def norm(s):
    return re.sub(r'[\s\-_.()\[\]]+', '', (s or '').lower())


def load_epg(epg_text):
    """display-name -> id"""
    if not epg_text:
        return {}
    try:
        root = ET.fromstring(epg_text)
    except Exception:
        return {}
    m = {}
    for ch in root.findall('channel'):
        cid = ch.get('id') or ''
        for d in ch.findall('display-name'):
            n = (d.text or '').strip()
            if n and n not in m:
                m[n] = cid
    return m


def build(json_text, epg_text=''):
    data = json.loads(json_text)
    epg = load_epg(epg_text)
    epg_norm = {}
    for n, cid in epg.items():
        epg_norm.setdefault(norm(n), cid)

    seen, entries = set(), []
    matched = 0
    for item in data:
        name = (item.get('name') or item.get('title') or '').strip()
        uris = [u.strip() for u in (item.get('uris') or []) if u and URL_OK.match(u.strip())]
        if not name or not uris:
            continue
        key = re.sub(r'\s', '', uris[0]).lower()
        if key in seen:
            continue
        seen.add(key)

        group = (item.get('group') or '未分类').strip()
        logo = (item.get('logo') or '').strip()
        tvg_id = epg.get(name) or epg_norm.get(norm(name)) or ''
        if tvg_id:
            matched += 1
        headers = item.get('headers') or {}
        ua = (headers.get('user-agent') or '').strip()

        parts = ['#EXTINF:-1']
        if tvg_id:
            parts.append(f'tvg-id="{tvg_id}"')
        parts.append(f'tvg-name="{name}"')
        if logo:
            parts.append(f'tvg-logo="{logo}"')
        parts.append(f'group-title="{group}"')

        block = [' '.join(parts) + ',' + name]
        for hkey, opt in (('user-agent', 'http-user-agent'),
                          ('referer', 'http-referrer'),
                          ('referrer', 'http-referrer'),
                          ('origin', 'http-origin'),
                          ('cookie', 'http-cookie')):
            val = (headers.get(hkey) or '').strip()
            if val:
                block.append(f'#EXTVLCOPT:{opt}={val}')
        block.extend(uris)
        entries.append((group, block))

    idx = {g: i for i, g in enumerate(GROUP_ORDER)}
    entries.sort(key=lambda x: idx.get(x[0], 99))

    if epg_text:
        lines = [f'#EXTM3U url-tvg="{EPG_URL}" x-tvg-url="{EPG_URL}"']
    else:
        lines = ['#EXTM3U']
    for _, block in entries:
        lines.extend(block)

    stats = {
        'source': len(data),
        'channels': len(entries),
        'epg_matched': matched,
        'groups': {g: sum(1 for gg, _ in entries if gg == g) for g, _ in
                   sorted(entries, key=lambda x: idx.get(x[0], 99))},
    }
    return '\n'.join(lines) + '\n', stats


def main():
    with open(JSON_PATH, 'r', encoding='utf-8-sig') as f:
        jtext = f.read()
    etext = ''
    if os.path.exists(EPG_PATH):
        with open(EPG_PATH, 'r', encoding='utf-8-sig') as f:
            etext = f.read()
    text, stats = build(jtext, etext)
    with open(OUT_PATH, 'w', encoding='utf-8', newline='\n') as f:
        f.write(text)
    print(f"源 {stats['source']} 条 -> 输出 {stats['channels']} 个频道")
    print(f"EPG 匹配 tvg-id：{stats['epg_matched']}/{stats['channels']}")
    print('分组：' + ', '.join(f'{g}({c})' for g, c in stats['groups'].items()))
    print('输出：' + OUT_PATH)
    return 0


if __name__ == '__main__':
    sys.exit(main())
