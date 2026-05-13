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

async function fetchFocusStatus() {
  const config = readJson("./config/widgetConfig.json");
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
  const config = readJson("./config/widgetConfig.json");
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

contextBridge.exposeInMainWorld("desktopWidget", {
  platform: process.platform,
  close: () => ipcRenderer.send("widget:close"),
  getFocusStatus: fetchFocusStatus,
  completeCurrentTask,
  log,
  getInitialData: () => ({
    config: readJson("./config/widgetConfig.json"),
    tasks: readJson("./data/mockTasks.json"),
    focus: readJson("./data/mockFocusState.json"),
  }),
});
