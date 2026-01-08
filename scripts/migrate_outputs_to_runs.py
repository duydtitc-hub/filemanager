#!/usr/bin/env python3
import os
import shutil
import json
import sys
# Ensure project root is on sys.path so we can import config
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)
from config import OUTPUT_DIR

REPORT = []

def find_existing_runs(outputs_dir):
    return [d for d in os.listdir(outputs_dir) if os.path.isdir(os.path.join(outputs_dir, d))]


def determine_target_run(filename, existing_runs):
    # If file clearly contains _Tap_ pattern
    if "_Tap_" in filename:
        return filename.split("_Tap_")[0]
    # Prefer exact match prefix with existing runs
    for r in existing_runs:
        if filename.startswith(r + "_") or filename.startswith(r + ".") or filename.startswith(r):
            return r
    # fallback: use part before first underscore
    if "_" in filename:
        return filename.split("_")[0]
    # fallback: use name before first dot
    return filename.split(".")[0]


def migrate():
    outputs = OUTPUT_DIR
    moved = []
    skipped = []
    existing_runs = find_existing_runs(outputs)
    for name in os.listdir(outputs):
        path = os.path.join(outputs, name)
        # skip directories (they are run dirs)
        if os.path.isdir(path):
            continue
        # skip hidden files
        if name.startswith('.') or name.endswith('.fx.log') or name.endswith('.fx.err.log'):
            continue
        target = determine_target_run(name, existing_runs)
        if not target:
            skipped.append(name)
            continue
        target_dir = os.path.join(outputs, target)
        try:
            os.makedirs(target_dir, exist_ok=True)
            dest = os.path.join(target_dir, name)
            # Avoid overwriting existing files
            if os.path.exists(dest):
                # if identical size, skip; else rename with suffix
                if os.path.getsize(dest) == os.path.getsize(path):
                    skipped.append(name)
                    continue
                else:
                    base, ext = os.path.splitext(name)
                    i = 1
                    while True:
                        new_name = f"{base}.migrated.{i}{ext}"
                        new_dest = os.path.join(target_dir, new_name)
                        if not os.path.exists(new_dest):
                            dest = new_dest
                            break
                        i += 1
            shutil.move(path, dest)
            moved.append({'file': name, 'to': target, 'dest': dest})
        except Exception as e:
            skipped.append({'file': name, 'error': str(e)})
    report = {'moved': moved, 'skipped': skipped}
    with open(os.path.join(outputs, 'migrate_report.json'), 'w', encoding='utf-8') as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    return report


if __name__ == '__main__':
    r = migrate()
    print('Migration complete.')
    print('Moved:', len(r['moved']), 'Skipped:', len(r['skipped']))
    print('Report saved to', os.path.join(OUTPUT_DIR, 'migrate_report.json'))
