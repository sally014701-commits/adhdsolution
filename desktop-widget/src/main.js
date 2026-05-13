const { app, BrowserWindow, ipcMain, screen } = require("electron");
const path = require("path");

const WINDOW_WIDTH = 480;
const WINDOW_HEIGHT = 180;
const SCREEN_MARGIN = 16;

function getWidgetBounds() {
  const { workArea } = screen.getPrimaryDisplay();

  return {
    width: WINDOW_WIDTH,
    height: WINDOW_HEIGHT,
    x: workArea.x + Math.round((workArea.width - WINDOW_WIDTH) / 2),
    y: workArea.y + SCREEN_MARGIN,
  };
}

function createWindow() {
  const window = new BrowserWindow({
    ...getWidgetBounds(),
    frame: false,
    resizable: false,
    alwaysOnTop: true,
    skipTaskbar: true,
    transparent: true,
    backgroundColor: "#00000000",
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
    },
  });

  window.setAlwaysOnTop(true, "screen-saver");
  window.loadFile(path.join(__dirname, "index.html"));
}

ipcMain.on("widget:close", (event) => {
  BrowserWindow.fromWebContents(event.sender)?.close();
});

app.whenReady().then(() => {
  createWindow();

  app.on("activate", () => {
    if (BrowserWindow.getAllWindows().length === 0) {
      createWindow();
    }
  });
});

app.on("window-all-closed", () => {
  if (process.platform !== "darwin") {
    app.quit();
  }
});
