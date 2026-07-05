import csv
import json
import random
import time
from pathlib import Path
from uuid import uuid4

from flask import Blueprint, Response, jsonify, render_template, request


CONDITIONS = ("abstract", "concrete")
DATA_DIR = Path(__file__).resolve().parent / "data"
EVENT_LOG_PATH = DATA_DIR / "urp_experiment_events.jsonl"
CSV_LOG_PATH = DATA_DIR / "urp_experiment_events.csv"
MINIGAME_AFTER_SECONDS = 180
INTERVENTION_AFTER_SECONDS = 30
READING_DURATION_SECONDS = 600

SESSIONS = {}


CSV_FIELDS = [
    "server_time_ms",
    "event_type",
    "session_id",
    "participant_id",
    "condition",
    "intervention_id",
    "message_type",
    "message",
    "snapshot_json",
    "payload_json",
]


def _now_ms():
    return int(time.time() * 1000)


def _elapsed_seconds(start_ms):
    if not start_ms:
        return 0
    return max(0, int((_now_ms() - int(start_ms)) / 1000))


def _condition(value):
    return value if value in CONDITIONS else random.choice(CONDITIONS)


def _public_session(session):
    return {
        "session_id": session["session_id"],
        "started_at_ms": session["started_at_ms"],
        "reading_duration_seconds": READING_DURATION_SECONDS,
        "minigame_after_seconds": MINIGAME_AFTER_SECONDS,
        "intervention_after_seconds": INTERVENTION_AFTER_SECONDS,
    }


def _admin_session(session):
    return {
        **session,
        "elapsed_seconds": _elapsed_seconds(session.get("started_at_ms")),
        "condition_label": session.get("condition", "").title(),
    }


def _safe_int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _read_events(limit=80):
    if not EVENT_LOG_PATH.exists():
        return []
    lines = EVENT_LOG_PATH.read_text(encoding="utf-8").splitlines()
    events = []
    for line in lines[-limit:]:
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return events


def _write_csv_event(event):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    exists = CSV_LOG_PATH.exists()
    with CSV_LOG_PATH.open("a", encoding="utf-8", newline="") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=CSV_FIELDS)
        if not exists:
            writer.writeheader()
        writer.writerow({
            "server_time_ms": event.get("server_time_ms"),
            "event_type": event.get("event_type", ""),
            "session_id": event.get("session_id", ""),
            "participant_id": event.get("participant_id", ""),
            "condition": event.get("condition", ""),
            "intervention_id": event.get("intervention_id", ""),
            "message_type": event.get("message_type", ""),
            "message": event.get("message", ""),
            "snapshot_json": json.dumps(event.get("snapshot") or {}, ensure_ascii=False),
            "payload_json": json.dumps(event.get("payload") or {}, ensure_ascii=False),
        })


def _append_event(event):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "server_time_ms": _now_ms(),
        **event,
    }
    with EVENT_LOG_PATH.open("a", encoding="utf-8") as log_file:
        log_file.write(json.dumps(payload, ensure_ascii=False) + "\n")
    _write_csv_event(payload)
    return payload


def _tracker_snapshot(tracker):
    if not tracker:
        return {
            "source": "fallback",
            "is_active": False,
            "state_code": "reading",
            "task": "Reading task",
            "current_app": "",
            "current_title": "",
            "current_url": "",
            "activity": 0,
            "idle_time": 0,
            "window_switch": 0,
            "remaining_time": 0,
            "overrun_seconds": 0,
            "transition_phase": "reading",
            "distraction_reason": "",
        }

    time_status = tracker.get_time_status() if getattr(tracker, "is_active", False) else {}
    return {
        "source": "focus_tracker",
        "is_active": bool(getattr(tracker, "is_active", False)),
        "state_code": tracker.get_state_code() if hasattr(tracker, "get_state_code") else "unknown",
        "task": getattr(tracker, "task_name", "") or "Reading task",
        "current_app": getattr(tracker, "last_app_name", ""),
        "current_title": getattr(tracker, "last_window_title", ""),
        "current_url": getattr(tracker, "current_chrome_url", ""),
        "activity": tracker.get_current_activity() if hasattr(tracker, "get_current_activity") else 0,
        "idle_time": _safe_int(getattr(tracker, "current_idle_time", 0)),
        "window_switch": tracker.get_window_switch_count() if hasattr(tracker, "get_window_switch_count") else 0,
        "remaining_time": _safe_int(time_status.get("remaining_time", 0)),
        "overrun_seconds": _safe_int(time_status.get("overrun_seconds", 0)),
        "transition_phase": time_status.get("transition_phase", "reading"),
        "distraction_reason": getattr(tracker, "distraction_reason", ""),
    }


def generate_intervention_message(condition, snapshot):
    if condition == "concrete":
        app = snapshot.get("current_app") or "현재 창"
        title = snapshot.get("current_title") or snapshot.get("current_url") or "다른 화면"
        idle = _safe_int(snapshot.get("idle_time", 0))
        switches = _safe_int(snapshot.get("window_switch", 0))
        activity = _safe_int(snapshot.get("activity", 0))
        return (
            "현재 읽기 과제로 돌아갈 시간입니다. "
            f"최근 활동 {activity}회, 입력 공백 {idle}초, 창 전환 {switches}회가 감지되었고 "
            f"현재 화면은 {app} ({title})입니다."
        )
    return "현재 읽기 과제로 돌아갈 시간입니다."


def build_intervention_state(session, get_tracker, force=False):
    if not session:
        return {
            "active": False,
            "condition": "",
            "message": "",
            "type": "monitoring",
            "session_id": "",
        }

    if session.get("intervention_acknowledged_at_ms"):
        return {
            "active": False,
            "condition": session["condition"],
            "message": "",
            "type": "monitoring",
            "session_id": session["session_id"],
        }

    mini_started_at = session.get("minigame_started_at_ms")
    eligible = bool(mini_started_at and _elapsed_seconds(mini_started_at) >= INTERVENTION_AFTER_SECONDS)
    if not force and not session.get("intervention_active") and not eligible:
        return {
            "active": False,
            "condition": session["condition"],
            "message": "",
            "type": "monitoring",
            "session_id": session["session_id"],
        }

    if not session.get("intervention_active"):
        snapshot = _tracker_snapshot(get_tracker())
        session["intervention_id"] = f"msg-{uuid4().hex[:12]}"
        session["intervention_snapshot"] = snapshot
        session["intervention_message"] = generate_intervention_message(session["condition"], snapshot)
        session["intervention_active"] = True
        session["intervention_started_at_ms"] = _now_ms()
        _append_event({
            "event_type": "intervention_activated",
            "session_id": session["session_id"],
            "participant_id": session.get("participant_id", ""),
            "condition": session["condition"],
            "intervention_id": session["intervention_id"],
            "message_type": "monitoring",
            "message": session["intervention_message"],
            "snapshot": snapshot,
            "payload": {"trigger": "minigame_30s" if not force else "admin_force"},
        })

    return {
        "active": True,
        "condition": session["condition"],
        "message": session.get("intervention_message", ""),
        "type": "monitoring",
        "session_id": session["session_id"],
        "intervention_id": session.get("intervention_id", ""),
    }


def create_urp_experiment_blueprint(get_tracker):
    blueprint = Blueprint("urp_experiment", __name__)

    @blueprint.route("/experiment")
    def participant_view():
        return render_template("urp_participant.html")

    @blueprint.route("/experiment/admin")
    @blueprint.route("/experiment/urp")
    def admin_view():
        return render_template("urp_admin.html")

    @blueprint.route("/experiment/survey")
    def survey_view():
        return render_template("urp_survey.html")

    @blueprint.route("/experiment/api/session", methods=["POST"])
    def create_participant_session():
        session = {
            "session_id": f"urp-{uuid4().hex[:12]}",
            "participant_id": "",
            "condition": random.choice(CONDITIONS),
            "started_at_ms": _now_ms(),
            "created_by": "participant_view",
            "intervention_active": False,
        }
        SESSIONS[session["session_id"]] = session
        _append_event({
            "event_type": "participant_session_started",
            "session_id": session["session_id"],
            "condition": session["condition"],
            "payload": {"public_view": True},
        })
        return jsonify(_public_session(session))

    @blueprint.route("/experiment/api/minigame_started", methods=["POST"])
    def minigame_started():
        data = request.json or {}
        session = SESSIONS.get(data.get("session_id", ""))
        if not session:
            return jsonify({"error": "session not found"}), 404
        if not session.get("minigame_started_at_ms"):
            session["minigame_started_at_ms"] = _now_ms()
            _append_event({
                "event_type": "minigame_started",
                "session_id": session["session_id"],
                "participant_id": session.get("participant_id", ""),
                "condition": session["condition"],
            })
        return jsonify({"status": "ok", "session_id": session["session_id"]})

    @blueprint.route("/experiment/api/intervention_state", methods=["GET"])
    def intervention_state():
        session = SESSIONS.get(request.args.get("session_id", ""))
        state = build_intervention_state(session, get_tracker, force=False)
        return jsonify(state)

    @blueprint.route("/experiment/api/intervention_ack", methods=["POST"])
    def intervention_ack():
        data = request.json or {}
        session = SESSIONS.get(data.get("session_id", ""))
        if not session:
            return jsonify({"error": "session not found"}), 404
        session["intervention_active"] = False
        session["intervention_acknowledged_at_ms"] = _now_ms()
        _append_event({
            "event_type": "intervention_acknowledged",
            "session_id": session["session_id"],
            "participant_id": session.get("participant_id", ""),
            "condition": session["condition"],
            "intervention_id": session.get("intervention_id", ""),
            "message_type": "monitoring",
            "message": session.get("intervention_message", ""),
            "snapshot": session.get("intervention_snapshot", {}),
        })
        return jsonify({"status": "ok"})

    @blueprint.route("/experiment/api/event", methods=["POST"])
    def participant_event():
        data = request.json or {}
        session = SESSIONS.get(data.get("session_id", ""))
        _append_event({
            "event_type": data.get("event_type") or "participant_event",
            "session_id": data.get("session_id") or "",
            "participant_id": session.get("participant_id", "") if session else "",
            "condition": session.get("condition", "") if session else "",
            "payload": data.get("payload") or {},
        })
        return jsonify({"status": "ok"})

    @blueprint.route("/experiment/api/survey", methods=["POST"])
    def participant_survey():
        data = request.json or {}
        session = SESSIONS.get(data.get("session_id", ""))
        if not session:
            return jsonify({"error": "session not found"}), 404
        _append_event({
            "event_type": "post_survey_submitted",
            "session_id": session["session_id"],
            "participant_id": session.get("participant_id", ""),
            "condition": session["condition"],
            "payload": {
                "monitoring_awareness": data.get("monitoring_awareness"),
                "psychological_reactance": data.get("psychological_reactance"),
                "free_response": data.get("free_response") or "",
            },
        })
        return jsonify({"status": "ok"})

    @blueprint.route("/experiment/api/admin/session", methods=["POST"])
    def admin_create_session():
        data = request.json or {}
        session = {
            "session_id": data.get("session_id") or f"urp-{uuid4().hex[:12]}",
            "participant_id": data.get("participant_id") or "",
            "condition": _condition(data.get("condition")),
            "started_at_ms": _now_ms(),
            "created_by": "admin",
            "intervention_active": False,
        }
        SESSIONS[session["session_id"]] = session
        _append_event({
            "event_type": "admin_session_started",
            "session_id": session["session_id"],
            "participant_id": session["participant_id"],
            "condition": session["condition"],
            "payload": {"assignment": data.get("condition") or "random"},
        })
        return jsonify(_admin_session(session))

    @blueprint.route("/experiment/api/admin/session_state", methods=["GET"])
    def admin_session_state():
        session_id = request.args.get("session_id", "")
        session = SESSIONS.get(session_id) or next(reversed(SESSIONS.values()), None)
        state = build_intervention_state(session, get_tracker, force=False) if session else {}
        return jsonify({
            "session": _admin_session(session) if session else None,
            "intervention_state": state,
            "snapshot": _tracker_snapshot(get_tracker()),
        })

    @blueprint.route("/experiment/api/admin/force_intervention", methods=["POST"])
    def admin_force_intervention():
        data = request.json or {}
        session = SESSIONS.get(data.get("session_id", ""))
        if not session:
            return jsonify({"error": "session not found"}), 404
        state = build_intervention_state(session, get_tracker, force=True)
        return jsonify(state)

    @blueprint.route("/experiment/api/admin/events", methods=["GET"])
    def admin_events():
        return jsonify({"events": _read_events(_safe_int(request.args.get("limit"), 120))})

    @blueprint.route("/experiment/api/admin/csv_status", methods=["GET"])
    def admin_csv_status():
        return jsonify({
            "exists": CSV_LOG_PATH.exists(),
            "path": str(CSV_LOG_PATH),
            "bytes": CSV_LOG_PATH.stat().st_size if CSV_LOG_PATH.exists() else 0,
        })

    @blueprint.route("/experiment/api/admin/events.csv", methods=["GET"])
    def admin_events_csv():
        if not CSV_LOG_PATH.exists():
            return Response("", mimetype="text/csv")
        return Response(
            CSV_LOG_PATH.read_text(encoding="utf-8"),
            mimetype="text/csv",
            headers={"Content-Disposition": "attachment; filename=urp_experiment_events.csv"},
        )

    @blueprint.route("/experiment/api/admin/conditions", methods=["GET"])
    def admin_conditions():
        return jsonify({
            "conditions": [
                {
                    "id": "abstract",
                    "label": "Abstract",
                    "description": "Generic monitoring intervention with no behavioral telemetry in the message.",
                },
                {
                    "id": "concrete",
                    "label": "Concrete",
                    "description": "Monitoring intervention that includes concrete behavioral telemetry.",
                },
            ],
            "event_log_path": str(EVENT_LOG_PATH),
            "csv_log_path": str(CSV_LOG_PATH),
        })

    return blueprint
