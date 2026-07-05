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
GAME_PROMPT_MESSAGE = "잠깐 쉬어가는 미니게임을 해보시겠습니까? 2,000점 달성 시 소정의 보상이 제공됩니다."
ABSTRACT_RETURN_MESSAGE = "집중 흐름이 잠시 흐트러진 것 같습니다. 원래 읽기 과제로 돌아가시겠습니까?"
CONCRETE_RETURN_MESSAGE = "읽기 과제 시작 후 약 4분 30초가 지났고, 최근 30초 동안 미니게임 화면에 머물렀습니다. 원래 읽기 과제로 돌아가시겠습니까?"

SESSIONS = {}
LATEST_SESSION_ID = ""


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


def _latest_session():
    if LATEST_SESSION_ID and LATEST_SESSION_ID in SESSIONS:
        return SESSIONS[LATEST_SESSION_ID]
    if not SESSIONS:
        return None
    return next(reversed(SESSIONS.values()))


def _requested_or_latest_session():
    return SESSIONS.get(request.args.get("session_id", "")) or _latest_session()


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


def generate_intervention_message(condition, snapshot, message_type="monitoring"):
    if message_type == "game_prompt":
        return GAME_PROMPT_MESSAGE
    if condition == "concrete":
        return CONCRETE_RETURN_MESSAGE
    return ABSTRACT_RETURN_MESSAGE


def build_intervention_state(session, get_tracker, force=False):
    if not session:
        return {
            "active": False,
            "condition": "",
            "message": "",
            "type": "monitoring",
            "session_id": "",
        }

    if session.get("returned_to_task_at_ms"):
        return {
            "active": False,
            "condition": session["condition"],
            "message": "",
            "type": "monitoring",
            "session_id": session["session_id"],
        }

    if not session.get("game_start_clicked_at_ms"):
        reading_elapsed = _elapsed_seconds(session.get("started_at_ms"))
        prompt_due = reading_elapsed >= MINIGAME_AFTER_SECONDS
        if force or prompt_due:
            if not session.get("distraction_prompt_shown_at_ms"):
                session["distraction_prompt_shown_at_ms"] = _now_ms()
                _append_event({
                    "event_type": "distraction_prompt_shown",
                    "session_id": session["session_id"],
                    "participant_id": session.get("participant_id", ""),
                    "condition": session["condition"],
                    "message_type": "game_prompt",
                    "message": GAME_PROMPT_MESSAGE,
                    "payload": {"reading_elapsed_sec": reading_elapsed, "trigger": "timer" if prompt_due else "admin_force"},
                })
            return {
                "active": True,
                "condition": session["condition"],
                "message": GAME_PROMPT_MESSAGE,
                "type": "game_prompt",
                "session_id": session["session_id"],
                "display": "web_overlay",
            }

        return {
            "active": False,
            "condition": session["condition"],
            "message": "",
            "type": "monitoring",
            "session_id": session["session_id"],
            "display": "",
        }

    game_entered_at = session.get("game_entered_at_ms")
    eligible = bool(game_entered_at and _elapsed_seconds(game_entered_at) >= INTERVENTION_AFTER_SECONDS)
    if not force and not session.get("return_intervention_active") and not eligible:
        return {
            "active": False,
            "condition": session["condition"],
            "message": "",
            "type": "monitoring",
            "session_id": session["session_id"],
            "display": "",
        }

    if not session.get("return_intervention_active"):
        snapshot = _tracker_snapshot(get_tracker())
        session["intervention_id"] = f"msg-{uuid4().hex[:12]}"
        session["intervention_snapshot"] = snapshot
        session["intervention_message"] = generate_intervention_message(session["condition"], snapshot, "monitoring")
        session["return_intervention_active"] = True
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
            "payload": {
                "trigger": "game_30s" if not force else "admin_force",
                "game_elapsed_sec": _elapsed_seconds(game_entered_at),
            },
        })

    return {
        "active": True,
        "condition": session["condition"],
        "message": session.get("intervention_message", ""),
        "type": "monitoring",
        "session_id": session["session_id"],
        "intervention_id": session.get("intervention_id", ""),
        "display": "desktop_widget",
        "return_url": f"/experiment?session_id={session['session_id']}",
    }


def create_urp_experiment_blueprint(get_tracker):
    blueprint = Blueprint("urp_experiment", __name__)

    @blueprint.route("/experiment")
    def participant_view():
        return render_template("urp_participant.html")

    @blueprint.route("/experiment/game")
    def game_view():
        return render_template("urp_game.html")

    @blueprint.route("/experiment/admin")
    @blueprint.route("/experiment/urp")
    def admin_view():
        return render_template("urp_admin.html")

    @blueprint.route("/experiment/survey")
    def survey_view():
        return render_template("urp_survey.html")

    @blueprint.route("/experiment/api/session", methods=["POST"])
    def create_participant_session():
        global LATEST_SESSION_ID
        session = {
            "session_id": f"urp-{uuid4().hex[:12]}",
            "participant_id": "",
            "condition": random.choice(CONDITIONS),
            "started_at_ms": _now_ms(),
            "created_by": "participant_view",
            "intervention_active": False,
        }
        SESSIONS[session["session_id"]] = session
        LATEST_SESSION_ID = session["session_id"]
        _append_event({
            "event_type": "participant_session_started",
            "session_id": session["session_id"],
            "condition": session["condition"],
            "payload": {"public_view": True},
        })
        return jsonify(_public_session(session))

    @blueprint.route("/experiment/api/session_state", methods=["GET"])
    def participant_session_state():
        session = SESSIONS.get(request.args.get("session_id", ""))
        if not session:
            return jsonify({"error": "session not found"}), 404
        return jsonify(_public_session(session))

    @blueprint.route("/experiment/api/game_start_clicked", methods=["POST"])
    def game_start_clicked():
        data = request.json or {}
        session = SESSIONS.get(data.get("session_id", ""))
        if not session:
            return jsonify({"error": "session not found"}), 404
        if not session.get("game_start_clicked_at_ms"):
            session["game_start_clicked_at_ms"] = _now_ms()
            _append_event({
                "event_type": "game_start_clicked",
                "session_id": session["session_id"],
                "participant_id": session.get("participant_id", ""),
                "condition": session["condition"],
                "message_type": "game_prompt",
                "message": GAME_PROMPT_MESSAGE,
            })
        return jsonify({"status": "ok", "session_id": session["session_id"]})

    @blueprint.route("/experiment/api/game_entered", methods=["POST"])
    def game_entered():
        data = request.json or {}
        session = SESSIONS.get(data.get("session_id", ""))
        if not session:
            return jsonify({"error": "session not found"}), 404
        if not session.get("game_entered_at_ms"):
            session["game_entered_at_ms"] = _now_ms()
            _append_event({
                "event_type": "game_entered",
                "session_id": session["session_id"],
                "participant_id": session.get("participant_id", ""),
                "condition": session["condition"],
            })
        return jsonify({"status": "ok", "session_id": session["session_id"]})

    @blueprint.route("/experiment/api/minigame_started", methods=["POST"])
    def minigame_started():
        # Backward-compatible alias for early prototypes.
        return game_entered()

    @blueprint.route("/experiment/api/intervention_state", methods=["GET"])
    def intervention_state():
        session = _requested_or_latest_session()
        if session and request.args.get("client") == "desktop-widget":
            session["desktop_widget_last_poll_at_ms"] = _now_ms()
        state = build_intervention_state(session, get_tracker, force=False)
        if session and state.get("active") and state.get("type") == "monitoring":
            state["web_fallback_active"] = _elapsed_seconds(session.get("desktop_widget_last_poll_at_ms")) > 4
        return jsonify(state)

    @blueprint.route("/experiment/api/intervention_ack", methods=["POST"])
    def intervention_ack():
        data = request.json or {}
        session = SESSIONS.get(data.get("session_id", "")) or _latest_session()
        if not session:
            return jsonify({"error": "session not found"}), 404
        clicked_at = _now_ms()
        intervention_shown_at = session.get("intervention_started_at_ms") or clicked_at
        return_latency_sec = max(0, round((clicked_at - intervention_shown_at) / 1000, 3))
        session["return_intervention_active"] = False
        session["returned_to_task_at_ms"] = clicked_at
        _append_event({
            "event_type": "return_to_task",
            "session_id": session["session_id"],
            "participant_id": session.get("participant_id", ""),
            "condition": session["condition"],
            "intervention_id": session.get("intervention_id", ""),
            "message_type": "monitoring",
            "message": session.get("intervention_message", ""),
            "snapshot": session.get("intervention_snapshot", {}),
            "payload": {
                "return_latency_sec": return_latency_sec,
                "intervention_shown_at_ms": intervention_shown_at,
                "return_clicked_at_ms": clicked_at,
            },
        })
        return jsonify({
            "status": "ok",
            "return_latency_sec": return_latency_sec,
            "return_url": f"/experiment?session_id={session['session_id']}",
        })

    @blueprint.route("/experiment/api/intervention_continue_game", methods=["POST"])
    def intervention_continue_game():
        data = request.json or {}
        session = SESSIONS.get(data.get("session_id", "")) or _latest_session()
        if not session:
            return jsonify({"error": "session not found"}), 404
        _append_event({
            "event_type": "intervention_dismissed_continue_game",
            "session_id": session["session_id"],
            "participant_id": session.get("participant_id", ""),
            "condition": session["condition"],
            "intervention_id": session.get("intervention_id", ""),
            "message_type": "monitoring",
            "message": session.get("intervention_message", ""),
            "snapshot": session.get("intervention_snapshot", {}),
            "payload": {
                "intervention_shown_at_ms": session.get("intervention_started_at_ms"),
                "dismissed_at_ms": _now_ms(),
            },
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
        global LATEST_SESSION_ID
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
        LATEST_SESSION_ID = session["session_id"]
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
