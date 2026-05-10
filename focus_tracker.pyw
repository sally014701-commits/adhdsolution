import time
import threading
import ctypes
from collections import deque
import psutil
from pynput import keyboard, mouse
import json
import logging
import webbrowser
from flask import Flask, request, jsonify, render_template

# ==========================================
# 임계값 (Thresholds) 상수 정의
# ==========================================
WINDOW_SWITCH_THRESHOLD = 15      # 2분 기준 활성 창 전환 횟수
IDLE_THRESHOLD = 60               # 초 단위 마지막 입력 이후 경과 시간
ACTIVITY_DROP_RATIO = 0.5         # baseline 대비 50% 이하

app = Flask(__name__)
# Flask 로깅 최소화 (콘솔 지저분해짐 방지)
log = logging.getLogger('werkzeug')
log.setLevel(logging.ERROR)

global_tracker = None

@app.route('/')
def index():
    return render_template('index.html')

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
            if current_app and current_app.lower() == 'chrome.exe' and global_tracker.is_blocked(current_app, title):
                print(f"\n🚨 [즉시 경고] 금지된 크롬 사이트({title.strip()})에 진입했습니다! 🚨\n")
    return jsonify({"status": "ok"})

@app.route('/start_tracking', methods=['POST'])
def start_tracking():
    data = request.json
    if data and global_tracker:
        task = data.get('task', '')
        blocked_apps = data.get('blocked_apps', '')
        global_tracker.start_monitoring(task, blocked_apps)
        return jsonify({"status": "ok"})
    return jsonify({"error": "Invalid request"}), 400

@app.route('/stop_tracking', methods=['POST'])
def stop_tracking():
    if not global_tracker:
        return jsonify({"error": "Tracker not initialized"}), 500
    
    global_tracker.running = False
    global_tracker.is_active = False
    
    report = {
        "total_focus_sec": global_tracker.total_focus_sec,
        "total_distracted_sec": global_tracker.total_distracted_sec,
        "total_idle_sec": global_tracker.total_idle_sec,
        "distractions": list(global_tracker.distraction_log)
    }
    return jsonify(report)

@app.route('/status', methods=['GET'])
def get_status():
    if not global_tracker:
        return jsonify({"error": "Tracker not initialized"}), 500
        
    return jsonify({
        "is_active": global_tracker.is_active,
        "state": global_tracker.current_state,
        "current_app": global_tracker.last_app_name,
        "current_url": global_tracker.current_chrome_url if global_tracker.last_app_name.lower() == 'chrome.exe' else "",
        "current_title": global_tracker.last_window_title,
        "activity": global_tracker.last_minute_activity,
        "idle_time": global_tracker.current_idle_time,
        "window_switch": global_tracker.get_window_switch_count(),
        "elapsed_time": int(time.time() - global_tracker.start_time) if global_tracker.start_time else 0
    })

class FocusTracker:
    def __init__(self):
        self.lock = threading.Lock()
        
        # 상태 변수
        self.last_input_time = time.time()
        self.current_activity = 0
        self.window_switch_timestamps = deque()
        self.activity_history = []
        
        # UI 제공용 변수
        self.current_state = "수집 중"
        self.last_app_name = ""
        self.last_window_title = ""
        self.last_minute_activity = 0
        self.current_idle_time = 0
        
        # Baseline 변수
        self.baseline_activity = 0.0
        self.baseline_window_switch = 0.0
        self.is_baseline_set = False
        self.seconds_elapsed = 0
        self.start_time = None
        
        # 지속 시간 추적
        self.distracted_minutes = 0
        
        # 보고서용 통계 데이터
        self.total_focus_sec = 0
        self.total_distracted_sec = 0
        self.total_idle_sec = 0
        self.distraction_log = set()
        
        # 윈도우 창 모니터링용
        self.last_window_handle = ctypes.windll.user32.GetForegroundWindow()
        self.running = False
        self.is_active = False # 설정 전엔 비활성
        self.loop_thread = None
        self.win_thread = None
        self.allowed_apps = []
        self.blocked_apps = []
        
        # 크롬 연동 변수
        self.current_chrome_url = ""
        self.current_chrome_title = ""
        
        global global_tracker
        global_tracker = self
        
    def start_monitoring(self, task, blocked_input):
        with self.lock:
            if self.is_active:
                return
            self.is_active = True
            
        # 이전 스레드가 완전히 종료될 때까지 대기
        self.running = False
        if self.loop_thread and self.loop_thread.is_alive():
            self.loop_thread.join(timeout=1.5)
        if self.win_thread and self.win_thread.is_alive():
            self.win_thread.join(timeout=1.5)
            
        # 모든 상태 초기화 (재시작 시 대비)
        self.running = True
        self.seconds_elapsed = 0
        self.start_time = time.time()
        self.current_activity = 0
        self.activity_history = []
        self.window_switch_timestamps.clear()
        self.last_input_time = time.time()
        self.is_baseline_set = False
        
        self.current_state = "수집 중"
        self.total_focus_sec = 0
        self.total_distracted_sec = 0
        self.total_idle_sec = 0
        self.distraction_log.clear()
        self.distracted_minutes = 0
            
        if "레포트" in task or "문서" in task or "과제" in task:
            self.allowed_apps = ["WINWORD.EXE", "EXCEL.EXE", "chrome.exe"]
        elif "코딩" in task or "개발" in task:
            self.allowed_apps = ["Code.exe", "chrome.exe"]
        elif "조사" in task or "리서치" in task:
            self.allowed_apps = ["chrome.exe"]
        else:
            self.allowed_apps = ["chrome.exe"]

        if blocked_input:
            self.blocked_apps = [app.strip() for app in blocked_input.split(",") if app.strip()]

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
        
        # 루프 시작 스레드
        self.loop_thread = threading.Thread(target=self.tracking_loop, daemon=True)
        self.loop_thread.start()
        
        print(f"✅ 허용 앱 설정 완료: {self.allowed_apps}")
        if self.blocked_apps:
            print(f"🚫 다음 앱은 차단됩니다: {self.blocked_apps}")
        print("🎯 집중 모니터링 시스템 시작")

    def on_input(self, *args):
        """키보드 및 마우스 입력 발생 시 호출되는 콜백"""
        self.last_input_time = time.time()
        self.current_activity += 1

    def get_window_title(self, hwnd):
        """윈도우 핸들(hwnd)의 타이틀을 반환"""
        length = ctypes.windll.user32.GetWindowTextLengthW(hwnd)
        if length == 0:
            return ""
        buf = ctypes.create_unicode_buffer(length + 1)
        ctypes.windll.user32.GetWindowTextW(hwnd, buf, length + 1)
        return buf.value

    def monitor_window(self):
        """1초마다 활성 창을 체크하여 변경 시 카운트 및 금지 앱 감지"""
        last_valid_window = ctypes.windll.user32.GetForegroundWindow()
        
        while self.running:
            current_window = ctypes.windll.user32.GetForegroundWindow()
            if current_window != 0 and current_window != last_valid_window:
                title = self.get_window_title(current_window)
                if title.strip():
                    self.window_switch_timestamps.append(time.time())
                    last_valid_window = current_window
                    
                    if self.blocked_apps:
                        current_app = self.get_foreground_process_name()
                        if hasattr(self, 'is_blocked') and self.is_blocked(current_app, title):
                            print(f"\n🚨 [즉시 경고] 금지된 사이트/앱({title.strip()})에 진입했습니다! 🚨\n")
            time.sleep(1)

    def get_window_switch_count(self):
        """최근 2분 동안의 창 전환 횟수 반환"""
        current_time = time.time()
        while self.window_switch_timestamps and self.window_switch_timestamps[0] < current_time - 120:
            self.window_switch_timestamps.popleft()
        return len(self.window_switch_timestamps)

    def get_foreground_process_name(self):
        """현재 활성화된 창의 프로세스 이름 반환"""
        hwnd = ctypes.windll.user32.GetForegroundWindow()
        if not hwnd:
            return ""
        pid = ctypes.c_ulong(0)
        ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value > 0:
            try:
                return psutil.Process(pid.value).name()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                return ""
        return ""

    def is_blocked(self, current_app, current_title):
        """앱 프로세스 이름이나 창 타이틀, 또는 크롬 URL에 금지어가 포함되어 있는지 확인"""
        if not self.blocked_apps:
            return False
        app_lower = current_app.lower() if current_app else ""
        title_lower = current_title.lower() if current_title else ""
        url_lower = self.current_chrome_url.lower() if app_lower == 'chrome.exe' else ""
        
        for b in self.blocked_apps:
            b_lower = b.lower()
            if b_lower == app_lower or b_lower in title_lower or b_lower in url_lower:
                return True
        return False

    def tracking_loop(self):
        try:
            # 1초 주기 상태 갱신 루프
            while self.running:
                time.sleep(1) 
                self.seconds_elapsed += 1
                
                # 매 1분(60초)마다 activity 누적 및 처리
                if self.seconds_elapsed % 60 == 0:
                    self.last_minute_activity = self.current_activity
                    self.activity_history.append(self.current_activity)
                    self.current_activity = 0
                    
                    # Baseline 3분 수집 완료 체크
                    if not self.is_baseline_set and len(self.activity_history) == 3:
                        self.baseline_activity = sum(self.activity_history) / 3
                        self.is_baseline_set = True
                        print("-" * 50)
                        print(f"✅ [Baseline 설정 완료] \n - 평균 activity: {self.baseline_activity:.1f}")
                        print("-" * 50)
                
                window_switch_count = self.get_window_switch_count()
                idle_time = int(time.time() - self.last_input_time)
                current_app = self.get_foreground_process_name()
                current_title = self.get_window_title(ctypes.windll.user32.GetForegroundWindow())
                
                # UI용 변수 실시간 업데이트
                self.current_idle_time = idle_time
                self.last_app_name = current_app
                self.last_window_title = current_title
                # 1) 실시간 상태 판정 검사
                cond_blocked = self.is_blocked(current_app, current_title)
                cond_idle = idle_time > IDLE_THRESHOLD
                cond_app = current_app and current_app not in self.allowed_apps
                
                # Baseline 기반 검사는 Baseline 수집이 끝난 후에만
                cond_switch_activity = False
                if self.is_baseline_set:
                    cond_switch_activity = (window_switch_count > WINDOW_SWITCH_THRESHOLD) and (self.last_minute_activity < self.baseline_activity * ACTIVITY_DROP_RATIO)
                
                # 2) 상태 결정 로직
                if cond_blocked:
                    self.current_state = "이탈"
                elif cond_idle:
                    self.current_state = "비활동"
                elif cond_app:
                    self.current_state = "이탈"
                elif cond_switch_activity:
                    self.current_state = "이탈"
                else:
                    if not self.is_baseline_set:
                        self.current_state = "수집 중"
                    else:
                        self.current_state = "집중"
                
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
                            print("\n🚨 [경고] 현재 작업에서 벗어난 상태입니다! 🚨\n")
                    else:
                        self.distracted_minutes = 0

        except KeyboardInterrupt:
            self.stop()

    def stop(self):
        print("\n모니터링을 종료합니다.")
        self.running = False
        if hasattr(self, 'kb_listener'):
            self.kb_listener.stop()
            self.ms_listener.stop()

    def run(self):
        print("="*50)
        print("🎯 대시보드 주소: http://localhost:5000")
        print("="*50)
        # 브라우저 자동 실행
        threading.Timer(1, lambda: webbrowser.open("http://localhost:5000")).start()
        # Flask 서버 메인 스레드 실행
        app.run(host='0.0.0.0', port=5000, debug=False, use_reloader=False)

if __name__ == "__main__":
    tracker = FocusTracker()
    tracker.run()
