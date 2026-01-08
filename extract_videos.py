#!/usr/bin/env python3
"""
Simple extractor for Tencent video links from HTML.

Usage:
  python extract_videos.py input.html
  cat input.html | python extract_videos.py

Outputs unique URLs like:
  https://v.qq.com/x/cover/<cid>/<vid>.html
or
  https://v.qq.com/x/page/<vid>.html
"""
import sys
import re

def extract_links(html: str):
    urls = []
    seen = set()
    # Find tags that contain data-vid
    for m in re.finditer(r'<[^>]*data-vid="([^"]+)"[^>]*>', html, flags=re.IGNORECASE):
        tag = m.group(0)
        vid = m.group(1)
        cid_m = re.search(r'data-cid="([^"]+)"', tag)
        cid = cid_m.group(1) if cid_m else ''
        if cid:
            url = f'https://v.qq.com/x/cover/{cid}/{vid}.html'
        else:
            url = f'https://v.qq.com/x/page/{vid}.html'
        if url not in seen:
            seen.add(url)
            urls.append((vid, cid, url))
    return urls

def main():
    if len(sys.argv) > 1:
        path = sys.argv[1]
        with open(path, 'r', encoding='utf-8', errors='ignore') as f:
            html = f.read()
    else:
        html = sys.stdin.read()

    results = extract_links(html)
    if not results:
        print('No video links found.', file=sys.stderr)
        sys.exit(1)

    for vid, cid, url in results:
        if cid:
            print(f'{url}  (vid={vid} cid={cid})')
        else:
            print(f'{url}  (vid={vid})')

if __name__ == '__main__':
    main()
