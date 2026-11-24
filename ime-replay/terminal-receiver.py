import json
from pathlib import Path
import sys

out = Path(sys.argv[1])
out.touch()
print("IME receiver ready.", flush=True)
with out.open("w", encoding="utf-8") as stream:
    for line in sys.stdin:
        text = line.rstrip("\r\n")
        if not text:
            continue
        stream.write(json.dumps(text) + "\n")
        stream.flush()
