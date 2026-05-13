# Mobile-PC-Widget Demo Flow

This document describes the current demo path for the ADHD focus tracker prototype:
mobile is the planner, the PC localhost app is the execution launcher, and the
desktop widget is the always-on-top execution companion.

## Current Demo Shape

The repo currently supports these real connections:

- Mobile plan creation writes a shared plan to `data/current_plan.json`.
- The PC localhost launcher reads that plan through `GET /api/plan/current`.
- The PC launcher can start and stop the Electron widget through the existing
  Widget ON/OFF APIs.
- The desktop widget polls `http://localhost:5000/status` for focus status and
  falls back to local mock data if the PC API is unavailable.

Demo readiness gaps in the current repo:

- `POST /api/plan/start` is not implemented yet.
- `POST /api/tasks/complete_current` is not implemented yet.
- `/status` does not yet expose `current_task`, `next_task`, `plan_progress`,
  `metadata_permission`, `blocked_sites`, `finishing`, or `overtime`.
- The widget still uses local `mockTasks.json` for task title/progress display.
- The widget complete button still completes mock tasks locally.
- `metadata_permission` is stored in the plan, but the detection branch is not
  fully enforced in the current tracking logic.

## Setup Commands

Run the PC Flask app from the repo root:

```powershell
python focus_tracker.pyw
```

Open the mobile planner from the same Flask server:

```text
http://localhost:5000/mobile
```

Open the PC launcher:

```text
http://localhost:5000
```

Install and run the desktop widget directly:

```powershell
cd desktop-widget
npm install
npm start
```

Check the widget JavaScript:

```powershell
cd desktop-widget
npm run check
```

Chrome URL detection depends on the Chrome extension sending URL updates to the
PC app's `/update_tab` endpoint. Load/enable the extension before filming the
YouTube blocked-site portion of the demo.

## Demo Walkthrough

1. Start the PC app with `python focus_tracker.pyw`.
2. Open `http://localhost:5000/mobile`.
3. Enter the large goal: `중간고사 레포트 쓰기`.
4. Generate micro tasks with the mobile planner.
5. Set `blocked_sites` to `youtube.com`.
6. Set `metadata_permission` to `true`.
7. Confirm `data/current_plan.json` contains the generated plan.
8. Open `http://localhost:5000`.
9. Confirm the PC launcher shows the mobile plan goal, steps, blocked apps/sites,
   and metadata permission state.
10. Click `Widget ON` to launch the Electron floating widget.
11. Confirm the widget appears and shows focus/status information.

The intended next-stage demo steps are listed below, but currently require the
missing task-start/task-complete/status-extension work:

1. Click `Start Plan`.
2. Confirm `/status.current_task` is the first pending task.
3. Confirm the widget shows the current task and remaining time from `/status`.
4. Click the widget complete button.
5. Confirm `POST /api/tasks/complete_current` completes the current task.
6. Confirm `/status.current_task` changes to the next task.
7. Visit YouTube and confirm `/status.state` becomes distracted.
8. Use a short task duration to confirm finishing at 80% and overtime after 100%.

## Real vs Mock

Real in the current repo:

- Mobile form input to shared JSON plan state.
- `data/current_plan.json` as the cross-surface plan handoff.
- `GET /api/plan/current` for the PC launcher.
- PC launcher display of the mobile plan.
- Widget process launch via `Widget ON`.
- Widget polling of `/status` for focus state.

Mock or not yet wired:

- Widget task list: `desktop-widget/src/data/mockTasks.json`.
- Widget fallback focus state: `desktop-widget/src/data/mockFocusState.json`.
- Widget complete button: local mock completion only.
- Plan start from PC launcher: intended API is `POST /api/plan/start`.
- Task completion from widget: intended API is `POST /api/tasks/complete_current`.
- Widget task/timer/progress from `/status.current_task`, `/status.next_task`,
  and `/status.plan_progress`.
- Finishing/overtime task states.

## Filming Timeline

Use this 30-60 second beat sheet for a short recording:

- `0:00-0:30` Mobile: enter `중간고사 레포트 쓰기`, generate the plan, set
  `youtube.com`, enable metadata permission.
- `0:30-1:00` PC launcher: refresh `http://localhost:5000` and show the mobile
  plan details.
- `1:00-1:30` Click `Widget ON` and show the Electron floating widget.
- `1:30-2:00` Show current status/timer area in the widget. Note that task title
  is mock-backed until `/status.current_task` is implemented.
- `2:00-2:30` Show the intended complete-button moment. In the current repo this
  advances mock widget tasks only.
- `2:30-3:00` Show Chrome URL detection setup and the intended YouTube blocked
  site check.
- `3:00-3:30` Explain the intended finishing/overtime beat with a short-duration
  task once those states are implemented.

## Known Issues

- `.git/index.lock` permission errors can recur because the `.git` directory has
  Windows ACL DENY entries in some sessions.
- There is no root `README.md`; this `DEMO.md` is the current full-flow guide.
- Some requested demo steps describe the target product state but are not fully
  implemented in the current repo.
- Browser automation in Codex may block `localhost` or `127.0.0.1`, even when the
  app itself works in a normal browser.
- Chrome URL detection requires the extension to be enabled and successfully
  posting to `/update_tab`.
- The widget README is narrower than this full-flow document; prefer this file
  when rehearsing the end-to-end demo.

