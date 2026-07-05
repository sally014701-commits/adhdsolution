const { contextBridge, ipcRenderer } = require("electron");
const fs = require("fs");
const path = require("path");

function readJson(relativePath) {
  const filePath = path.join(__dirname, relativePath);
  return JSON.parse(fs.readFileSync(filePath, "utf8"));
}

function log(message, detail = "") {
  ipcRenderer.send("widget:log", message, typeof detail === "string" ? detail : JSON.stringify(detail));
}

function getWidgetConfig() {
  const config = readJson("./config/widgetConfig.json");
  return {
    ...config,
    mode: process.env.FOCUSPLAN_WIDGET_MODE || config.mode,
  };
}

async function fetchFocusStatus() {
  const config = getWidgetConfig();
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 1800);

  try {
    log("fetch status start", config.integration.statusApiUrl);
    const response = await fetch(config.integration.statusApiUrl, {
      signal: controller.signal,
      cache: "no-store",
    });

    if (!response.ok) {
      throw new Error(`Status API returned ${response.status}`);
    }

    return {
      ok: true,
      source: "api",
      status: await response.json(),
    };
  } catch (error) {
    log("fetch status failed", error.message);
    return {
      ok: false,
      source: "mock",
      error: error.message,
      status: readJson("./data/mockFocusState.json"),
    };
  } finally {
    clearTimeout(timeout);
  }
}

async function completeCurrentTask() {
  const config = getWidgetConfig();
  const completeUrl = config.integration.statusApiUrl.replace(/\/status$/, "/api/tasks/complete_current");
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 1800);

  try {
    log("complete current start", completeUrl);
    const response = await fetch(completeUrl, {
      method: "POST",
      signal: controller.signal,
      cache: "no-store",
    });
    const body = await response.json().catch(() => ({}));

    if (!response.ok) {
      throw new Error(body.error || `Complete API returned ${response.status}`);
    }

    return {
      ok: true,
      result: body,
    };
  } catch (error) {
    log("complete current failed", error.message);
    return {
      ok: false,
      error: error.message,
    };
  } finally {
    clearTimeout(timeout);
  }
}

async function fetchInterventionState() {
  const config = getWidgetConfig();
  const url = config.integration.interventionApiUrl;
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 1800);

  try {
    log("fetch intervention start", url);
    const response = await fetch(url, {
      signal: controller.signal,
      cache: "no-store",
    });

    if (!response.ok) {
      throw new Error(`Intervention API returned ${response.status}`);
    }

    return {
      ok: true,
      source: "api",
      state: await response.json(),
    };
  } catch (error) {
    log("fetch intervention failed", error.message);
    return {
      ok: false,
      source: "none",
      error: error.message,
      state: { active: false },
    };
  } finally {
    clearTimeout(timeout);
  }
}

async function postExperimentAction(path, payload = {}) {
  const config = getWidgetConfig();
  const baseUrl = new URL(config.integration.interventionApiUrl);
  const url = `${baseUrl.origin}${path}`;
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 1800);

  try {
    log("post experiment action", url);
    const response = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
      signal: controller.signal,
      cache: "no-store",
    });
    const body = await response.json().catch(() => ({}));

    if (!response.ok) {
      throw new Error(body.error || `Experiment API returned ${response.status}`);
    }

    return { ok: true, result: body };
  } catch (error) {
    log("post experiment action failed", error.message);
    return { ok: false, error: error.message };
  } finally {
    clearTimeout(timeout);
  }
}

async function returnToTask(sessionId) {
  const result = await postExperimentAction("/experiment/api/intervention_ack", { session_id: sessionId || "" });
  if (result.ok && result.result?.return_url) {
    ipcRenderer.send("widget:open-url", result.result.return_url);
  }
  return result;
}

function continueGame(sessionId) {
  return postExperimentAction("/experiment/api/intervention_continue_game", { session_id: sessionId || "" });
}

contextBridge.exposeInMainWorld("desktopWidget", {
  platform: process.platform,
  close: () => ipcRenderer.send("widget:close"),
  setVisible: (visible) => ipcRenderer.send("widget:set-visible", Boolean(visible)),
  getFocusStatus: fetchFocusStatus,
  getInterventionState: fetchInterventionState,
  returnToTask,
  continueGame,
  completeCurrentTask,
  log,
  getInitialData: () => ({
    config: getWidgetConfig(),
    tasks: readJson("./data/mockTasks.json"),
    focus: readJson("./data/mockFocusState.json"),
  }),
});
