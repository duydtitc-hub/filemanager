import re,sys
src=open('convert_stt.py','r',encoding='utf-8').read()
#m = re.search(r"def _parse_srt_timestamp_to_seconds\([^\)]*\):", src)
m = re.search(r"def _parse_srt_timestamp_to_seconds\(ts: str\) -> float:\n", src)
if not m:
    print('parser function header not found')
    sys.exit(1)
start = m.start()
rest = src[start:]
# find next top-level def (starts at column 0)
next_def = re.search(r"\ndef \w+\(", rest)
if next_def:
    func_text = rest[:next_def.start()]
else:
    func_text = rest
# Execute only the function definition in an isolated namespace
ns = {}
exec(func_text, ns)
parse = ns.get('_parse_srt_timestamp_to_seconds')
if not parse:
    print('failed to load parser')
    sys.exit(1)
# Test canonical timestamps
cases = ['00:01:00,720','00:01:01,360']
for c in cases:
    try:
        print(c,'->',parse(c), flush=True)
    except Exception as e:
        print(c,'-> ERROR',e, flush=True)
