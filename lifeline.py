"""Small, read-only Codex quota window for Windows."""

from __future__ import annotations

import glob
import json
import os
import queue
import shutil
import subprocess
import threading
import time
import tkinter as tk
from pathlib import Path


REFRESH_MS = 90_000
TRANSPARENT = "#ff00ff"
TEXT = "#ffffff"
TRACK = "#394653"


def find_codex() -> str:
    override = os.environ.get("CODEX_BIN")
    if override:
        if Path(override).is_file():
            return override
        raise FileNotFoundError("CODEX_BIN 指向的文件不存在")
    installed = shutil.which("codex")
    if installed:
        return installed
    local = os.environ.get("LOCALAPPDATA", "")
    candidates = glob.glob(os.path.join(local, "OpenAI", "Codex", "bin", "*", "codex.exe"))
    if candidates:
        return max(candidates, key=os.path.getmtime)
    raise FileNotFoundError("未找到 Codex CLI；请设置 CODEX_BIN 为 codex.exe 路径")


def read_limits(timeout: float = 25.0) -> dict:
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    process = subprocess.Popen(
        [find_codex(), "app-server"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
        creationflags=flags,
    )
    messages: queue.Queue[dict | None] = queue.Queue()

    def collect() -> None:
        assert process.stdout is not None
        for line in process.stdout:
            try:
                messages.put(json.loads(line))
            except json.JSONDecodeError:
                continue
        messages.put(None)

    threading.Thread(target=collect, daemon=True).start()
    deadline = time.monotonic() + timeout

    def send(message: dict) -> None:
        assert process.stdin is not None
        process.stdin.write(json.dumps(message, ensure_ascii=False) + "\n")
        process.stdin.flush()

    def receive(request_id: int) -> dict:
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("读取 Codex 额度超时")
            try:
                message = messages.get(timeout=remaining)
            except queue.Empty as exc:
                raise TimeoutError("读取 Codex 额度超时") from exc
            if message is None:
                raise RuntimeError("Codex App Server 提前退出")
            if message.get("id") != request_id:
                continue
            if "error" in message:
                raise RuntimeError(str(message["error"].get("message", message["error"])))
            return message.get("result", {})

    try:
        send({
            "method": "initialize",
            "id": 1,
            "params": {"clientInfo": {
                "name": "lifeline",
                "title": "Lifeline",
                "version": "1.0.0",
            }},
        })
        receive(1)
        send({"method": "initialized"})
        send({"method": "account/rateLimits/read", "id": 2})
        return receive(2)
    finally:
        if process.poll() is None:
            process.terminate()
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=2)


def window_data(response: dict) -> dict[int, dict | None]:
    buckets = response.get("rateLimitsByLimitId") or {}
    bucket = buckets.get("codex") or response.get("rateLimits") or {}
    found: dict[int, dict | None] = {300: None, 10080: None}
    for item in (bucket.get("primary"), bucket.get("secondary")):
        if not isinstance(item, dict):
            continue
        duration = item.get("windowDurationMins")
        if duration in found:
            found[duration] = item
    return found


def remaining_percent(item: dict | None) -> float | None:
    if not item or item.get("usedPercent") is None:
        return None
    return max(0.0, min(100.0, 100.0 - float(item["usedPercent"])))


class LifelineWindow:
    def __init__(self) -> None:
        self.root = tk.Tk()
        self.root.title("Lifeline")
        self.root.configure(bg=TRANSPARENT)
        self.root.overrideredirect(True)
        try:
            self.root.wm_attributes("-transparentcolor", TRANSPARENT)
        except tk.TclError:
            # Other Tk platforms still get the same compact two-bar layout.
            pass
        self.root.attributes("-topmost", True)
        self.root.geometry(f"310x104+{self.root.winfo_screenwidth() - 330}+24")
        self.root.resizable(False, False)
        self.fetching = False
        self.results: queue.Queue[tuple[dict | None, str | None]] = queue.Queue()
        self.drag_origin: tuple[int, int] | None = None
        self.values: dict[int, float | None] = {300: None, 10080: None}
        self._build()
        self._draw()
        self.refresh()
        self.root.after(100, self._collect_results)
        self.root.after(REFRESH_MS, self._refresh_timer)

    def _build(self) -> None:
        self.canvas = tk.Canvas(self.root, width=310, height=104,
                                bg=TRANSPARENT, highlightthickness=0, bd=0)
        self.canvas.pack()
        self.canvas.bind("<ButtonPress-1>", self._drag_start)
        self.canvas.bind("<B1-Motion>", self._drag_move)
        self.canvas.bind("<Double-Button-1>", lambda _event: self.refresh())
        self.canvas.bind("<Button-3>", lambda _event: self.root.destroy())
        self.root.bind("<Escape>", lambda _event: self.root.destroy())

    def _drag_start(self, event: tk.Event) -> None:
        self.drag_origin = (event.x_root - self.root.winfo_x(),
                            event.y_root - self.root.winfo_y())

    def _drag_move(self, event: tk.Event) -> None:
        if self.drag_origin:
            x = event.x_root - self.drag_origin[0]
            y = event.y_root - self.drag_origin[1]
            self.root.geometry(f"+{x}+{y}")

    def _draw(self) -> None:
        self.canvas.delete("all")
        for duration, caption, label_y, bar_y in (
            (300, "5小时", 5, 35),
            (10080, "7天", 55, 85),
        ):
            value = self.values[duration]
            remaining = "剩余 --" if value is None else f"剩余 {value:.0f}%"
            for x, anchor, content in ((12, "nw", caption), (298, "ne", remaining)):
                self.canvas.create_text(x + 1, label_y + 1, text=content,
                                        anchor=anchor, fill="#101820",
                                        font=("Microsoft YaHei UI", 11, "bold"))
                self.canvas.create_text(x, label_y, text=content,
                                        anchor=anchor, fill=TEXT,
                                        font=("Microsoft YaHei UI", 11, "bold"))

            # A single rounded stroke keeps the track and fill continuous.
            self.canvas.create_line(19, bar_y, 291, bar_y,
                                    fill=TRACK, width=14, capstyle=tk.ROUND)
            if value is not None and value > 0:
                color = "#67d7a4" if value > 30 else "#f1bd68" if value > 10 else "#f47b78"
                end_x = 19 + 272 * value / 100
                self.canvas.create_line(19, bar_y, max(19.01, end_x), bar_y,
                                        fill=color, width=14, capstyle=tk.ROUND)

    def refresh(self) -> None:
        if self.fetching:
            return
        self.fetching = True

        def work() -> None:
            try:
                self.results.put((read_limits(), None))
            except Exception as exc:
                self.results.put((None, str(exc)))

        threading.Thread(target=work, daemon=True).start()

    def _collect_results(self) -> None:
        try:
            response, error = self.results.get_nowait()
        except queue.Empty:
            pass
        else:
            self.fetching = False
            if not error:
                windows = window_data(response or {})
                for duration, item in windows.items():
                    self.values[duration] = remaining_percent(item)
                self._draw()
        self.root.after(100, self._collect_results)

    def _refresh_timer(self) -> None:
        self.refresh()
        self.root.after(REFRESH_MS, self._refresh_timer)

    def run(self) -> None:
        self.root.mainloop()


if __name__ == "__main__":
    LifelineWindow().run()
