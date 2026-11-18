# -*- coding: utf-8 -*-
"""M3U -> kenpark76 同款 JSON 频道列表格式（分组命名、headers 写法完全对齐）。

build(m3u_text, reference_json=None, default_ua='') -> (json_text, stats)
  reference_json: 原文 koreatv.json 文本，同名频道直接沿用它的分组
  default_ua    : 源里没有 UA 时补的默认 UA（对齐原文“每条都有 headers”）
"""
import json
import re

ATTR_RE = re.compile(r'([\w-]+)\s*=\s*"([^"]*)"')
EMOJI_RE = re.compile('[\U0001F000-\U0001FAFF\u2600-\u27BF\uFE0F\u200D\u2B00-\u2BFF]')
URL_OK = re.compile(r'^(https?|rtmp|rtsp)://', re.I)

NO_LOGO = 'https://buddytv.netlify.app/img/no-logo.png'

GROUP_ORDER = [    '한국-지상파', '한국-종합편성', '한국-기타', '한국-영화',
    '中国-央视', '中国-卫视', '中国-港台', 'ENGLISH',
]

BROADCAST = ('kbs', 'sbs', 'mbc', 'ebs', 'obs', 'tbs', 'arirang', '阿里郎')
GENERAL = ('jtbc', 'tvn', 'mbn', '채널a', 'channela', '조선', 'chosun', 'ytn', '연합')
CTV = ('cctv', 'cgtn', '央视')
HK_TW = ('tvb', '中天', '東森', '东森', '凤凰', '鳳凰', '澳门', '澳視', '香港', '台湾',
         '台灣', '民视', '民視', '华视', '華視', '台视', '台視', '中视', '中視', '寰宇',
         'tvbs', 'simp', 'now')


def map_group(orig, name, ref):
    key = name.strip().lower()
    if key in ref:
        return ref[key]
    n = re.sub(r'\s+', '', key)
    if any(k in n for k in CTV):
        return '中国-央视'
    if any(k in key for k in HK_TW):
        return '中国-港台'
    if orig and ('중국' in orig or re.search('[\u4e00-\u9fff]', name)):
        return '中国-卫视'
    if any(k in n for k in GENERAL):
        return '한국-종합편성'
    if any(k in n for k in BROADCAST):
        return '한국-지상파'
    return '한국-기타'


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


def build(m3u_text, reference_json=None, default_ua=''):
    ref = {}
    if reference_json:
        for x in json.loads(reference_json):
            if x.get('name'):
                ref[x['name'].strip().lower()] = x.get('group', '')

    seen, out, matched = set(), [], 0
    for attrs, name, url, ua in parse_m3u(m3u_text):
        if not name or not URL_OK.match(url):
            continue
        key = re.sub(r'\s', '', url).lower()
        if key in seen:
            continue
        seen.add(key)

        orig = EMOJI_RE.sub('', attrs.get('group-title', '')).strip()
        group = map_group(orig, name, ref)
        if name.strip().lower() in ref:
            matched += 1

        item = {
            'group': group,
            'logo': attrs.get('tvg-logo', '').strip() or NO_LOGO,
            'name': name,
            'title': name,
            'uris': [url],
        }
        user_agent = ua or default_ua
        if user_agent:
            item['headers'] = {'user-agent': user_agent}
        out.append(item)

    idx = {g: i for i, g in enumerate(GROUP_ORDER)}
    out.sort(key=lambda x: idx.get(x['group'], 99))
    text = json.dumps(out, ensure_ascii=False, indent='\t') + '\n'
    stats = {
        'channels': len(out),
        'ref_matched': matched,
        'with_headers': sum(1 for x in out if 'headers' in x),
        'groups': {g: sum(1 for x in out if x['group'] == g) for g in GROUP_ORDER
                   if any(x['group'] == g for x in out)},
    }
    return text, stats


def build_from_json(json_text, default_ua='', sort_by_group=False):
    """已有 JSON 频道列表 -> 同风格规范化 JSON（补齐 logo / headers，统一字段顺序）。"""
    data = json.loads(json_text)
    seen, out = set(), []
    for item in data:
        name = (item.get('name') or item.get('title') or '').strip()
        uris = [u.strip() for u in (item.get('uris') or []) if u and URL_OK.match(u.strip())]
        if not name or not uris:
            continue
        key = re.sub(r'\s', '', uris[0]).lower()
        if key in seen:
            continue
        seen.add(key)

        src_headers = item.get('headers') or {}
        headers = {'user-agent': (src_headers.get('user-agent') or '').strip() or default_ua}
        for k in ('cookie', 'referer', 'referrer', 'origin'):
            v = (src_headers.get(k) or '').strip()
            if v:
                headers[k] = v
        headers = {k: v for k, v in headers.items() if v}

        norm = {
            'group': (item.get('group') or '未分类').strip(),
            'logo': (item.get('logo') or '').strip() or NO_LOGO,
            'name': name,
            'title': (item.get('title') or name).strip(),
            'uris': uris,
        }
        if headers:
            norm['headers'] = headers
        out.append(norm)

    if sort_by_group:
        idx = {g: i for i, g in enumerate(GROUP_ORDER)}
        out.sort(key=lambda x: idx.get(x['group'], 99))

    text = json.dumps(out, ensure_ascii=False, indent='\t') + '\n'
    stats = {
        'channels': len(out),
        'with_headers': sum(1 for x in out if 'headers' in x),
        'groups': {g: sum(1 for x in out if x['group'] == g)
                   for g in sorted({x['group'] for x in out})},
    }
    return text, stats
