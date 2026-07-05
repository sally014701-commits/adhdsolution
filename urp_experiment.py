import json
import random
import time
from pathlib import Path
from uuid import uuid4

from flask import Blueprint, jsonify, render_template, request


CONDITIONS = ("low_specificity", "medium_specificity", "high_specificity")
DATA_DIR = Path(__file__).resolve().parent / "data"
EVENT_LOG_PATH = DATA_DIR / "urp_experiment_events.jsonl"


def _safe_int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _now_ms():
    return int(time.time() * 1000)


def _append_event(event):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "server_time_ms": _now_ms(),
        **event,
    }
    with EVENT_LOG_PATH.open("a", encoding="utf-8") as log_file:
        log_file.write(json.dumps(payload, ensure_ascii=False) + "\n")
    return payload


def _tracker_snapshot(tracker):
    if not tracker:
        return {
            "is_active": False,
            "state_code": "unknown",
            "task": "",
            "current_app": "",
            "current_title": "",
            "current_url": "",
            "activity": 0,
            "idle_time": 0,
            "window_switch": 0,
            "remaining_time": 0,
            "overrun_seconds": 0,
            "transition_phase": "unknown",
            "distraction_reason": "",
        }

    time_status = tracker.get_time_status() if getattr(tracker, "is_active", False) else {}
    return {
        "is_active": bool(getattr(tracker, "is_active", False)),
        "state_code": tracker.get_state_code() if hasattr(tracker, "get_state_code") else "unknown",
        "task": getattr(tracker, "task_name", ""),
        "current_app": getattr(tracker, "last_app_name", ""),
        "current_title": getattr(tracker, "last_window_title", ""),
        "current_url": getattr(tracker, "current_chrome_url", ""),
        "activity": tracker.get_current_activity() if hasattr(tracker, "get_current_activity") else 0,
        "idle_time": _safe_int(getattr(tracker, "current_idle_time", 0)),
        "window_switch": tracker.get_window_switch_count() if hasattr(tracker, "get_window_switch_count") else 0,
        "remaining_time": _safe_int(time_status.get("remaining_time", 0)),
        "overrun_seconds": _safe_int(time_status.get("overrun_seconds", 0)),
        "transition_phase": time_status.get("transition_phase", "unknown"),
        "distraction_reason": getattr(tracker, "distraction_reason", ""),
    }


def _format_mmss(seconds):
    seconds = max(0, _safe_int(seconds))
    minutes, rest = divmod(seconds, 60)
    return f"{minutes:02d}:{rest:02d}"


def _primary_context(snapshot):
    if snapshot.get("overrun_seconds", 0) > 0:
        return "overtime"
    if snapshot.get("distraction_reason") == "blocked":
        return "blocked"
    if snapshot.get("state_code") == "idle":
        return "idle"
    if snapshot.get("transition_phase") in {"finish_now", "wrapup_soon"}:
        return "wrapup"
    return "focus"


def _message_for(condition, snapshot):
    context = _primary_context(snapshot)
    task = snapshot.get("task") or "현재 작업"
    app = snapshot.get("current_app") or "현재 창"
    title = snapshot.get("current_title") or snapshot.get("current_url") or "창 정보 없음"
    remaining = _format_mmss(snapshot.get("remaining_time", 0))
    overrun = _format_mmss(snapshot.get("overrun_seconds", 0))
    idle = snapshot.get("idle_time", 0)
    switches = snapshot.get("window_switch", 0)
    activity = snapshot.get("activity", 0)

    if condition == "low_specificity":
        base = {
            "overtime": "정해둔 시간을 넘겼어요. 이제 마무리하고 다음 행동으로 전환해 주세요.",
            "blocked": "지금은 작업에서 벗어난 상태예요. 다시 원래 하던 일로 돌아와 주세요.",
            "idle": "잠시 멈춰 있는 상태예요. 아주 작은 다음 행동 하나만 다시 시작해 주세요.",
            "wrapup": "마무리 구간이에요. 새 일을 벌리지 말고 끝낼 준비를 해 주세요.",
            "focus": "좋아요. 지금 하던 흐름을 유지해 주세요.",
        }
        return base.get(context, base["focus"])

    if condition == "medium_specificity":
        base = {
            "overtime": f"'{task}'의 목표 시간을 {overrun} 넘겼어요. 지금은 완성도를 올리기보다 저장하고 전환할 시간입니다.",
            "blocked": f"현재 창이 '{app}'로 감지됐어요. 작업 목표 '{task}'로 다시 돌아와 주세요.",
            "idle": f"{idle}초 동안 입력이 거의 없었어요. '{task}'에서 바로 할 수 있는 한 줄 행동부터 재개해 주세요.",
            "wrapup": f"'{task}'의 남은 시간이 {remaining}입니다. 새 내용을 추가하지 말고 정리와 저장만 해 주세요.",
            "focus": f"'{task}'를 진행 중이에요. 남은 시간 {remaining} 동안 현재 흐름을 유지해 주세요.",
        }
        return base.get(context, base["focus"])

    base = {
        "overtime": (
            f"'{task}'가 목표 시간을 {overrun} 초과했습니다. 현재 창은 '{app}'이고 최근 2분 창 전환은 "
            f"{switches}회입니다. 지금 할 일은 추가 작성이 아니라 저장, 닫기, 다음 작업 선택입니다."
        ),
        "blocked": (
            f"차단 맥락이 감지됐습니다. 현재 앱은 '{app}', 창/URL은 '{title}'입니다. "
            f"작업 '{task}'와 맞지 않으니 이 창을 닫고 작업 창으로 복귀해 주세요."
        ),
        "idle": (
            f"입력 공백이 {idle}초이고 최근 활동량은 {activity}회입니다. '{task}'를 다시 시작하기 위해 "
            "커서를 작업 위치에 놓고 첫 문장 또는 첫 클릭 하나만 실행해 주세요."
        ),
        "wrapup": (
            f"'{task}'의 남은 시간은 {remaining}, 현재 앱은 '{app}', 최근 창 전환은 {switches}회입니다. "
            "지금부터는 새 자료 탐색을 멈추고 결과물을 저장 가능한 형태로 좁혀 주세요."
        ),
        "focus": (
            f"'{task}' 진행 중입니다. 현재 앱은 '{app}', 최근 활동량은 {activity}회, "
            f"남은 시간은 {remaining}입니다. 지금 창에서 다음 작은 행동을 계속해 주세요."
        ),
    }
    return base.get(context, base["focus"])


def create_urp_experiment_blueprint(get_tracker):
    blueprint = Blueprint("urp_experiment", __name__)

    @blueprint.route("/experiment/urp")
    def urp_experiment_page():
        return render_template("urp_experiment.html")

    @blueprint.route("/api/experiment/urp/session", methods=["POST"])
    def create_session():
        data = request.json or {}
        requested_condition = data.get("condition")
        condition = requested_condition if requested_condition in CONDITIONS else random.choice(CONDITIONS)
        session = {
            "session_id": data.get("session_id") or f"urp-{uuid4().hex[:12]}",
            "participant_id": data.get("participant_id") or "",
            "condition": condition,
            "condition_label": condition.replace("_", " "),
            "created_at_ms": _now_ms(),
        }
        _append_event({
            "event_type": "session_started",
            **session,
        })
        return jsonify(session)

    @blueprint.route("/api/experiment/urp/intervention", methods=["POST"])
    def create_intervention():
        data = request.json or {}
        condition = data.get("condition")
        if condition not in CONDITIONS:
            condition = random.choice(CONDITIONS)
        snapshot = data.get("snapshot") if isinstance(data.get("snapshot"), dict) else _tracker_snapshot(get_tracker())
        message = _message_for(condition, snapshot)
        payload = {
            "intervention_id": f"msg-{uuid4().hex[:12]}",
            "session_id": data.get("session_id") or "",
            "condition": condition,
            "message": message,
            "snapshot": snapshot,
        }
        _append_event({
            "event_type": "intervention_generated",
            **payload,
        })
        return jsonify(payload)

    @blueprint.route("/api/experiment/urp/event", methods=["POST"])
    def record_event():
        data = request.json or {}
        event = _append_event({
            "event_type": data.get("event_type") or "client_event",
            "session_id": data.get("session_id") or "",
            "condition": data.get("condition") or "",
            "intervention_id": data.get("intervention_id") or "",
            "rating": data.get("rating"),
            "response": data.get("response"),
            "client_payload": data.get("payload") or {},
        })
        return jsonify({"status": "ok", "event": event})

    @blueprint.route("/api/experiment/urp/conditions", methods=["GET"])
    def get_conditions():
        return jsonify({
            "conditions": [
                {
                    "id": "low_specificity",
                    "label": "Low specificity",
                    "description": "General intervention message without concrete monitoring details.",
                },
                {
                    "id": "medium_specificity",
                    "label": "Medium specificity",
                    "description": "Includes task or broad state information such as app, idle, or remaining time.",
                },
                {
                    "id": "high_specificity",
                    "label": "High specificity",
                    "description": "Includes concrete monitoring details such as app/title, idle seconds, activity, window switches, and time.",
                },
            ],
            "event_log_path": str(EVENT_LOG_PATH),
        })

    return blueprint
