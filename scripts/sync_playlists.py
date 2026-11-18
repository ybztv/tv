# -*- coding: utf-8 -*-
"""多源同步：按 sync_config.json 的 jobs 采集 -> 规范化 -> 推送到 GitHub。

job 类型：
  m3u          : 直接抓 M3U，做标准纯 M3U 规范化（复用 sync_ktv.normalize）
  json_koreatv : 抓 koreatv.json（+EPG），按频道对象转成标准纯 M3U

用法：
  python sync_playlists.py            # 正常同步
  python sync_playlists.py --dry-run  # 只生成文件，不推送
"""
import base64
import importlib.util
import json
import os
import sys
import urllib.request
from datetime import datetime

from sync_ktv import API, http, normalize, log

HERE = os.path.dirname(os.path.abspath(__file__))
CONF_PATH = os.path.join(HERE, 'sync_config.json')


def load_module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _find_converter():
    for p in (os.path.join(HERE, 'koreatv_to_m3u.py'),
              os.path.join(HERE, 'kenpark', 'koreatv_to_m3u.py')):
        if os.path.exists(p):
            return p
    raise FileNotFoundError('koreatv_to_m3u.py 未找到')


KOREA = load_module(_find_converter(), 'koreatv_to_m3u')


def fetch(url, timeout=60):
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode('utf-8-sig', 'replace')


def fetch_bytes(url, timeout=60):
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def render(job):
    """返回 (bytes 内容, 说明)；raw 类型原样搬运，其余转成标准 M3U"""
    src = job['source']
    if job['type'] == 'raw':
        data = fetch_bytes(src)
        return data, f'{len(data) / 1024:.0f} KB 原样同步'
    if job['type'] == 'json_koreatv':
        jtext = fetch(src)
        etext = ''
        if job.get('epg'):
            try:
                etext = fetch(job['epg'])
            except Exception as e:
                log(f'  EPG 抓取失败，跳过 tvg-id：{e}')
        text, st = KOREA.build(jtext, etext)
        return text.encode('utf-8'), f"{st['channels']} 个频道 / EPG 匹配 {st['epg_matched']}"
    text, count = normalize(fetch(src))
    return text.encode('utf-8'), f'{count} 个频道'


def push(cfg, job, content, note, token, branch):
    """content 为 bytes"""
    api_repo = f'{API}/repos/{cfg["owner"]}/{cfg["repo"]}'
    path = job['path']
    st, remote = http(f'{api_repo}/contents/{path}?ref={branch}', token=token)
    if st == 200 and isinstance(remote, dict):
        old = base64.b64decode(remote['content'])
        if old == content:
            log(f'  {path} 无变化，跳过提交')
            return True
        sha = remote['sha']
    elif st == 404:
        sha = None
    else:
        log(f'  {path} 读取失败（HTTP {st}）：{remote}')
        return False

    payload = {
        'message': f'chore: 同步 {path}（{datetime.now():%Y-%m-%d %H:%M}，{note}）',
        'content': base64.b64encode(content).decode(),
        'branch': branch,
    }
    if sha:
        payload['sha'] = sha
    st, res = http(f'{api_repo}/contents/{path}', 'PUT', payload, token)
    if st in (200, 201):
        log(f'  {path} 推送成功（{note}）')
        return True
    log(f'  {path} 推送失败（HTTP {st}）：{res}')
    return False


def main():
    dry = '--dry-run' in sys.argv
    with open(CONF_PATH, 'r', encoding='utf-8-sig') as f:
        cfg = json.load(f)
    token = os.environ.get('GITHUB_TOKEN') or cfg.get('token', '')

    log('===== 开始同步 =====')
    branch = cfg.get('branch', 'main')
    ok_all = True

    if not dry:
        if not token:
            log('缺少 Token，终止')
            return 3
        st, body = http(f'{API}/repos/{cfg["owner"]}/{cfg["repo"]}', token=token)
        if st != 200:
            log(f'仓库不可用（HTTP {st}）：{body}')
            return 4
        branch = body.get('default_branch') or branch

    for job in cfg.get('jobs', []):
        log(f'[{job["path"]}] 采集 {job["source"]}')
        try:
            text, note = render(job)
        except Exception as e:
            log(f'  采集/转换失败：{e}')
            ok_all = False
            continue
        local = os.path.join(HERE, job['path'])
        if os.path.dirname(job['path']):
            os.makedirs(os.path.dirname(local), exist_ok=True)
        with open(local, 'wb') as f:
            f.write(text)
        log(f'  处理完成：{note}，共 {len(text)} 字节 -> {local}')
        if dry:
            continue
        ok_all = push(cfg, job, text, note, token, branch) and ok_all

    log('===== 同步结束 =====')
    return 0 if ok_all else 1


if __name__ == '__main__':
    sys.exit(main())
