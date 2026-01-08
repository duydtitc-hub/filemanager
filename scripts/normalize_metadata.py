import os
import json
import glob
from urllib.parse import quote_plus
from datetime import datetime

OUTPUT_DIR_TOKEN = 'tiktokad'
DOWNLOAD_HOST = 'https://sandbox.travel.com.vn/api/download-video'

# NOTE: keep compatibility with Python <3.9 typing in some environments

def to_project_relative_posix(p: str) -> str:
    if not p:
        return ''
    p = p.replace('\\', '/').replace('\\\\', '/')
    lower = p.lower()
    idx = lower.find(OUTPUT_DIR_TOKEN)
    if idx >= 0:
        return p[idx:]
    # fallback: if path already starts with OUTPUT_DIR_TOKEN
    parts = p.split('/')
    if parts and parts[0] == OUTPUT_DIR_TOKEN:
        return p
    # final fallback: strip drive letters and leading slashes
    # keep last two path segments if nothing else
    return p.lstrip('/\\')

def build_urls(posix_path: str) -> tuple[str, str]:
    q = quote_plus(posix_path)
    view = f"{DOWNLOAD_HOST}?video_name={q}"
    download = f"{DOWNLOAD_HOST}?download=1&video_name={q}"
    return view, download

def normalize_metadata_file(path: str) -> bool:
    changed = False
    with open(path, 'r', encoding='utf-8') as f:
        try:
            data = json.load(f)
        except Exception:
            print(f"Skipping non-json or unreadable file: {path}")
            return False

    final_video = data.get('final_video') or data.get('final_video_path') or ''
    posix = to_project_relative_posix(final_video)
    if not posix:
        # If final_video missing, try to infer from other fields
        # nothing to do
        return False

    # Build correct URLs
    view_url, download_url = build_urls(posix)

    # If existing URLs contain encoded backslashes (%5C) or final_video had backslashes
    existing_view = data.get('view_url', '')
    existing_download = data.get('download_url', '')
    if ('%5C' in existing_view) or ('%5C' in existing_download) or ('\\' in str(final_video)):
        # backup original
        bak = path + '.bak.' + datetime.now().strftime('%Y%m%d%H%M%S')
        try:
            with open(bak, 'w', encoding='utf-8') as bf:
                json.dump(data, bf, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"Warning: failed to write backup for {path}: {e}")

        data['final_video'] = posix
        data['view_url'] = view_url
        data['download_url'] = download_url
        try:
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            changed = True
            print(f"Updated: {path} -> view_url uses posix path: {posix}")
        except Exception as e:
            print(f"Failed to write updated metadata for {path}: {e}")

    return changed

def main():
    meta_glob = os.path.join(OUTPUT_DIR_TOKEN, 'metadata_*.json')
    files = glob.glob(meta_glob)
    if not files:
        print('No metadata files found at', meta_glob)
        return

    updated = 0
    for f in files:
        try:
            if normalize_metadata_file(f):
                updated += 1
        except Exception as e:
            print(f"Error processing {f}: {e}")

    print(f"Normalization complete. Files scanned: {len(files)}, updated: {updated}")

if __name__ == '__main__':
    main()
