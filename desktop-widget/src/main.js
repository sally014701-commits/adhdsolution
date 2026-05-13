const { app, BrowserWindow, ipcMain, screen } = require("electron");
const fs = require("fs");
const path = require("path");

app.commandLine.appendSwitch("disable-gpu-sandbox");

const WINDOW_WIDTH = 480;
const WINDOW_HEIGHT = 180;
const SCREEN_MARGIN = 24;
const LOG_PATH = path.join(__dirname, "..", "electron-crash.log");

function log(message, detail = "") {
  const line = `[${new Date().toISOString()}] ${message}${detail ? ` ${detail}` : ""}\n`;
  try {
    fs.appendFileSync(LOG_PATH, line, "utf8");
  } catch {
    // Logging must never prevent the widget from opening.
  }
}

function getSwitchValue(name) {
  const prefix = `--${name}=`;
  const arg = process.argv.find((value) => value.startsWith(prefix));
  return arg ? arg.slice(prefix.length) : "";
}

function ensureDir(dirPath) {
  if (!dirPath) {
    return;
  }
  try {
    fs.mkdirSync(dirPath, { recursive: true });
  } catch (error) {
    log("failed to create runtime path", `${dirPath} ${error.message}`);
  }
}

const userDataPath = getSwitchValue("user-data-dir");
const cachePath = getSwitchValue("disk-cache-dir");
const tempPath = path.join(userDataPath || path.join(__dirname, "..", "widget-runtime"), "temp");

ensureDir(userDataPath);
ensureDir(cachePath);
ensureDir(tempPath);

if (userDataPath) {
  app.setPath("userData", userDataPath);
  app.setPath("sessionData", userDataPath);
}
if (cachePath) {
  app.setPath("cache", cachePath);
}
if (tempPath) {
  app.setPath("temp", tempPath);
}

log("main process started");
log("runtime paths", JSON.stringify({
  userData: app.getPath("userData"),
  sessionData: app.getPath("sessionData"),
  cache: app.getPath("cache"),
  temp: app.getPath("temp"),
}));


function getWidgetBounds() {
  const { workArea } = screen.getPrimaryDisplay();
  const width = WINDOW_WIDTH;
  const height = WINDOW_HEIGHT;
  const x = Math.max(workArea.x, workArea.x + workArea.width - width - SCREEN_MARGIN);
  const y = Math.max(workArea.y, workArea.y + SCREEN_MARGIN);

  return {
    width,
    height,
    x,
    y,
  };
}

function createWindow() {
  log("createWindow called");
  const bounds = getWidgetBounds();
  const window = new BrowserWindow({
    ...bounds,
    frame: false,
    resizable: false,
    alwaysOnTop: true,
    skipTaskbar: true,
    transparent: true,
    show: true,
    backgroundColor: "#00000000",
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: false,
    },
  });
  log("BrowserWindow created", JSON.stringify(bounds));

  window.setAlwaysOnTop(true, "screen-saver");
  window.once("ready-to-show", () => {
    log("ready-to-show");
    window.show();
    window.focus();
    log("window shown");
  });
  window.webContents.on("did-finish-load", () => log("renderer did-finish-load"));
  window.webContents.on("console-message", (_event, level, message, line, sourceId) => {
    log("renderer console", JSON.stringify({ level, message, line, sourceId }));
  });
  window.webContents.on("render-process-gone", (_event, details) => {
    log("render-process-gone", JSON.stringify(details));
  });
  window.on("unresponsive", () => log("window unresponsive"));
  window.on("closed", () => log("window closed"));
  window.loadFile(path.join(__dirname, "index.html"));
}

ipcMain.on("widget:close", (event) => {
  BrowserWindow.fromWebContents(event.sender)?.close();
});

ipcMain.on("widget:log", (_event, message, detail = "") => {
  log(`renderer ${message}`, detail);
});

app.whenReady().then(() => {
  log("app ready");
  createWindow();

  app.on("activate", () => {
    if (BrowserWindow.getAllWindows().length === 0) {
      createWindow();
    }
  });
});

app.on("window-all-closed", () => {
  log("window-all-closed");
  if (process.platform !== "darwin") {
    app.quit();
  }
});

app.on("render-process-gone", (_event, _webContents, details) => {
  log("app render-process-gone", JSON.stringify(details));
});

app.on("child-process-gone", (_event, details) => {
  log("child-process-gone", JSON.stringify(details));
});
