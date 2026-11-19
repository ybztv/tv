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

GITEE_API = 'https://gitee.com/api/v5'

HERE = os.path.dirname(os.path.abspath(__file__))
CONF_PATH = os.path.join(HERE, 'sync_config.json')


def load_module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _find(name):
    for p in (os.path.join(HERE, name),
              os.path.join(HERE, 'kenpark', name)):
        if os.path.exists(p):
            return p
    raise FileNotFoundError(name)


KOREA = load_module(_find('koreatv_to_m3u.py'), 'koreatv_to_m3u')
M2J = load_module(_find('m3u_to_json.py'), 'm3u_to_json')


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
    if job['type'] == 'm3u_to_json':
        ref = ''
        if job.get('reference'):
            try:
                ref = fetch(job['reference'])
            except Exception as e:
                log(f'  参考文件抓取失败，改用规则分组：{e}')
        text, st = M2J.build(fetch(src), ref, job.get('default_ua', ''))
        return text.encode('utf-8'), (
            f"{st['channels']} 个频道（JSON，沿用原文分组 {st['ref_matched']} 条，"
            f"headers {st['with_headers']} 条）")
    if job['type'] == 'json_norm':
        text, st = M2J.build_from_json(fetch(src), job.get('default_ua', ''),
                                       job.get('sort_by_group', False))
        return text.encode('utf-8'), (
            f"{st['channels']} 条（JSON 规范化，headers {st['with_headers']} 条）")
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


def push_gitee(gcfg, path, content, note):
    """把同一份内容推到 Gitee。gcfg: {owner, repo, branch}；token 取环境变量 GITEE_TOKEN 或配置。"""
    token = os.environ.get('GITEE_TOKEN') or gcfg.get('token', '')
    if not token:
        return True  # 未配置 Gitee，跳过
    api_repo = f'{GITEE_API}/repos/{gcfg["owner"]}/{gcfg["repo"]}'
    branch = gcfg.get('branch', 'master')
    st, remote = http(f'{api_repo}/contents/{path}?ref={branch}&access_token={token}', timeout=180)
    sha = None
    if st == 200 and isinstance(remote, dict):
        try:
            old = base64.b64decode(remote.get('content') or '')
        except Exception:
            old = b''
        if old == content:
            log(f'  [Gitee] {path} 无变化，跳过')
            return True
        sha = remote.get('sha')
    payload = {
        'content': base64.b64encode(content).decode(),
        'message': f'sync {path} @{datetime.now():%Y-%m-%d %H:%M:%S}',
        'branch': branch,
        'access_token': token,
    }
    method = 'GET'
    if sha:
        payload['sha'] = sha
        st, res = http(f'{api_repo}/contents/{path}', 'PUT', payload, timeout=240)
    else:
        st, res = http(f'{api_repo}/contents/{path}', 'POST', payload, timeout=240)
    if st in (200, 201):
        log(f'  [Gitee] {path} 推送成功（{note}）')
        return True
    log(f'  [Gitee] {path} 推送失败（HTTP {st}）：{res}')
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
        if cfg.get('gitee'):
            ok_all = push_gitee(cfg['gitee'], job['path'], text, note) and ok_all

    log('===== 同步结束 =====')
    return 0 if ok_all else 1


if __name__ == '__main__':
    sys.exit(main())
