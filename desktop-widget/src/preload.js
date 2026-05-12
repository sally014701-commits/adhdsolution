const { contextBridge, ipcRenderer } = require("electron");
const fs = require("fs");
const path = require("path");

function readJson(relativePath) {
  const filePath = path.join(__dirname, relativePath);
  return JSON.parse(fs.readFileSync(filePath, "utf8"));
}

async function fetchFocusStatus() {
  const config = readJson("./config/widgetConfig.json");
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 800);

  try {
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

contextBridge.exposeInMainWorld("desktopWidget", {
  platform: process.platform,
  close: () => ipcRenderer.send("widget:close"),
  getFocusStatus: fetchFocusStatus,
  getInitialData: () => ({
    config: readJson("./config/widgetConfig.json"),
    tasks: readJson("./data/mockTasks.json"),
    focus: readJson("./data/mockFocusState.json"),
  }),
});
