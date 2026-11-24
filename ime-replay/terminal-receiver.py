import json
from pathlib import Path
import sys
from threading import Thread
import time

out = Path(sys.argv[1])
out.touch()

def render_status():
    counter = 0
    while True:
        # One bounded status line at 50 Hz keeps the terminal updating.
        print(f"\x1b[s\x1b[1;1Hfixture update {counter:06d}\x1b[u", end="", flush=True)
        counter += 1
        time.sleep(.02)

if "--output-load" in sys.argv:
    Thread(target=render_status, daemon=True).start()

print("IME receiver ready.", flush=True)
with out.open("w", encoding="utf-8") as stream:
    for line in sys.stdin:
        text = line.rstrip("\r\n")
        if not text:
            continue
        stream.write(json.dumps(text) + "\n")
        stream.flush()
