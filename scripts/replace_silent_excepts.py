import re
from pathlib import Path

p = Path(r"e:\TTSDocker\app.py")
text = p.read_text(encoding='utf-8')

# Create backup
bak = p.with_suffix('.py.bak')
if not bak.exists():
    bak.write_text(text, encoding='utf-8')

# Pattern: capture leading indent then 'except Exception:' then newline then same indent + optional spaces then 'pass'
pattern = re.compile(r"(?m)^(?P<indent>[ \t]*)except Exception:\s*\n(?P=indent)[ \t]*pass\s*$")

def repl(m):
    indent = m.group('indent')
    return f"{indent}except Exception as e:\n{indent}    _report_and_ignore(e, \"ignored\")"

new_text, n = pattern.subn(repl, text)
if n:
    p.write_text(new_text, encoding='utf-8')
    print(f"Replaced {n} silent except(s) in {p}")
else:
    print("No matches found.")
