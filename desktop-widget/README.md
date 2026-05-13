# ADHD Desktop Widget MVP

Windows always-on-top floating widget for executing one micro task at a time.

## Run

```powershell
cd desktop-widget
npm install
npm start
```

The widget opens as a small frameless vertical window near the top-right of the primary display. It is independent from the existing Python focus tracker, Chrome extension, and web UI.

## Focus Status API

The widget polls the existing PC app status endpoint once per second:

```text
http://localhost:5000/status
```

It reads these fields when available:

- `state`
- `current_app`
- `current_url`
- `activity`
- `idle_time`
- `window_switch`
- `elapsed_time`

Supported state mapping:

- `focused` or `집중`: green/blue border
- `warning` or `마무리 필요`: yellow border
- `distracted` or `이탈`: red border with a light shake
- `idle` or `비활동`: gray border

If the API is unavailable, the widget falls back to `src/data/mockFocusState.json`.
Micro task data remains local mock data in the current repo. See `../DEMO.md`
for the full mobile-PC-widget demo flow and current readiness gaps.
