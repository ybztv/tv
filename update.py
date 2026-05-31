import requests
import re

# 1. 你要抓取的源（可加多个）
urls = [
    "https://raw.githubusercontent.com/xxx/korea.m3u8",  # 韩源
    "https://raw.githubusercontent.com/xxx/****3u8"      # 央视卫视
]

# 2. 合并、去重
channels = []
for url in urls:
    r = requests.get(url, timeout=10)
    r.raise_for_status()
    lines = r.text.splitlines()
    for line in lines:
        if line.startswith("#") or line in channels:
            continue
        channels.append(line)

# 3. 生成 m3u8
m3u8 = "#EXTM3U\n"
m3u8 += "#EXT-X-VERSION:3\n"
for ch in channels:
    if ch.startswith("http"):
        m3u8 += f"#EXTINF:-1,Channel\n{ch}\n"

# 4. 保存文件
with open("live.m3u8", "w", encoding="utf-8") as f:
    f.write(m3u8)

print("✅ 生成完成：live.m3u8")
