"""Exercise implicit Mozc commits in one editor without changing focus."""
import argparse
import ctypes as ct
from ctypes import wintypes as wt
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from threading import Event, Thread


class Keyboard(ct.Structure):
    _fields_ = [
        ("vk", wt.WORD), ("scan", wt.WORD), ("flags", wt.DWORD),
        ("time", wt.DWORD), ("extra", ct.c_size_t),
    ]


class Mouse(ct.Structure):
    _fields_ = [
        ("x", wt.LONG), ("y", wt.LONG), ("data", wt.DWORD),
        ("flags", wt.DWORD), ("time", wt.DWORD), ("extra", ct.c_size_t),
    ]


class Payload(ct.Union):
    _fields_ = [("keyboard", Keyboard), ("mouse", Mouse)]


class Input(ct.Structure):
    _fields_ = [("type", wt.DWORD), ("data", Payload)]


def replay(exe, out, lines, phrase, batch_count, output_load):
    user = ct.WinDLL("user32", use_last_error=True)
    user.GetForegroundWindow.restype = wt.HWND
    user.GetWindowThreadProcessId.argtypes = [wt.HWND, ct.POINTER(wt.DWORD)]
    user.SetForegroundWindow.argtypes = [wt.HWND]
    user.IsWindowVisible.argtypes = [wt.HWND]
    user.ShowWindow.argtypes = [wt.HWND, ct.c_int]
    user.GetWindowRect.argtypes = [wt.HWND, ct.POINTER(wt.RECT)]
    user.SetWindowPos.argtypes = [wt.HWND, wt.HWND, ct.c_int, ct.c_int, ct.c_int, ct.c_int, wt.UINT]
    user.GetClientRect.argtypes = [wt.HWND, ct.POINTER(wt.RECT)]
    user.ClientToScreen.argtypes = [wt.HWND, ct.POINTER(wt.POINT)]
    user.SetCursorPos.argtypes = [ct.c_int, ct.c_int]
    user.SendInput.argtypes = [wt.UINT, ct.POINTER(Input), ct.c_int]
    callback_type = ct.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
    user.EnumWindows.argtypes = [callback_type, wt.LPARAM]
    out.mkdir(parents=True)
    text_file = out / "ime-scratch.txt"
    fixture = "".join(f"row {i:06d}   Plain text for editor layout.\n" for i in range(lines))
    text_file.write_text("x\n" + fixture, encoding="utf-8")
    profile = out / "zed-user-data"
    env = os.environ.copy()
    env["ZED_LOG"] = "info,gpui_windows::platform=debug"
    proc = subprocess.Popen([exe, "--user-data-dir", profile, text_file], env=env)
    stop_resize = Event()
    resize_thread = None

    def foreground_owner():
        hwnd = user.GetForegroundWindow()
        pid = wt.DWORD()
        user.GetWindowThreadProcessId(hwnd, ct.byref(pid))
        return pid.value

    @callback_type
    def focus_window(hwnd, _):
        pid = wt.DWORD()
        user.GetWindowThreadProcessId(hwnd, ct.byref(pid))
        if pid.value == proc.pid and user.IsWindowVisible(hwnd):
            user.ShowWindow(hwnd, 9)
            user.SetForegroundWindow(hwnd)
            return False
        return True

    def send(events):
        if foreground_owner() != proc.pid:
            raise RuntimeError("INVALID: Zed lost foreground")
        batch = (Input * len(events))()
        for item, (vk, scan, flags) in zip(batch, events):
            item.type = 1
            item.data.keyboard = Keyboard(vk, scan, flags, 0, 0)
        if user.SendInput(len(batch), batch, ct.sizeof(Input)) != len(batch):
            raise ct.WinError(ct.get_last_error())

    def tap(vk):
        send([(vk, 0, 0), (vk, 0, 2)])

    def ctrl(vk, extended=0):
        send([(0x11, 0, 0), (vk, 0, extended), (vk, 0, extended | 2), (0x11, 0, 2)])
        time.sleep(.12)

    def read():
        return text_file.read_text(encoding="utf-8").split("\n", 1)[0]

    def clear_line():
        ctrl(0x24, extended=1)
        send([(0x10, 0, 0), (0x23, 0, 1), (0x23, 0, 3), (0x10, 0, 2)])
        tap(0x08)
        ctrl(ord("S"))
        for attempt in range(125):
            if attempt in (10, 35, 75):
                ctrl(ord("S"))
            if read() == "":
                return
            time.sleep(.2)
        raise RuntimeError("INVALID: scratch editor did not clear and save its first line")

    try:
        for _ in range(80):
            if proc.poll() is not None:
                raise RuntimeError(f"INVALID: Zed exited with {proc.returncode}")
            user.EnumWindows(focus_window, 0)
            if foreground_owner() == proc.pid:
                break
            time.sleep(.25)
        else:
            raise RuntimeError("INVALID: Zed could not be foregrounded")
        time.sleep(5)
        user.EnumWindows(focus_window, 0)
        # The fixture owns this freshly created directory and file.
        tap(0x0D)
        time.sleep(2)
        hwnd = user.GetForegroundWindow()
        rect = wt.RECT()
        if not user.GetClientRect(hwnd, ct.byref(rect)):
            raise ct.WinError(ct.get_last_error())
        point = wt.POINT(rect.right * 2 // 3, rect.bottom // 3)
        if not user.ClientToScreen(hwnd, ct.byref(point)):
            raise ct.WinError(ct.get_last_error())
        user.SetCursorPos(point.x, point.y)
        clicks = (Input * 2)()
        clicks[0].data.mouse.flags = 2
        clicks[1].data.mouse.flags = 4
        if user.SendInput(2, clicks, ct.sizeof(Input)) != 2:
            raise ct.WinError(ct.get_last_error())
        time.sleep(.5)
        send([(0x11, 0, 0), (0x10, 0, 0), (0xC0, 0, 0), (0xC0, 0, 2),
              (0x10, 0, 2), (0x11, 0, 2)])
        time.sleep(6)
        receiver = Path(__file__).with_name("terminal-receiver.py")
        capture = out / "pty.jsonl"
        command = f"& '{sys.executable}' '{receiver}' '{capture}'"
        if output_load:
            command += " --output-load"
        send([(0, ord(c), flags) for c in command for flags in (4, 6)])
        tap(0x0D)
        for _ in range(100):
            if capture.exists():
                break
            time.sleep(.2)
        else:
            raise RuntimeError("INVALID: the terminal line receiver did not start")

        geometry = wt.RECT()
        if not user.GetWindowRect(hwnd, ct.byref(geometry)):
            raise ct.WinError(ct.get_last_error())
        width = geometry.right - geometry.left
        height = geometry.bottom - geometry.top

        def resize():
            while not stop_resize.is_set():
                for offset in (0, 160, 80, 240):
                    # Resize the same window without activation, repositioning, or z-order changes.
                    user.SetWindowPos(hwnd, None, 0, 0, max(450, width-offset), height, 0x4016)
                    if stop_resize.wait(.023):
                        return

        resize_thread = Thread(target=resize)
        resize_thread.start()
        results = []
        prefix, suffix, expected, tail = {
            "ima": ("IMA", "DOUIU", "今どういう", "どういう"),
            "kansha": ("KANSYA", "WA-KU", "感謝わーく", "わーく"),
        }[phrase]
        modes = ("interleaved", "chords", "held-space", "space-batch")
        cases = [("control", True, 160, "interleaved")] + [
            (f"{mode}-{gap}-{attempt}", False, gap, mode)
            for attempt in range(batch_count) for mode in modes for gap in (0, 4, 16)
        ]
        def keys(text):
            return [event for key in text for event in ((ord(key) if key != "-" else 0xBD, 0, 0),
                                                        (ord(key) if key != "-" else 0xBD, 0, 2))]

        for label, explicit, gap, mode in cases:
            tap(0xF2)
            time.sleep(.12)
            send(keys(prefix))
            time.sleep(.18)
            send([(0x20, 0, 0)])
            time.sleep(.05)
            if mode == "space-batch":
                send([(0x20, 0, 2)] + keys(suffix))
            else:
                if mode != "held-space":
                    send([(0x20, 0, 2)])
                if explicit:
                    time.sleep(.12)
                    tap(0x0D)
                if gap:
                    time.sleep(gap / 1000)
                if mode == "chords":
                    send([(ord(key) if key != "-" else 0xBD, 0, flags)
                          for flags in (0, 2) for key in suffix])
                else:
                    send(keys(suffix))
                if mode == "held-space":
                    send([(0x20, 0, 2)])
            time.sleep(.3)
            tap(0x0D)
            time.sleep(.4)
            for attempt in range(100):
                recorded = capture.read_text(encoding="utf-8").splitlines()
                if len(recorded) > len(results):
                    after = json.loads(recorded[len(results)])
                    break
                if attempt in (5, 15):
                    tap(0x0D)
                time.sleep(.15)
            else:
                raise RuntimeError("INVALID: terminal line receiver did not receive a line")
            results.append({"trial": label, "received": after})
            (out / "results.json").write_text(json.dumps(results, ensure_ascii=False), encoding="utf-8")
            print(label, ascii(after), flush=True)

        if results[0]["received"] != expected:
            raise RuntimeError("INVALID: explicit control did not insert the complete phrase")
        losses = [item["trial"] for item in results[1:] if item["received"] == tail]
        other = [item for item in results[1:] if item["received"] not in (expected, tail)]
        if other:
            raise RuntimeError(f"INVALID: unexpected editor content: {other!r}")
        if losses:
            raise SystemExit(f"REPRODUCED: only the suffix was saved: {losses}")
        print("NOT REPRODUCED: every implicit commit reached the editor")
    finally:
        stop_resize.set()
        if resize_thread is not None:
            resize_thread.join()
        if proc.poll() is None:
            proc.terminate()
            proc.wait(timeout=10)


if __name__ == "__main__":
    if sys.platform != "win32" or not (
        os.environ.get("GITHUB_ACTIONS") == "true"
        or os.environ.get("COMPUTERNAME") == "PAD2PY-PAD-HOST"
    ):
        raise SystemExit("Run only on an isolated Windows CI runner or the pad2py test VM")
    parser = argparse.ArgumentParser()
    parser.add_argument("zed", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--lines", type=int, default=0)
    parser.add_argument("--phrase", choices=("ima", "kansha"), default="ima")
    parser.add_argument("--rounds", type=int, default=2)
    parser.add_argument("--output-load", action="store_true")
    args = parser.parse_args()
    replay(args.zed.resolve(), args.output.resolve(), args.lines, args.phrase, args.rounds, args.output_load)
