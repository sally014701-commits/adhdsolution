import json
import tkinter as tk
from tkinter import ttk
from urllib import error, request

STATUS_URL = "http://127.0.0.1:5000/status"
COMPLETE_URL = "http://127.0.0.1:5000/api/tasks/complete_current"


def get_json(url, method="GET"):
    req = request.Request(url, method=method)
    with request.urlopen(req, timeout=2) as response:
        return json.loads(response.read().decode("utf-8"))


def format_timer(seconds, overrun_seconds=0):
    overrun = max(0, int(overrun_seconds or 0))
    value = overrun if overrun > 0 else max(0, int(seconds or 0))
    minutes, rest = divmod(value, 60)
    prefix = "+" if overrun > 0 else ""
    return f"{prefix}{minutes:02d}:{rest:02d}"


class FallbackWidget:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("ADHD Task Widget")
        self.root.geometry("460x170+500+30")
        self.root.attributes("-topmost", True)
        self.root.resizable(False, False)
        self.root.configure(bg="#111827")

        self.state_label = tk.Label(self.root, text="connecting", bg="#111827", fg="#F9FAFB", font=("Segoe UI", 11, "bold"))
        self.state_label.pack(anchor="w", padx=16, pady=(12, 0))

        self.task_label = tk.Label(self.root, text="PC 앱 연결 대기", bg="#111827", fg="#FFFFFF", font=("Segoe UI", 16, "bold"))
        self.task_label.pack(anchor="w", padx=16, pady=(8, 0))

        self.timer_label = tk.Label(self.root, text="--:--", bg="#111827", fg="#FBBF24", font=("Segoe UI", 22, "bold"))
        self.timer_label.pack(anchor="w", padx=16, pady=(2, 0))

        self.next_label = tk.Label(self.root, text="다음 task 대기", bg="#111827", fg="#9CA3AF", font=("Segoe UI", 10))
        self.next_label.pack(anchor="w", padx=16)

        self.progress = ttk.Progressbar(self.root, length=420, mode="determinate", maximum=100)
        self.progress.pack(anchor="w", padx=16, pady=(8, 0))

        self.footer = tk.Frame(self.root, bg="#111827")
        self.footer.pack(fill="x", padx=16, pady=(8, 0))

        self.meta_label = tk.Label(self.footer, text="", bg="#111827", fg="#9CA3AF", font=("Segoe UI", 9))
        self.meta_label.pack(side="left")

        self.complete_button = tk.Button(self.footer, text="완료", command=self.complete_current, bg="#10B981", fg="#FFFFFF", relief="flat")
        self.complete_button.pack(side="right")

    def complete_current(self):
        try:
            get_json(COMPLETE_URL, method="POST")
            self.refresh()
        except Exception as exc:
            self.meta_label.configure(text=f"완료 실패: {exc}")

    def apply_state_color(self, state):
        colors = {
            "focused": "#10B981",
            "warning": "#F59E0B",
            "finishing": "#F59E0B",
            "overtime": "#EF4444",
            "distracted": "#EF4444",
            "idle": "#6B7280",
            "completed": "#60A5FA",
        }
        self.state_label.configure(fg=colors.get(state, "#F9FAFB"))

    def refresh(self):
        try:
            status = get_json(STATUS_URL)
            state = status.get("state_code") or status.get("state") or "focused"
            current = status.get("current_task") or {}
            next_task = status.get("next_task") or {}
            progress = status.get("plan_progress") or {}
            current_title = current.get("title") if isinstance(current, dict) else str(current)
            next_title = next_task.get("title") if isinstance(next_task, dict) else ""

            self.apply_state_color(state)
            self.state_label.configure(text=str(state).upper())
            self.task_label.configure(text=current_title or "작업 대기 중")
            self.timer_label.configure(text=format_timer(status.get("remaining_time"), status.get("overrun_seconds")))
            self.next_label.configure(text=f"다음: {next_title}" if next_title else "다음 task 없음")
            self.progress["value"] = max(0, min(100, float(progress.get("percent") or 0)))
            self.meta_label.configure(text=status.get("transition_message") or f"{progress.get('completed', 0)}/{progress.get('total', 0)} 완료")
            self.complete_button.configure(state=("disabled" if status.get("plan_completed") else "normal"))
        except (error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            self.state_label.configure(text="PC 연결 대기", fg="#F59E0B")
            self.meta_label.configure(text=str(exc))
        finally:
            self.root.after(1000, self.refresh)

    def run(self):
        self.refresh()
        self.root.mainloop()


if __name__ == "__main__":
    FallbackWidget().run()
