import json
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from flask import Blueprint, jsonify, render_template, request


REPORT_TERMS = [
    "\ub808\ud3ec\ud2b8",
    "\ubcf4\uace0\uc11c",
    "\uacfc\uc81c",
    "\ub17c\ubb38",
    "\uae00",
]
STUDY_TERMS = [
    "\uc2dc\ud5d8",
    "\uc911\uac04\uace0\uc0ac",
    "\uae30\ub9d0",
    "\uacf5\ubd80",
    "\uc554\uae30",
]
RESEARCH_TERMS = [
    "\uc790\ub8cc\uc870\uc0ac",
    "\uc870\uc0ac",
    "\ub9ac\uc11c\uce58",
]
CODING_TERMS = [
    "\ucf54\ub529",
    "\uac1c\ubc1c",
    "\ud504\ub85c\uadf8\ub798\ubc0d",
]

mobile_plan_store = {
    "latest": None,
    "plans": {},
}

CURRENT_PLAN_PATH = Path(__file__).resolve().parent / "data" / "current_plan.json"


def clamp_minutes(value, default=25, minimum=5, maximum=180):
    try:
        minutes = int(value)
    except (TypeError, ValueError):
        minutes = default
    return max(minimum, min(minutes, maximum))


def has_any_korean_term(text, terms):
    return any(term in text for term in terms)


def split_goal_into_steps(goal, total_minutes=45):
    goal_text = (goal or "").strip()
    lower_goal = goal_text.lower()
    is_report = any(term in lower_goal for term in ["report", "essay", "paper"]) or has_any_korean_term(
        goal_text, REPORT_TERMS
    )
    is_study = any(term in lower_goal for term in ["exam", "study", "quiz"]) or has_any_korean_term(
        goal_text, STUDY_TERMS
    )
    is_research = any(term in lower_goal for term in ["research", "survey"]) or has_any_korean_term(
        goal_text, RESEARCH_TERMS
    )

    if is_report:
        template = [
            ("\ubb38\uc11c \uc5f4\uace0 \uc81c\ubaa9\ub9cc \uc4f0\uae30", 5),
            ("\uc790\ub8cc \ub9c1\ud06c 3\uac1c \ucc3e\uae30", 15),
            ("\ubaa9\ucc28\ub97c \uc138 \uc904\ub85c \uc7a1\uae30", 8),
            ("\uc11c\ub860 \ucd08\uc548 \uc138 \ubb38\uc7a5 \uc4f0\uae30", 10),
            ("\ub2e4\uc74c\uc5d0 \uc774\uc5b4 \uc4f8 \ud55c \uc904 \ub0a8\uae30\uae30", 5),
        ]
    elif is_study:
        template = [
            ("\uacf5\ubd80\ud560 \ubc94\uc704 \ud55c \uc7a5\uc5d0 \uc801\uae30", 5),
            ("\uac00\uc7a5 \uc26c\uc6b4 \uac1c\ub150 3\uac1c \uccb4\ud06c\ud558\uae30", 10),
            ("\ud5f7\uac08\ub9ac\ub294 \ubd80\ubd84 2\uac1c \ud45c\uc2dc\ud558\uae30", 10),
            ("\uc9e7\uc740 \ubb38\uc81c\ub098 \uc608\uc2dc 3\uac1c \ud480\uae30", 15),
            ("\ub2e4\uc74c \ubcf5\uc2b5 \uc2dc\uc791\uc810 \uc801\uae30", 5),
        ]
    elif is_research:
        template = [
            ("\uac80\uc0c9 \ud0a4\uc6cc\ub4dc 3\uac1c \ub9cc\ub4e4\uae30", 5),
            ("\uc4f8\ub9cc\ud55c \ub9c1\ud06c 5\uac1c \ubaa8\uc73c\uae30", 15),
            ("\uac01 \ub9c1\ud06c\ub97c \ud55c \uc904\ub85c \uc694\uc57d\ud558\uae30", 15),
            ("\ubc84\ub9b4 \uc790\ub8cc 2\uac1c \uc9c0\uc6b0\uae30", 5),
            ("\uccab \ubb38\ub2e8\uc5d0 \uc4f8 \uadfc\uac70 \ud558\ub098 \uace0\ub974\uae30", 5),
        ]
    else:
        template = [
            ("\ud30c\uc77c\uc774\ub098 \uc791\uc5c5 \ud654\uba74 \uc5f4\uae30", 5),
            ("\ud574\uc57c \ud560 \uc77c\uc744 \uc138 \ub369\uc5b4\ub9ac\ub85c \ub098\ub204\uae30", 8),
            ("\uac00\uc7a5 \uc26c\uc6b4 \uccab \uc870\uac01\ub9cc \ub05d\ub0b4\uae30", 12),
            ("\ub9c9\ud788\ub294 \uc9c0\uc810 \ud558\ub098 \uc801\uae30", 5),
            ("\ub2e4\uc74c \ud589\ub3d9 \ud55c \uc904 \ub0a8\uae30\uae30", 5),
        ]

    total_template_minutes = sum(item[1] for item in template)
    target_total = clamp_minutes(total_minutes, default=max(total_template_minutes, 35), minimum=15, maximum=180)
    scale = target_total / total_template_minutes
    steps = []
    for index, (title, minutes) in enumerate(template, start=1):
        step_minutes = max(3, int(round(minutes * scale)))
        steps.append({
            "id": f"step_{index}",
            "title": title,
            "duration_minutes": step_minutes,
            "category": "WORK",
            "status": "pending",
            "order": index,
        })
    if steps:
        delta = target_total - sum(step["duration_minutes"] for step in steps)
        steps[-1]["duration_minutes"] = max(3, steps[-1]["duration_minutes"] + delta)
    return steps


def parse_list(value):
    if isinstance(value, list):
        raw_items = value
    else:
        raw_items = str(value or "").replace("\n", ",").split(",")
    items = []
    seen = set()
    for item in raw_items:
        cleaned = str(item).strip()
        if cleaned and cleaned.lower() not in seen:
            items.append(cleaned)
            seen.add(cleaned.lower())
    return items


def save_current_plan(plan):
    CURRENT_PLAN_PATH.parent.mkdir(parents=True, exist_ok=True)
    with CURRENT_PLAN_PATH.open("w", encoding="utf-8") as plan_file:
        json.dump(plan, plan_file, ensure_ascii=False, indent=2)
        plan_file.write("\n")


def load_current_plan():
    if not CURRENT_PLAN_PATH.exists():
        return None
    try:
        with CURRENT_PLAN_PATH.open("r", encoding="utf-8") as plan_file:
            return json.load(plan_file)
    except (OSError, json.JSONDecodeError):
        return None


def build_mobile_plan(goal, total_minutes=45, blocked_apps=None, blocked_sites=None, metadata_permission=False):
    steps = split_goal_into_steps(goal, total_minutes)
    plan_id = f"plan-{uuid4().hex[:12]}"
    plan = {
        "plan_id": plan_id,
        "goal_title": (goal or "").strip() or "\uc774\ub984 \uc5c6\ub294 \uc791\uc5c5",
        "created_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "metadata_permission": bool(metadata_permission),
        "blocked_apps": parse_list(blocked_apps),
        "blocked_sites": parse_list(blocked_sites),
        "steps": steps,
    }
    mobile_plan_store["latest"] = plan
    mobile_plan_store["plans"][plan_id] = plan
    save_current_plan(plan)
    return plan


def create_mobile_blueprint(get_tracker):
    mobile_bp = Blueprint("mobile", __name__)

    @mobile_bp.route("/mobile")
    def mobile():
        return render_template("mobile.html")

    @mobile_bp.route("/api/mobile/plan", methods=["POST"])
    def create_mobile_plan():
        data = request.json or {}
        plan = build_mobile_plan(
            data.get("goal", ""),
            data.get("total_minutes", 45),
            data.get("blocked_apps", ""),
            data.get("blocked_sites", ""),
            data.get("metadata_permission", False),
        )
        return jsonify(plan)

    @mobile_bp.route("/api/mobile/latest_plan", methods=["GET"])
    def latest_mobile_plan():
        plan = mobile_plan_store["latest"] or load_current_plan()
        if plan:
            mobile_plan_store["latest"] = plan
            mobile_plan_store["plans"][plan["plan_id"]] = plan
        return jsonify(plan or {})

    @mobile_bp.route("/api/mobile/step_done", methods=["POST"])
    def mark_mobile_step_done():
        data = request.json or {}
        plan = mobile_plan_store["plans"].get(str(data.get("plan_id", "")))
        if not plan:
            return jsonify({"error": "Plan not found"}), 404
        step_id = str(data.get("step_id", ""))
        for step in plan["steps"]:
            if step["id"] == step_id:
                step["status"] = "completed" if bool(data.get("done", True)) else "pending"
                break
        mobile_plan_store["latest"] = plan
        save_current_plan(plan)
        return jsonify(plan)

    @mobile_bp.route("/api/mobile/start_plan", methods=["POST"])
    def start_mobile_plan():
        data = request.json or {}
        incoming_plan = data.get("plan")
        if isinstance(incoming_plan, dict) and incoming_plan.get("plan_id"):
            plan = incoming_plan
            mobile_plan_store["latest"] = plan
            mobile_plan_store["plans"][plan["plan_id"]] = plan
            save_current_plan(plan)
        else:
            plan = mobile_plan_store["plans"].get(str(data.get("plan_id", ""))) or mobile_plan_store["latest"]
        tracker = get_tracker()
        if not plan or not tracker:
            return jsonify({"error": "No mobile plan or tracker available"}), 400
        next_step = next((step for step in plan["steps"] if step.get("status") != "completed"), plan["steps"][0])
        for step in plan.get("steps", []):
            if step is next_step:
                step["status"] = "active"
            elif step.get("status") == "active":
                step["status"] = "pending"
        plan["current_step_index"] = max(0, int(next_step.get("order", 1)) - 1)
        plan["status"] = "active"
        plan["task_start_time"] = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
        mobile_plan_store["latest"] = plan
        mobile_plan_store["plans"][plan["plan_id"]] = plan
        save_current_plan(plan)
        task = f"{plan.get('goal_title', '')} - {next_step['title']}".strip(" -")
        blocked_apps = ", ".join(plan.get("blocked_apps", []))
        blocked_sites = ", ".join(plan.get("blocked_sites", []))
        metadata_permission = bool(plan.get("metadata_permission", True))
        tracker.start_monitoring(
            task,
            blocked_apps,
            next_step.get("duration_minutes", 25),
            "",
            blocked_sites,
            metadata_permission,
        )
        return jsonify({"status": "ok", "started_step": next_step, "plan": plan})

    return mobile_bp
