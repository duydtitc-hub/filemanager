import base64
import json
import os
import time
import urllib.request

IMAGE_PATH = r"e:\TTSDocker\temp_images\f7a4a674-526b-416e-8e86-f65e6079b8ca.jpg"
URL = "http://127.0.0.1:8000/tiktok_ad/create_from_base64"
STATUS_URL_TEMPLATE = "http://127.0.0.1:8000/tiktok_ad/status/{task_id}"

with open(IMAGE_PATH, 'rb') as f:
    img_b64 = base64.b64encode(f.read()).decode('utf-8')

body = {
    "image_base64": img_b64,
    "prompt_text": "Đầm gân tăm ôm body phối cổ sơ mi. Mẫu sinh dáng đẹp eo thon",
    "style": "fashion",
    "bg_choice": "Khituonglaimoho.wav",
    "skip_tts": True
}

req = urllib.request.Request(URL, data=json.dumps(body).encode('utf-8'), headers={"Content-Type": "application/json"})
print('Posting create request...')
try:
    resp = urllib.request.urlopen(req, timeout=30)
    data = json.load(resp)
    print('Create response:')
    print(json.dumps(data, ensure_ascii=False, indent=2))
    task_id = data.get('task_id') or data.get('id') or data.get('task')
    if not task_id:
        print('No task_id returned by create endpoint, aborting.')
        raise SystemExit(1)
except Exception as e:
    print('Create request failed:', e)
    raise

# Poll status
status_url = STATUS_URL_TEMPLATE.format(task_id=task_id)
print(f'Polling status at: {status_url}')
final_status = None
for i in range(60):
    try:
        r = urllib.request.urlopen(status_url, timeout=15)
        s = json.load(r)
        st = s.get('status')
        print(f'[{i+1}] status={st}')
        print(json.dumps(s, ensure_ascii=False))
        if st in ('completed', 'error'):
            final_status = s
            break
    except Exception as e:
        print(f'[{i+1}] poll error: {e}')
    time.sleep(5)

if not final_status:
    print('Status poll timed out')
else:
    print('Final status:')
    print(json.dumps(final_status, ensure_ascii=False, indent=2))

# Inspect tiktokad folder
OUT_DIR = r"e:\TTSDocker\tiktokad"
print('\nListing tiktokad top-level entries:')
try:
    entries = os.listdir(OUT_DIR)
    entries = sorted(entries)
    for e in entries:
        print('-', e)
except Exception as e:
    print('Cannot list tiktokad:', e)

# Find latest metadata file
meta_files = []
for root, dirs, files in os.walk(OUT_DIR):
    for fn in files:
        if fn.startswith('metadata_') and fn.endswith('.json'):
            meta_files.append(os.path.join(root, fn))
meta_files.sort(key=lambda p: os.path.getmtime(p) if os.path.exists(p) else 0, reverse=True)
if meta_files:
    latest = meta_files[0]
    print('\nLatest metadata file:', latest)
    try:
        with open(latest, 'r', encoding='utf-8') as f:
            print(f.read()[:4000])
    except Exception as e:
        print('Error reading metadata:', e)
else:
    print('\nNo metadata_*.json files found in tiktokad')

# If session id returned in final_status, show folder contents
session_id = None
if final_status:
    session_id = final_status.get('session_id') or final_status.get('result', {}).get('session_id')
if session_id:
    sess_folder = os.path.join(OUT_DIR, session_id)
    print('\nSession folder:', sess_folder)
    try:
        for root, dirs, files in os.walk(sess_folder):
            for fn in files:
                print('-', os.path.join(root, fn))
    except Exception as e:
        print('Cannot list session folder:', e)
else:
    print('\nNo session_id found in final status; cannot inspect specific session folder.')
