# -*- coding: utf-8 -*-
"""
采集 krtv322/kortv 的 ktv.m3u，整理成标准纯 M3U，再推送到自己的 GitHub 仓库。

用法：
  python sync_ktv.py            # 正常同步（需要 Token）
  python sync_ktv.py --dry-run  # 只采集+转换，生成本地文件，不推送

配置：同目录 sync_config.json
{
  "owner": "ybztv",
  "repo":  "tv",
  "branch": "main",
  "path":  "ktv.m3u",
  "token": "ghp_xxx",          # 或改用环境变量 GITHUB_TOKEN
  "create_repo_if_missing": true,
  "source": "https://raw.githubusercontent.com/krtv322/kortv/main/ktv.m3u"
}
"""
import base64
import json
import os
import re
import sys
import urllib.error
import urllib.request
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
CONF = os.path.join(HERE, 'sync_config.json')
LOG = os.path.join(HERE, 'sync_ktv.log')

ATTR_RE = re.compile(r'([\w-]+)\s*=\s*"([^"]*)"')
URL_OK = re.compile(r'^(https?|rtmp|rtsp|mms|udp|rtp)://', re.I)
EMOJI_RE = re.compile('[\U0001F000-\U0001FAFF\u2600-\u27BF\uFE0F\u200D\u2B00-\u2BFF]')
API = 'https://api.github.com'


def log(msg):
    line = f'[{datetime.now():%Y-%m-%d %H:%M:%S}] {msg}'
    print(line)
    try:
        with open(LOG, 'a', encoding='utf-8') as f:
            f.write(line + '\n')
    except OSError as e:
        print(f'(日志写入失败：{e})')


def load_conf():
    if not os.path.exists(CONF):
        return {}
    with open(CONF, 'r', encoding='utf-8-sig') as f:
        return json.load(f)


def http(url, method='GET', data=None, token=None, timeout=40):
    body = json.dumps(data).encode() if data is not None else None
    req = urllib.request.Request(url, data=body, method=method)
    req.add_header('User-Agent', 'kortv-sync/1.0')
    req.add_header('Accept', 'application/vnd.github+json')
    if body:
        req.add_header('Content-Type', 'application/json')
    if token:
        req.add_header('Authorization', f'token {token}')
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read()
            ctype = r.headers.get('Content-Type', '')
            if 'json' in ctype:
                return r.status, json.loads(raw.decode('utf-8'))
            return r.status, raw.decode('utf-8', 'replace')
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode('utf-8', 'replace')
    except Exception as e:  # 网络错误等
        return 0, str(e)


def fetch_source(url):
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    with urllib.request.urlopen(req, timeout=40) as r:
        return r.read().decode('utf-8-sig', 'replace')


def normalize(text):
    """M3U -> 标准纯 M3U：单一 #EXTM3U 头、属性顺序统一、无效项剔除、按链接去重。"""
    items = []
    pending = None
    for raw in text.splitlines():
        line = raw.strip().lstrip('\ufeff')
        if not line:
            continue
        if line.upper().startswith('#EXTINF'):
            attrs = dict(ATTR_RE.findall(line))
            name = line.split(',', 1)[1].strip() if ',' in line else ''
            pending = (attrs, name)
            continue
        if line.startswith('#'):
            continue
        if pending is not None:
            items.append((pending[0], pending[1], line.strip()))
            pending = None

    seen, out = set(), []
    for attrs, name, url in items:
        if not name or not URL_OK.match(url):
            continue
        key = re.sub(r'\s', '', url).lower()
        if key in seen:
            continue
        seen.add(key)

        group = EMOJI_RE.sub('', attrs.get('group-title', '')).strip() or '한국방송'
        tvg_id = attrs.get('tvg-id', '').strip()
        tvg_name = attrs.get('tvg-name', '').strip() or name
        logo = attrs.get('tvg-logo', '').strip()

        parts = ['#EXTINF:-1']
        if tvg_id:
            parts.append(f'tvg-id="{tvg_id}"')
        parts.append(f'tvg-name="{tvg_name}"')
        if logo:
            parts.append(f'tvg-logo="{logo}"')
        parts.append(f'group-title="{group}"')
        out.append(' '.join(parts) + ',' + name)
        out.append(url)

    return '#EXTM3U\n' + '\n'.join(out) + '\n', len(out) // 2


def main():
    conf = {
        'owner': 'ybztv',
        'repo': 'tv',
        'branch': 'main',
        'path': 'ktv.m3u',
        'source': 'https://raw.githubusercontent.com/krtv322/kortv/main/ktv.m3u',
        'create_repo_if_missing': False,
    }
    conf.update(load_conf())
    token = os.environ.get('GITHUB_TOKEN') or conf.get('token') or ''
    dry = '--dry-run' in sys.argv

    log('开始同步')
    try:
        raw = fetch_source(conf['source'])
    except Exception as e:
        log(f'采集失败：{e}')
        return 2
    content, count = normalize(raw)
    local_path = os.path.join(HERE, 'ktv.m3u')
    with open(local_path, 'w', encoding='utf-8', newline='\n') as f:
        f.write(content)
    log(f'采集完成：{len(raw)} 字节 -> 标准 M3U {count} 个频道，已存 {local_path}')

    if dry:
        log('dry-run：不推送')
        return 0

    if not token:
        log('缺少 Token（sync_config.json 的 token 或环境变量 GITHUB_TOKEN），跳过推送')
        return 3

    api_repo = f'{API}/repos/{conf["owner"]}/{conf["repo"]}'

    # 仓库不存在且允许创建时先创建
    st, body = http(api_repo, token=token)
    if st == 404 and conf.get('create_repo_if_missing'):
        st2, body2 = http(f'{API}/user/repos', 'POST',
                          {'name': conf['repo'], 'private': True, 'auto_init': True}, token)
        log(f'创建仓库 {conf["repo"]}：HTTP {st2}')
        if st2 not in (200, 201):
            log(f'创建失败：{body2}')
            return 4
        st, body = http(api_repo, token=token)
    if st != 200:
        log(f'仓库不可用（HTTP {st}）：{body}')
        return 4

    default_branch = body.get('default_branch') or conf['branch']
    branch = conf['branch'] if conf['branch'] != 'main' else default_branch

    # 读取远端现有文件，比对是否需要更新
    path = conf['path']
    st, remote = http(f'{api_repo}/contents/{path}?ref={branch}', token=token)
    if st == 200 and isinstance(remote, dict):
        old = base64.b64decode(remote['content']).decode('utf-8', 'replace')
        if old.strip() == content.strip():
            log('远端内容与本地一致，无需提交')
            return 0
        sha = remote['sha']
        log('远端文件存在且已变化，准备更新')
    elif st == 404:
        sha = None
        log('远端文件不存在，准备新建')
    else:
        log(f'读取远端文件失败（HTTP {st}）：{remote}')
        return 5

    payload = {
        'message': f'chore: 同步 ktv.m3u（{datetime.now():%Y-%m-%d %H:%M}，{count} 个频道）',
        'content': base64.b64encode(content.encode('utf-8')).decode(),
        'branch': branch,
    }
    if sha:
        payload['sha'] = sha
    st, res = http(f'{api_repo}/contents/{path}', 'PUT', payload, token)
    if st in (200, 201):
        log(f'推送成功：{conf["owner"]}/{conf["repo"]}@{branch}/{path}（{count} 个频道）')
        return 0
    log(f'推送失败（HTTP {st}）：{res}')
    return 6


if __name__ == '__main__':
    sys.exit(main())
