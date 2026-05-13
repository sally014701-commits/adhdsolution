const FOCUS_LABELS = {
  focused: "Focused",
  warning: "Warning",
  distracted: "Distracted",
  idle: "Idle",
  overtime: "Overtime",
  completed: "Done",
};

const STATE_ALIASES = {
  focused: "focused",
  "집중": "focused",
  "집중 중": "focused",
  warning: "warning",
  finishing: "warning",
  "마무리 필요": "warning",
  "마무리": "warning",
  "마무리 중": "warning",
  "주의": "warning",
  overtime: "overtime",
  "시간초과": "overtime",
  distracted: "distracted",
  "이탈": "distracted",
  idle: "idle",
  "비활동": "idle",
  completed: "completed",
};

const state = {
  tasks: [],
  isAnimating: false,
  statusSource: "mock",
};

function logWidget(message, detail = "") {
  window.desktopWidget?.log?.(message, detail);
}

const FALLBACK_DATA = {
  config: {
    audio: {
      completionSoundPath: "./assets/audio/completion-placeholder.mp3",
      fallbackBeep: true,
    },
  },
  focus: {
    state: "focused",
    current_app: "Mock Workspace",
    current_url: "https://example.local/demo-task",
    activity: "mock",
    idle_time: 0,
    window_switch: 0,
    elapsed_time: 0,
  },
  tasks: [
    {
      id: 1,
      title: "워드 켜고 제목 쓰기",
      duration: 5,
      status: "pending",
    },
    {
      id: 2,
      title: "자료조사 링크 3개 찾기",
      duration: 15,
      status: "pending",
    },
    {
      id: 3,
      title: "서론 세 줄 쓰기",
      duration: 10,
      status: "pending",
    },
  ],
};

const elements = {
  shell: document.querySelector(".widget-shell"),
  taskPanel: document.querySelector("#taskPanel"),
  focusLabel: document.querySelector("#focusLabel"),
  currentTaskTitle: document.querySelector("#currentTaskTitle"),
  currentTaskDuration: document.querySelector("#currentTaskDuration"),
  nextTaskTitle: document.querySelector("#nextTaskTitle"),
  nextTaskDuration: document.querySelector("#nextTaskDuration"),
  progressFill: document.querySelector("#progressFill"),
  progressText: document.querySelector("#progressText"),
  currentApp: document.querySelector("#currentApp"),
  currentUrl: document.querySelector("#currentUrl"),
  statusMeta: document.querySelector("#statusMeta"),
  completeButton: document.querySelector("#completeButton"),
  closeButton: document.querySelector("#closeButton"),
};

function getPendingTasks() {
  return state.tasks.filter((task) => task.status === "pending");
}

function getProgress() {
  const completed = state.tasks.filter((task) => task.status === "completed").length;
  return {
    completed,
    total: state.tasks.length,
    percent: state.tasks.length === 0 ? 0 : Math.round((completed / state.tasks.length) * 100),
  };
}

function formatDuration(minutes) {
  const safeMinutes = Number(minutes) || 0;
  return `${String(safeMinutes).padStart(2, "0")}:00`;
}

function formatTimer(seconds, overrunSeconds = 0) {
  const overrun = Math.max(0, Number(overrunSeconds) || 0);
  const value = overrun > 0 ? overrun : Math.max(0, Number(seconds) || 0);
  const minutes = Math.floor(value / 60);
  const rest = value % 60;
  return `${overrun > 0 ? "+" : ""}${String(minutes).padStart(2, "0")}:${String(rest).padStart(2, "0")}`;
}

function formatSeconds(seconds) {
  const value = Number(seconds) || 0;

  if (value < 60) {
    return `${value}초`;
  }

  return `${Math.floor(value / 60)}분 ${value % 60}초`;
}

function normalizeFocusState(rawState) {
  const original = String(rawState ?? "focused").trim();
  const lower = original.toLowerCase();
  return STATE_ALIASES[lower] ?? STATE_ALIASES[original] ?? "focused";
}

function normalizeStatusTask(task) {
  if (!task) {
    return null;
  }
  if (typeof task === "string") {
    return {
      title: task,
      duration_minutes: 0,
    };
  }
  return {
    ...task,
    title: task.title || task.name || "작업",
    duration_minutes: Number(task.duration_minutes ?? task.duration ?? 0) || 0,
  };
}

function renderTasks() {
  const [currentTask, nextTask] = getPendingTasks();
  const progress = getProgress();

  if (currentTask) {
    elements.currentTaskTitle.textContent = currentTask.title;
    elements.currentTaskDuration.textContent = formatDuration(currentTask.duration);
    elements.completeButton.disabled = false;
  } else {
    elements.currentTaskTitle.textContent = "오늘 할 일 완료";
    elements.currentTaskDuration.textContent = "잘했어요";
    elements.completeButton.disabled = true;
  }

  elements.nextTaskTitle.textContent = nextTask ? nextTask.title : "다음 할 일 없음";
  elements.nextTaskDuration.textContent = nextTask ? ` · ${nextTask.duration}분` : "";
  elements.progressFill.style.width = `${progress.percent}%`;
  elements.progressText.textContent = `오늘의 퀘스트 ${progress.total}개 중 ${progress.completed}개 완료`;
}

function renderStatusTasks(status, source) {
  logWidget("render status tasks", {
    source,
    title: status?.current_task?.title || status?.current_task || "",
    remaining_time: status?.remaining_time,
    progress: status?.plan_progress,
  });
  if (source !== "api") {
    renderTasks();
    elements.progressText.textContent = "PC 앱 연결 대기 · mock fallback";
    return;
  }

  const currentTask = normalizeStatusTask(status.current_task);
  const nextTask = normalizeStatusTask(status.next_task);
  const planProgress = status.plan_progress || {};
  const completed = Number(planProgress.completed) || 0;
  const total = Number(planProgress.total) || 0;
  const planPercent = Number(planProgress.percent) || 0;
  const taskProgress = Number(status.time_progress);
  const progressPercent = Number.isFinite(taskProgress)
    ? Math.max(0, Math.min(100, Math.round(taskProgress * 100)))
    : Math.max(0, Math.min(100, Math.round(planPercent)));

  if (currentTask) {
    elements.currentTaskTitle.textContent = currentTask.title;
    elements.currentTaskDuration.textContent = formatTimer(status.remaining_time, status.overrun_seconds);
    elements.completeButton.disabled = false;
  } else if (status.plan_completed || status.state === "completed") {
    elements.currentTaskTitle.textContent = "오늘 할 일 완료";
    elements.currentTaskDuration.textContent = "잘했어요";
    elements.completeButton.disabled = true;
  } else {
    elements.currentTaskTitle.textContent = "작업 대기 중";
    elements.currentTaskDuration.textContent = "--:--";
    elements.completeButton.disabled = true;
  }

  elements.nextTaskTitle.textContent = nextTask ? nextTask.title : "다음 할 일 없음";
  elements.nextTaskDuration.textContent = nextTask && nextTask.duration_minutes
    ? ` · ${nextTask.duration_minutes}분`
    : "";
  elements.progressFill.style.width = `${progressPercent}%`;
  elements.progressText.textContent = total > 0
    ? `오늘의 퀘스트 ${total}개 중 ${completed}개 완료 · ${Math.round(planPercent)}%`
    : "PC plan 대기 중";
}

function renderFocusStatus(status, source) {
  const focusState = normalizeFocusState(status.state_code || status.state);
  elements.shell.dataset.focusState = focusState;
  elements.shell.dataset.statusSource = source;
  elements.focusLabel.textContent = FOCUS_LABELS[focusState] ?? FOCUS_LABELS.focused;

  elements.currentApp.textContent = status.current_app || "알 수 없음";
  elements.currentUrl.textContent = status.current_url || "-";
  elements.currentUrl.title = status.current_url || "";

  const activity = status.activity || "unknown";
  const idleTime = formatSeconds(status.idle_time);
  const elapsedTime = formatSeconds(status.elapsed_time);
  const switchCount = Number(status.window_switch) || 0;
  const sourceLabel = source === "api" ? "API 연결됨" : "mock fallback";
  if (source !== "api") {
    console.info("desktop-widget using mock fallback status");
  }

  elements.statusMeta.textContent =
    `${sourceLabel} · ${status.transition_message || activity} · idle ${idleTime} · switch ${switchCount} · ${elapsedTime}`;
}

function playCompletionSound(config) {
  const audioPath = config?.audio?.completionSoundPath;
  const audio = audioPath ? new Audio(audioPath) : null;

  if (audio) {
    audio.volume = 0.38;
    audio.play().catch(() => playFallbackBeep());
    return;
  }

  playFallbackBeep();
}

function playFallbackBeep() {
  const AudioContext = window.AudioContext || window.webkitAudioContext;
  if (!AudioContext) {
    return;
  }

  const audioContext = new AudioContext();
  const oscillator = audioContext.createOscillator();
  const gain = audioContext.createGain();

  oscillator.type = "sine";
  oscillator.frequency.setValueAtTime(660, audioContext.currentTime);
  oscillator.frequency.exponentialRampToValueAtTime(980, audioContext.currentTime + 0.12);
  gain.gain.setValueAtTime(0.001, audioContext.currentTime);
  gain.gain.exponentialRampToValueAtTime(0.16, audioContext.currentTime + 0.02);
  gain.gain.exponentialRampToValueAtTime(0.001, audioContext.currentTime + 0.18);

  oscillator.connect(gain);
  gain.connect(audioContext.destination);
  oscillator.start();
  oscillator.stop(audioContext.currentTime + 0.2);
}

function runCompletionAnimation(config, afterAnimation) {
  if (state.isAnimating) {
    return;
  }

  state.isAnimating = true;
  elements.taskPanel.classList.add("is-completing");
  elements.currentTaskTitle.classList.add("is-done");
  playCompletionSound(config);

  window.setTimeout(() => {
    elements.taskPanel.classList.remove("is-completing");
    elements.currentTaskTitle.classList.remove("is-done");
    afterAnimation?.();
    elements.taskPanel.classList.add("is-entering");

    window.setTimeout(() => {
      elements.taskPanel.classList.remove("is-entering");
      state.isAnimating = false;
    }, 260);
  }, 360);
}

async function completeCurrentTask(config, initialFocus) {
  if (state.isAnimating) {
    return;
  }

  if (window.desktopWidget?.completeCurrentTask) {
    const result = await window.desktopWidget.completeCurrentTask();
    logWidget("complete current result", result);
    if (result.ok) {
      runCompletionAnimation(config, () => {
        refreshFocusStatus(initialFocus);
      });
      return;
    }

    if (state.statusSource === "api") {
      console.error("Failed to complete PC task:", result.error);
      elements.statusMeta.textContent = `완료 처리 실패 · ${result.error}`;
      return;
    }

    console.info("desktop-widget complete API unavailable; using mock fallback", result.error);
  }

  const [currentTask] = getPendingTasks();
  if (!currentTask) {
    return;
  }
  currentTask.status = "completed";
  runCompletionAnimation(config, renderTasks);
}

async function refreshFocusStatus(initialFocus) {
  if (!window.desktopWidget?.getFocusStatus) {
    state.statusSource = "mock";
    renderFocusStatus(initialFocus, "mock");
    renderStatusTasks(initialFocus, "mock");
    return;
  }

  const result = await window.desktopWidget.getFocusStatus();
  state.statusSource = result.source;
  logWidget("refresh focus status result", {
    source: result.source,
    ok: result.ok,
    state: result.status?.state_code || result.status?.state,
    currentTask: result.status?.current_task?.title || result.status?.current_task || "",
    remaining: result.status?.remaining_time,
    error: result.error || "",
  });
  if (result.source !== "api") {
    console.info("desktop-widget status API unavailable; using mock fallback", result.error);
  }
  renderStatusTasks(result.status, result.source);
  renderFocusStatus(result.status, result.source);
}

function init() {
  const initialData = window.desktopWidget?.getInitialData
    ? window.desktopWidget.getInitialData()
    : FALLBACK_DATA;

  state.tasks = initialData.tasks.map((task) => ({ ...task }));
  renderTasks();
  refreshFocusStatus(initialData.focus);
  window.setInterval(() => {
    refreshFocusStatus(initialData.focus);
  }, 1000);

  elements.completeButton.addEventListener("click", () => {
    completeCurrentTask(initialData.config, initialData.focus);
  });

  elements.closeButton.addEventListener("click", () => {
    window.desktopWidget?.close?.();
  });
}

init();
