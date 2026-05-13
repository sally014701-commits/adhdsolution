import time
import threading
import ctypes
import os
import subprocess
import atexit
import sys
from ctypes import wintypes
from collections import deque
import psutil
from pynput import keyboard, mouse
import json
import logging
import webbrowser
from flask import Flask, request, jsonify, render_template, send_from_directory
from mobile_app import create_mobile_blueprint

# ==========================================
# 임계값 (Thresholds) 상수 정의
# ==========================================
WINDOW_SWITCH_THRESHOLD = 15      # 2분 기준 활성 창 전환 횟수
IDLE_THRESHOLD = 60               # 초 단위 마지막 입력 이후 경과 시간
ACTIVITY_DROP_RATIO = 0.5         # baseline 대비 50% 이하

class LASTINPUTINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", ctypes.c_uint),
        ("dwTime", ctypes.c_uint),
    ]

user32 = ctypes.windll.user32
user32.GetForegroundWindow.restype = wintypes.HWND
user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
user32.GetWindowTextLengthW.restype = ctypes.c_int
user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
user32.GetWindowTextW.restype = ctypes.c_int
user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
user32.GetWindowThreadProcessId.restype = wintypes.DWORD
user32.GetLastInputInfo.argtypes = [ctypes.POINTER(LASTINPUTINFO)]
user32.GetLastInputInfo.restype = wintypes.BOOL
user32.OpenInputDesktop.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
user32.OpenInputDesktop.restype = wintypes.HDESK
user32.SetThreadDesktop.argtypes = [wintypes.HDESK]
user32.SetThreadDesktop.restype = wintypes.BOOL
user32.IsWindow.argtypes = [wintypes.HWND]
user32.IsWindow.restype = wintypes.BOOL

DESKTOP_READOBJECTS = 0x0001
DESKTOP_SWITCHDESKTOP = 0x0100

app = Flask(__name__)
# Flask 로깅 최소화 (콘솔 지저분해짐 방지)
log = logging.getLogger('werkzeug')
log.setLevel(logging.ERROR)

for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8", errors="replace")

global_tracker = None
app.register_blueprint(create_mobile_blueprint(lambda: global_tracker))

WIDGET_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "desktop-widget")
WIDGET_SRC_DIR = os.path.join(WIDGET_DIR, "src")
WIDGET_LAUNCH_LOG = os.path.join(WIDGET_DIR, "widget-launch.log")
WIDGET_USER_DATA_DIR = os.path.join(WIDGET_DIR, ".electron-user-data")
WIDGET_CACHE_DIR = os.path.join(WIDGET_DIR, ".electron-cache")
WIDGET_TEMP_DIR = os.path.join(WIDGET_DIR, ".electron-temp")
widget_process = None
widget_lock = threading.Lock()
CURRENT_PLAN_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "current_plan.json")

def _normalized_path(value):
    return os.path.normcase(os.path.abspath(value)) if value else ""

def _path_contains_widget_dir(value):
    if not value:
        return False
    return os.path.normcase(value).find(os.path.normcase(WIDGET_DIR)) >= 0

def _find_widget_process():
    for proc in psutil.process_iter(["pid", "name", "cmdline", "cwd"]):
        try:
            cmdline = " ".join(proc.info.get("cmdline") or [])
            cwd = proc.info.get("cwd") or ""
            if _path_contains_widget_dir(cmdline) or _path_contains_widget_dir(cwd):
                return proc
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue
    return None

def _get_running_widget_process():
    global widget_process
    if widget_process and widget_process.poll() is None:
        return widget_process

    found = _find_widget_process()
    if found:
        return found

    widget_process = None
    return None

def _terminate_process_tree(proc):
    try:
        ps_proc = psutil.Process(proc.pid) if hasattr(proc, "pid") else proc
        children = ps_proc.children(recursive=True)
        for child in children:
            try:
                child.terminate()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        try:
            ps_proc.terminate()
        except psutil.AccessDenied:
            if hasattr(proc, "terminate"):
                proc.terminate()

        gone, alive = psutil.wait_procs([ps_proc, *children], timeout=3)
        for still_alive in alive:
            try:
                still_alive.kill()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        return True
    except psutil.NoSuchProcess:
        return False
    except psutil.AccessDenied:
        if hasattr(proc, "kill"):
            try:
                proc.kill()
                return True
            except Exception:
                return False
        return False

def _cleanup_widget_process():
    global widget_process
    proc = _get_running_widget_process()
    if proc:
        _terminate_process_tree(proc)
        widget_process = None

def _get_electron_command():
    electron_exe = os.path.join(WIDGET_DIR, "node_modules", "electron", "dist", "electron.exe")
    electron_cmd = os.path.join(WIDGET_DIR, "node_modules", ".bin", "electron.cmd")
    electron_args = [
        f"--user-data-dir={WIDGET_USER_DATA_DIR}",
        f"--disk-cache-dir={WIDGET_CACHE_DIR}",
        "--disable-gpu",
        "--disable-features=NetworkServiceSandbox",
        "--no-sandbox",
        ".",
    ]

    if os.path.exists(electron_exe):
        return [electron_exe, *electron_args]
    if os.path.exists(electron_cmd):
        return [electron_cmd, *electron_args]
    return None

def _get_electron_path():
    electron_exe = os.path.join(WIDGET_DIR, "node_modules", "electron", "dist", "electron.exe")
    electron_cmd = os.path.join(WIDGET_DIR, "node_modules", ".bin", "electron.cmd")

    if os.path.exists(electron_exe):
        return electron_exe
    if os.path.exists(electron_cmd):
        return electron_cmd
    return None

@app.route('/widget/start', methods=['POST'])
def start_widget():
    global widget_process
    print("desktop widget start API called", flush=True)
    with widget_lock:
        if _get_running_widget_process():
            return jsonify({
                "running": True,
                "message": "already running",
                "mode": "electron",
            })

        if not os.path.isdir(WIDGET_DIR):
            return jsonify({
                "running": False,
                "error": "desktop-widget folder not found",
                "widget_dir": WIDGET_DIR,
            }), 500

        package_json = os.path.join(WIDGET_DIR, "package.json")
        if not os.path.exists(package_json):
            return jsonify({
                "running": False,
                "error": "package.json not found",
                "widget_dir": WIDGET_DIR,
            }), 500

        electron_path = _get_electron_path()
        widget_command = _get_electron_command()
        if not widget_command:
            return jsonify({
                "running": False,
                "error": "Electron not installed",
                "command": None,
                "cwd": WIDGET_DIR,
                "electron_path": None,
                "log_path": WIDGET_LAUNCH_LOG,
            }), 500

        command_display = " ".join(widget_command)
        print(f"desktop widget command: {command_display}", flush=True)
        print(f"desktop widget cwd: {WIDGET_DIR}", flush=True)
        creationflags = (
            getattr(subprocess, "CREATE_NO_WINDOW", 0)
            | getattr(subprocess, "DETACHED_PROCESS", 0)
            | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        )
        try:
            os.makedirs(WIDGET_USER_DATA_DIR, exist_ok=True)
            os.makedirs(WIDGET_CACHE_DIR, exist_ok=True)
            os.makedirs(WIDGET_TEMP_DIR, exist_ok=True)
            widget_env = os.environ.copy()
            widget_env["LOCALAPPDATA"] = WIDGET_USER_DATA_DIR
            widget_env["TEMP"] = WIDGET_TEMP_DIR
            widget_env["TMP"] = WIDGET_TEMP_DIR
            log_file = open(WIDGET_LAUNCH_LOG, "w", encoding="utf-8", errors="replace")
            widget_process = subprocess.Popen(
                widget_command,
                cwd=WIDGET_DIR,
                env=widget_env,
                stdin=subprocess.DEVNULL,
                stdout=log_file,
                stderr=log_file,
                close_fds=True,
                creationflags=creationflags,
            )
            log_file.close()
            time.sleep(3)
            if widget_process.poll() is not None:
                returncode = widget_process.returncode
                error_detail = ""
                if os.path.exists(WIDGET_LAUNCH_LOG):
                    with open(WIDGET_LAUNCH_LOG, "r", encoding="utf-8", errors="replace") as launch_log:
                        error_detail = launch_log.read()[-800:]
                widget_process = None
                return jsonify({
                    "running": False,
                    "error": "Electron widget failed to start",
                    "returncode": returncode,
                    "detail": error_detail.strip(),
                    "command": command_display,
                    "cwd": WIDGET_DIR,
                    "electron_path": electron_path,
                    "log_path": WIDGET_LAUNCH_LOG,
                    "user_data_dir": WIDGET_USER_DATA_DIR,
                    "cache_dir": WIDGET_CACHE_DIR,
                    "temp_dir": WIDGET_TEMP_DIR,
                }), 500
            return jsonify({
                "running": True,
                "message": "desktop electron widget launched",
                "mode": "electron",
                "command": command_display,
                "cwd": WIDGET_DIR,
                "electron_path": electron_path,
                "log_path": WIDGET_LAUNCH_LOG,
                "user_data_dir": WIDGET_USER_DATA_DIR,
                "cache_dir": WIDGET_CACHE_DIR,
                "temp_dir": WIDGET_TEMP_DIR,
            })
        except Exception as exc:
            widget_process = None
            error_detail = ""
            if os.path.exists(WIDGET_LAUNCH_LOG):
                with open(WIDGET_LAUNCH_LOG, "r", encoding="utf-8", errors="replace") as launch_log:
                    error_detail = launch_log.read()[-800:]
            return jsonify({
                "running": False,
                "error": str(exc),
                "detail": error_detail.strip(),
                "command": command_display,
                "cwd": WIDGET_DIR,
                "electron_path": electron_path,
                "log_path": WIDGET_LAUNCH_LOG,
                "user_data_dir": WIDGET_USER_DATA_DIR,
                "cache_dir": WIDGET_CACHE_DIR,
                "temp_dir": WIDGET_TEMP_DIR,
            }), 500

@app.route('/widget/stop', methods=['POST'])
def stop_widget():
    global widget_process
    with widget_lock:
        proc = _get_running_widget_process()
        if not proc:
            return jsonify({"running": False, "status": "not running"})

        if not _terminate_process_tree(proc):
            return jsonify({"running": True, "error": "failed to stop widget process"}), 500
        widget_process = None
        return jsonify({"running": False, "status": "stopped"})

@app.route('/widget/status', methods=['GET'])
def widget_status():
    return jsonify({"running": bool(_get_running_widget_process())})

atexit.register(_cleanup_widget_process)

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/plan/current', methods=['GET'])
def current_plan():
    if not os.path.exists(CURRENT_PLAN_PATH):
        return jsonify({"error": "No current plan found"}), 404
    try:
        with open(CURRENT_PLAN_PATH, "r", encoding="utf-8") as plan_file:
            return jsonify(json.load(plan_file))
    except (OSError, json.JSONDecodeError) as exc:
        return jsonify({"error": "Unable to read current plan", "detail": str(exc)}), 500

@app.route('/update_tab', methods=['POST'])
def update_tab():
    data = request.json
    if data and global_tracker:
        url = data.get('url', '')
        title = data.get('title', '')
        
        global_tracker.current_chrome_url = url
        global_tracker.current_chrome_title = title
        
        if global_tracker.blocked_apps:
            current_app = global_tracker.get_foreground_process_name()
            chrome_app = current_app if current_app and current_app.lower() == 'chrome.exe' else 'chrome.exe'
            if global_tracker.is_blocked(chrome_app, title):
                global_tracker.last_app_name = chrome_app
                global_tracker.last_window_title = title
                global_tracker.current_state = "이탈"
                global_tracker.distraction_reason = "blocked"
                global_tracker.alert_message = f"금지된 사이트/앱입니다: {title.strip() or url}"
                print(f"\n[즉시 경고] 금지된 크롬 사이트({title.strip()})에 진입했습니다!\n")
    return jsonify({"status": "ok"})

@app.route('/start_tracking', methods=['POST'])
def start_tracking():
    data = request.json
    if data and global_tracker:
        task = data.get('task', '')
        blocked_apps = data.get('blocked_apps', '')
        target_minutes = data.get('target_minutes', 60)
        extra_allowed_apps = data.get('extra_allowed_apps', '')
        global_tracker.start_monitoring(task, blocked_apps, target_minutes, extra_allowed_apps)
        return jsonify({"status": "ok"})
    return jsonify({"error": "Invalid request"}), 400

@app.route('/allowed_apps_preview', methods=['POST'])
def allowed_apps_preview():
    data = request.json or {}
    task = data.get('task', '')
    extra_allowed_apps = data.get('extra_allowed_apps', '')
    tracker = global_tracker or FocusTracker.__new__(FocusTracker)
    default_apps = tracker.get_default_allowed_apps(task)
    extra_apps = tracker.parse_app_list(extra_allowed_apps)
    return jsonify({
        "allowed_apps": tracker.merge_app_lists(default_apps, extra_apps),
        "default_apps": default_apps,
        "extra_apps": extra_apps,
    })

@app.route('/stop_tracking', methods=['POST'])
def stop_tracking():
    if not global_tracker:
        return jsonify({"error": "Tracker not initialized"}), 500
    
    global_tracker.stop()
    
    report = {
        "total_focus_sec": global_tracker.total_focus_sec,
        "total_distracted_sec": global_tracker.total_distracted_sec,
        "total_idle_sec": global_tracker.total_idle_sec,
        "task": global_tracker.task_name,
        "target_minutes": global_tracker.target_minutes,
        "elapsed_sec": global_tracker.get_elapsed_seconds(),
        "overrun_sec": global_tracker.get_time_status()["overrun_seconds"],
        "distractions": list(global_tracker.distraction_log)
    }
    return jsonify(report)

@app.route('/status', methods=['GET'])
def get_status():
    if not global_tracker:
        return jsonify({"error": "Tracker not initialized"}), 500

    if global_tracker.is_active:
        global_tracker.record_window_switch(global_tracker.get_foreground_window(), source="/status")
        global_tracker.evaluate_state(
            global_tracker.last_app_name,
            global_tracker.last_window_title,
            global_tracker.get_window_switch_count(),
            global_tracker.current_idle_time,
        )

    time_status = global_tracker.get_time_status()
        
    return jsonify({
        "is_active": global_tracker.is_active,
        "state": global_tracker.current_state,
        "state_code": global_tracker.get_state_code(),
        "alert_message": global_tracker.alert_message,
        "distraction_reason": global_tracker.distraction_reason,
        "condition_flags": global_tracker.condition_flags,
        "allowed_apps": global_tracker.allowed_apps,
        "task": global_tracker.task_name,
        "target_minutes": global_tracker.target_minutes,
        "target_seconds": global_tracker.target_seconds,
        **time_status,
        "current_app": global_tracker.last_app_name,
        "current_url": global_tracker.current_chrome_url if global_tracker.current_chrome_url else "",
        "current_title": global_tracker.last_window_title,
        "activity": global_tracker.get_current_activity(),
        "idle_time": global_tracker.current_idle_time,
        "window_switch": global_tracker.get_window_switch_count(),
        "foreground_hwnd": global_tracker.get_foreground_window(),
        "last_window_handle": global_tracker.last_window_handle,
        "win_thread_alive": bool(global_tracker.win_thread and global_tracker.win_thread.is_alive()),
        "elapsed_time": int(time.time() - global_tracker.start_time) if global_tracker.start_time else 0
    })

class FocusTracker:
    def __init__(self):
        self.lock = threading.Lock()
        
        # 상태 변수
        self.last_input_time = time.time()
        self.current_activity = 0
        self.activity_timestamps = deque()
        self.window_switch_timestamps = deque()
        self.activity_history = []
        self.last_system_input_tick = self.get_last_input_tick()
        
        # UI 제공용 변수
        self.current_state = "수집 중"
        self.last_app_name = ""
        self.last_window_title = ""
        self.last_minute_activity = 0
        self.current_idle_time = 0
        self.distraction_reason = ""
        self.alert_message = ""
        self.condition_flags = {}
        
        # Baseline 변수
        self.baseline_activity = 0.0
        self.baseline_window_switch = 0.0
        self.is_baseline_set = False
        self.seconds_elapsed = 0
        self.start_time = None
        self.task_name = ""
        self.target_minutes = 60
        self.target_seconds = 3600
        self.transition_phase = "work"
        
        # 지속 시간 추적
        self.distracted_minutes = 0
        
        # 보고서용 통계 데이터
        self.total_focus_sec = 0
        self.total_distracted_sec = 0
        self.total_idle_sec = 0
        self.distraction_log = set()
        
        # 윈도우 창 모니터링용
        self.last_window_handle = self.get_foreground_window()
        self.last_window_process_name = self.get_process_name_by_window(self.last_window_handle)
        self.running = False
        self.is_active = False # 설정 전엔 비활성
        self.loop_thread = None
        self.win_thread = None
        self.input_desktop_handle = None
        self.allowed_apps = []
        self.blocked_apps = []
        
        # 크롬 연동 변수
        self.current_chrome_url = ""
        self.current_chrome_title = ""
        
        global global_tracker
        global_tracker = self
        
    def start_monitoring(self, task, blocked_input, target_minutes=60, extra_allowed_input=""):
        with self.lock:
            if self.is_active:
                return
            self.is_active = True
            
        # 이전 스레드가 완전히 종료될 때까지 대기
        self.running = False
        self.stop_input_listeners()
        if self.loop_thread and self.loop_thread.is_alive():
            self.loop_thread.join(timeout=1.5)
        if self.win_thread and self.win_thread.is_alive():
            self.win_thread.join(timeout=1.5)
            
        # 모든 상태 초기화 (재시작 시 대비)
        self.running = True
        self.seconds_elapsed = 0
        self.start_time = time.time()
        self.task_name = task.strip() or "작업"
        self.target_minutes = self.parse_target_minutes(target_minutes)
        self.target_seconds = self.target_minutes * 60
        self.transition_phase = "work"
        self.current_activity = 0
        self.activity_timestamps.clear()
        self.last_minute_activity = 0
        self.activity_history = []
        self.window_switch_timestamps.clear()
        self.last_window_handle = self.get_foreground_window()
        self.last_window_process_name = self.get_process_name_by_window(self.last_window_handle)
        self.last_input_time = time.time()
        self.last_system_input_tick = self.get_last_input_tick()
        self.is_baseline_set = False
        
        self.current_state = "수집 중"
        self.distraction_reason = ""
        self.alert_message = ""
        self.total_focus_sec = 0
        self.total_distracted_sec = 0
        self.total_idle_sec = 0
        self.distraction_log.clear()
        self.distracted_minutes = 0
            
        self.allowed_apps = self.merge_app_lists(
            self.get_default_allowed_apps(task),
            self.parse_app_list(extra_allowed_input)
        )

        if blocked_input:
            self.blocked_apps = self.parse_app_list(blocked_input)
        else:
            self.blocked_apps = []

        # pynput 이벤트 리스너 시작
        self.kb_listener = keyboard.Listener(on_press=self.on_input)
        self.ms_listener = mouse.Listener(
            on_move=self.on_input, 
            on_click=self.on_input, 
            on_scroll=self.on_input
        )
        self.kb_listener.start()
        self.ms_listener.start()

        # 창 전환 모니터링 스레드 시작
        self.win_thread = threading.Thread(target=self.monitor_window, daemon=True)
        self.win_thread.start()
        print(f"[WindowSwitch] monitor_window thread started | alive={self.win_thread.is_alive()} | initial_hwnd={self.last_window_handle}", flush=True)
        
        # 루프 시작 스레드
        self.loop_thread = threading.Thread(target=self.tracking_loop, daemon=True)
        self.loop_thread.start()
        
        print(f"✅ 허용 앱 설정 완료: {self.allowed_apps}")
        if self.blocked_apps:
            print(f"차단 앱/사이트: {self.blocked_apps}")
        print("집중 모니터링 시스템 시작")

    def on_input(self, *args):
        """키보드 및 마우스 입력 발생 시 호출되는 콜백"""
        self.record_activity()

    def parse_app_list(self, value):
        if not value:
            return []
        return [app.strip() for app in value.split(",") if app.strip()]

    def merge_app_lists(self, *app_lists):
        merged = []
        seen = set()
        for apps in app_lists:
            for app_name in apps:
                key = app_name.lower()
                if key not in seen:
                    seen.add(key)
                    merged.append(app_name)
        return merged

    def get_default_allowed_apps(self, task):
        task_text = task or ""
        if "레포트" in task_text or "문서" in task_text or "과제" in task_text:
            return ["WINWORD.EXE", "EXCEL.EXE", "chrome.exe"]
        if "코딩" in task_text or "개발" in task_text:
            return ["Code.exe", "chrome.exe"]
        if "조사" in task_text or "리서치" in task_text:
            return ["chrome.exe"]
        return ["chrome.exe"]

    def parse_target_minutes(self, value):
        try:
            minutes = int(value)
        except (TypeError, ValueError):
            minutes = 60
        return max(1, min(minutes, 480))

    def get_elapsed_seconds(self):
        return int(time.time() - self.start_time) if self.start_time else 0

    def get_time_status(self):
        elapsed = self.get_elapsed_seconds()
        remaining = max(0, self.target_seconds - elapsed)
        overrun = max(0, elapsed - self.target_seconds)
        progress = min(1.0, elapsed / self.target_seconds) if self.target_seconds else 0.0

        if overrun > 0:
            phase = "overrun"
            message = "목표 시간을 넘겼습니다. 지금은 더 완벽하게 만드는 시간이 아니라 마무리하고 전환할 시간입니다."
        elif remaining <= 120:
            phase = "finish_now"
            message = "마무리 2분 전입니다. 새 내용을 추가하지 말고 저장, 정리, 다음 행동만 준비하세요."
        elif remaining <= 600:
            phase = "wrapup_soon"
            message = "마무리 구간입니다. 완성도를 올리기보다 끝낼 수 있는 형태로 좁혀주세요."
        else:
            phase = "work"
            message = "정해둔 시간 안에서 필요한 만큼만 진행하세요."

        if phase != self.transition_phase:
            self.transition_phase = phase
            print(f"[Transition] phase={phase} remaining={remaining}s overrun={overrun}s", flush=True)

        return {
            "elapsed_time": elapsed,
            "remaining_time": remaining,
            "overrun_seconds": overrun,
            "time_progress": progress,
            "transition_phase": phase,
            "transition_message": message,
            "transition_required": phase in ["finish_now", "overrun"],
        }

    def record_activity(self):
        if not self.is_active:
            return
        now = time.time()
        self.last_input_time = now
        self.activity_timestamps.append(now)
        self.prune_activity(now)

    def prune_activity(self, now=None):
        now = now or time.time()
        while self.activity_timestamps and self.activity_timestamps[0] < now - 60:
            self.activity_timestamps.popleft()
        self.current_activity = len(self.activity_timestamps)
        return self.current_activity

    def get_current_activity(self):
        return self.prune_activity()

    def get_last_input_tick(self):
        info = LASTINPUTINFO()
        info.cbSize = ctypes.sizeof(LASTINPUTINFO)
        if user32.GetLastInputInfo(ctypes.byref(info)):
            return int(info.dwTime)
        return None

    def sync_polled_input_activity(self):
        current_tick = self.get_last_input_tick()
        if current_tick is None:
            return
        if self.last_system_input_tick is None:
            self.last_system_input_tick = current_tick
            return
        if current_tick != self.last_system_input_tick:
            self.last_system_input_tick = current_tick
            self.record_activity()

    def get_window_title(self, hwnd):
        """윈도우 핸들(hwnd)의 타이틀을 반환"""
        length = user32.GetWindowTextLengthW(hwnd)
        if length == 0:
            return ""
        buf = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buf, length + 1)
        return buf.value

    def get_foreground_window(self):
        hwnd = user32.GetForegroundWindow()
        return int(hwnd) if hwnd else 0

    def attach_thread_to_input_desktop(self):
        access = DESKTOP_READOBJECTS | DESKTOP_SWITCHDESKTOP
        desktop = user32.OpenInputDesktop(0, False, access)
        if not desktop:
            print("[WindowSwitch] OpenInputDesktop failed", flush=True)
            return False
        if not user32.SetThreadDesktop(desktop):
            print("[WindowSwitch] SetThreadDesktop failed", flush=True)
            return False
        self.input_desktop_handle = desktop
        print("[WindowSwitch] attached monitor thread to input desktop", flush=True)
        return True

    def get_process_name_by_window(self, hwnd):
        if not hwnd:
            return ""
        pid = wintypes.DWORD(0)
        user32.GetWindowThreadProcessId(wintypes.HWND(hwnd), ctypes.byref(pid))
        if pid.value > 0:
            try:
                return psutil.Process(pid.value).name()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                return ""
        return ""

    def record_window_switch(self, hwnd, source="monitor"):
        if not hwnd:
            return False
        previous_window = self.last_window_handle
        previous_app = self.last_window_process_name
        current_app = self.get_process_name_by_window(hwnd)
        if hwnd == self.last_window_handle:
            return False
        if previous_app and current_app and previous_app.lower() == current_app.lower():
            self.last_window_handle = hwnd
            self.last_window_process_name = current_app
            return False
        if previous_window and not user32.IsWindow(wintypes.HWND(previous_window)):
            print(
                f"[WindowSwitch:{source}] ignored_closed_window_return "
                f"previous_hwnd={previous_window} current_hwnd={hwnd} "
                f"previous_process={previous_app} process={current_app} "
                f"window_switch_count={self.get_window_switch_count()}",
                flush=True
            )
            self.last_window_handle = hwnd
            self.last_window_process_name = current_app
            return False
        self.last_window_handle = hwnd
        self.last_window_process_name = current_app
        self.window_switch_timestamps.append(time.time())
        window_switch_count = self.get_window_switch_count()
        print(
            f"[WindowSwitch:{source}] previous_hwnd={previous_window} "
            f"current_hwnd={hwnd} previous_process={previous_app} process={current_app} "
            f"window_switch_count={window_switch_count}",
            flush=True
        )
        return True

    def monitor_window(self):
        """1초마다 활성 창을 체크하여 변경 시 카운트 및 금지 앱 감지"""
        self.attach_thread_to_input_desktop()
        initial_window = self.get_foreground_window()
        if initial_window:
            self.last_window_handle = initial_window
            self.last_window_process_name = self.get_process_name_by_window(initial_window)
            self.last_app_name = self.last_window_process_name
            self.last_window_title = self.get_window_title(initial_window)
            print(
                f"[WindowSwitch] baseline hwnd={self.last_window_handle} "
                f"process={self.last_window_process_name}",
                flush=True
            )
        print(f"[WindowSwitch] monitor_window loop entered | running={self.running}", flush=True)
        while self.running:
            current_window = self.get_foreground_window()
            if current_window:
                self.last_app_name = self.get_process_name_by_window(current_window)
                self.last_window_title = self.get_window_title(current_window)
            if self.record_window_switch(current_window, source="monitor"):
                title = self.get_window_title(current_window)
                if self.blocked_apps:
                    current_app = self.get_foreground_process_name()
                    if hasattr(self, 'is_blocked') and self.is_blocked(current_app, title):
                        self.current_state = "이탈"
                        self.distraction_reason = "blocked"
                        self.alert_message = f"금지된 사이트/앱입니다: {title.strip() or current_app}"
                        print(f"\n[즉시 경고] 금지된 사이트/앱({title.strip()})에 진입했습니다!\n")
            time.sleep(1)

    def get_window_switch_count(self):
        """최근 2분 동안의 창 전환 횟수 반환"""
        current_time = time.time()
        while self.window_switch_timestamps and self.window_switch_timestamps[0] < current_time - 120:
            self.window_switch_timestamps.popleft()
        return len(self.window_switch_timestamps)

    def get_foreground_process_name(self):
        """현재 활성화된 창의 프로세스 이름 반환"""
        return self.get_process_name_by_window(self.get_foreground_window())

    def stop_input_listeners(self):
        for listener_name in ("kb_listener", "ms_listener"):
            listener = getattr(self, listener_name, None)
            if listener:
                try:
                    listener.stop()
                except Exception:
                    pass
                setattr(self, listener_name, None)

    def get_blocked_terms(self):
        terms = set()
        aliases = {
            "유튜브": ["youtube", "youtube.com", "youtu.be"],
            "youtube": ["유튜브", "youtube.com", "youtu.be"],
            "youtube.com": ["유튜브", "youtube", "youtu.be"],
            "youtu.be": ["유튜브", "youtube", "youtube.com"],
        }

        for blocked in self.blocked_apps:
            term = blocked.strip().lower()
            if not term:
                continue
            terms.add(term)
            terms.update(aliases.get(term, []))
        return terms

    def is_blocked(self, current_app, current_title):
        """앱 프로세스 이름이나 창 타이틀, 또는 크롬 URL에 금지어가 포함되어 있는지 확인"""
        if not self.blocked_apps:
            return False
        app_lower = current_app.lower() if current_app else ""
        title_lower = current_title.lower() if current_title else ""
        url_lower = self.current_chrome_url.lower()
        
        for b_lower in self.get_blocked_terms():
            if b_lower in app_lower or b_lower in title_lower or b_lower in url_lower:
                return True
        return False

    def get_state_code(self):
        if self.current_state == "이탈":
            return "distracted"
        if self.current_state == "비활동":
            return "idle"
        if self.current_state == "집중":
            return "focused"
        return "collecting"

    def evaluate_state(self, current_app, current_title, window_switch_count, idle_time):
        cond_blocked = self.is_blocked(current_app, current_title)
        cond_idle = idle_time > IDLE_THRESHOLD
        allowed_lower = [app.lower() for app in self.allowed_apps]
        cond_app = bool(current_app) and current_app.lower() not in allowed_lower

        current_activity = self.get_current_activity()
        cond_switch_activity = False
        if self.is_baseline_set:
            cond_switch_activity = (
                window_switch_count > WINDOW_SWITCH_THRESHOLD
                and current_activity < self.baseline_activity * ACTIVITY_DROP_RATIO
            )

        self.condition_flags = {
            "cond_blocked": bool(cond_blocked),
            "cond_idle": bool(cond_idle),
            "cond_app": bool(cond_app),
            "cond_switch_activity": bool(cond_switch_activity),
            "current_app": current_app,
            "allowed_apps": self.allowed_apps,
            "window_switch_count": window_switch_count,
            "current_activity": current_activity,
            "baseline_activity": self.baseline_activity,
            "is_baseline_set": self.is_baseline_set,
        }

        if cond_blocked:
            self.current_state = "이탈"
            self.distraction_reason = "blocked"
            blocked_target = self.current_chrome_url if self.current_chrome_url else (current_title or current_app)
            self.alert_message = f"금지된 사이트/앱입니다: {blocked_target}"
        elif cond_idle:
            self.current_state = "비활동"
            self.distraction_reason = "idle"
            self.alert_message = "60초 이상 입력이 없어 비활동 상태입니다."
        elif cond_app:
            self.current_state = "이탈"
            self.distraction_reason = "not_allowed_app"
            self.alert_message = f"허용되지 않은 앱입니다: {current_app}"
        elif cond_switch_activity:
            self.current_state = "이탈"
            self.distraction_reason = "switch_activity"
            self.alert_message = "창 전환이 많고 활동량이 낮아 산만한 작업 패턴으로 감지되었습니다."
        else:
            self.current_state = "집중"
            self.distraction_reason = ""
            self.alert_message = ""

    def tracking_loop(self):
        try:
            # 1초 주기 상태 갱신 루프
            while self.running:
                time.sleep(1) 
                self.sync_polled_input_activity()
                self.seconds_elapsed += 1
                
                # 매 1분(60초)마다 activity 누적 및 처리
                if self.seconds_elapsed % 60 == 0:
                    self.last_minute_activity = self.get_current_activity()
                    self.activity_history.append(self.last_minute_activity)
                    
                    # Baseline 3분 수집 완료 체크
                    if not self.is_baseline_set and len(self.activity_history) == 3:
                        self.baseline_activity = sum(self.activity_history) / 3
                        self.is_baseline_set = True
                        print("-" * 50)
                        print(f"✅ [Baseline 설정 완료] \n - 평균 activity: {self.baseline_activity:.1f}")
                        print("-" * 50)
                
                window_switch_count = self.get_window_switch_count()
                idle_time = int(time.time() - self.last_input_time)
                current_app = self.last_app_name
                current_title = self.last_window_title
                
                # UI용 변수 실시간 업데이트
                self.current_idle_time = idle_time
                self.last_app_name = current_app
                self.last_window_title = current_title
                self.evaluate_state(current_app, current_title, window_switch_count, idle_time)
                
                # 3) 통계 기록 (1초마다)
                if self.current_state == "집중":
                    self.total_focus_sec += 1
                elif self.current_state == "이탈":
                    self.total_distracted_sec += 1
                    dist_name = self.current_chrome_url if (current_app and current_app.lower() == 'chrome.exe' and self.current_chrome_url) else current_app
                    if dist_name:
                        self.distraction_log.add(dist_name)
                elif self.current_state == "비활동":
                    self.total_idle_sec += 1
                
                # 콘솔 출력 (매 1분마다)
                if self.seconds_elapsed % 60 == 0:
                    minutes = self.seconds_elapsed // 60
                    print(f"[{minutes}분] 상태: {self.current_state} | 앱: {current_app} | activity: {self.last_minute_activity}, idle_time: {idle_time}초, window_switch(2m): {window_switch_count}")
                    
                    if self.current_state in ["이탈", "비활동"]:
                        self.distracted_minutes += 1
                        if self.distracted_minutes >= 3:
                            print("\n[경고] 현재 작업에서 벗어난 상태입니다!\n")
                    else:
                        self.distracted_minutes = 0

        except KeyboardInterrupt:
            self.stop()

    def stop(self):
        print("\n모니터링을 종료합니다.")
        self.running = False
        self.is_active = False
        self.stop_input_listeners()

    def run(self):
        print("="*50)
        print("대시보드 주소: http://localhost:5000")
        print("="*50)
        # 브라우저 자동 실행
        threading.Timer(1, lambda: webbrowser.open("http://localhost:5000")).start()
        # Flask 서버 메인 스레드 실행
        app.run(host='0.0.0.0', port=5000, debug=False, use_reloader=False)

if __name__ == "__main__":
    tracker = FocusTracker()
    tracker.run()
