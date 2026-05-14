import { StatusBar } from 'expo-status-bar';
import { LinearGradient } from 'expo-linear-gradient';
import { useEffect, useMemo, useRef, useState } from 'react';
import {
  Alert,
  KeyboardAvoidingView,
  Platform,
  Pressable,
  SafeAreaView,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  View,
} from 'react-native';

type Screen = 'speak' | 'microstep' | 'stop' | 'dashboard';
type StepCategory = 'WORK' | 'ROUTINE';
type StepStatus = 'pending' | 'active' | 'completed';

type PlanStep = {
  id: string;
  title: string;
  duration_minutes: number;
  category: StepCategory;
  status: StepStatus;
  order: number;
};

type Plan = {
  plan_id: string;
  goal_title: string;
  total_minutes: number;
  metadata_permission: boolean;
  blocked_apps: string[];
  blocked_sites: string[];
  status: 'draft' | 'active' | 'completed';
  current_step_index: number;
  source: 'mobile';
  created_at: string;
  steps: PlanStep[];
};

type PcStatus = {
  current_task?: string | { title?: string };
  task?: string;
  remaining_time?: number;
  overrun_seconds?: number;
  violation_count?: number;
  distraction_count?: number;
  plan_completed?: boolean;
  plan_progress?: {
    completed?: number;
    total?: number;
    percent?: number;
  };
};

const colors = {
  bgPage: '#FFF8F5',
  bgSurface: 'rgba(255, 252, 250, 0.88)',
  textPrimary: '#3D312E',
  textSecondary: '#8C7A76',
  chipPeach: '#FFD6B8',
  chipApricot: '#FFB86C',
  focusLabel: '#3A6B36',
  coral: '#FF8A7A',
  taskBlue: '#C5E2F6',
  routineGreen: '#DFFAB0',
  borderLine: 'rgba(0, 0, 0, 0.06)',
  borderSoft: 'rgba(255, 255, 255, 0.65)',
};

const LAN_SERVER = 'http://192.168.219.104:5000';

function getDefaultServer() {
  if (Platform.OS === 'web' && typeof window !== 'undefined') {
    const host = window.location.hostname;
    if (host && host !== 'localhost' && host !== '127.0.0.1') {
      return `http://${host}:5000`;
    }
    return 'http://127.0.0.1:5000';
  }
  return LAN_SERVER;
}

function normalizeServerUrl(value: string) {
  const trimmed = value.trim();
  if (!trimmed) return getDefaultServer();
  return /^https?:\/\//i.test(trimmed) ? trimmed.replace(/\/+$/, '') : `http://${trimmed.replace(/\/+$/, '')}`;
}

function formatSeconds(seconds: number) {
  const safe = Math.max(0, Number(seconds) || 0);
  const minutes = Math.floor(safe / 60);
  const rest = safe % 60;
  return `${String(minutes).padStart(2, '0')}:${String(rest).padStart(2, '0')}`;
}

function minutesLabel(minutes: number) {
  return `${Number(minutes) || 0}분`;
}

function makeSteps(goalText: string): PlanStep[] {
  const lowerGoal = goalText.toLowerCase();
  const rawSteps =
    lowerGoal.includes('report') ||
    lowerGoal.includes('essay') ||
    lowerGoal.includes('레포트') ||
    lowerGoal.includes('보고서') ||
    lowerGoal.includes('과제')
      ? [
          ['문서 열고 제목만 적기', 5, 'WORK'],
          ['자료 링크 3개 찾기', 12, 'WORK'],
          ['목차를 세 줄로 쪼개기', 8, 'WORK'],
          ['서론 초안 한 문장 쓰기', 10, 'WORK'],
          ['물 마시고 다음 줄 남기기', 5, 'ROUTINE'],
        ]
      : lowerGoal.includes('study') ||
          lowerGoal.includes('exam') ||
          lowerGoal.includes('공부') ||
          lowerGoal.includes('시험')
        ? [
            ['공부 범위 한 줄에 적기', 5, 'WORK'],
            ['가장 쉬운 개념 3개 체크하기', 10, 'WORK'],
            ['헷갈리는 부분 2개 표시하기', 10, 'WORK'],
            ['지금 문제 예시 3개 풀기', 15, 'WORK'],
            ['스트레칭하고 다음 복습 적기', 5, 'ROUTINE'],
          ]
        : [
            ['작업 화면 열기', 5, 'WORK'],
            ['해야 할 일을 세 덩어리로 나누기', 8, 'WORK'],
            ['가장 쉬운 첫 조각만 끝내기', 12, 'WORK'],
            ['막힌 지점 하나 적기', 5, 'WORK'],
            ['짧게 쉬고 다음 행동 남기기', 5, 'ROUTINE'],
          ];

  return rawSteps.map(([title, duration, category], index) => ({
    id: `step_${index + 1}`,
    title: String(title),
    duration_minutes: Number(duration),
    category: category as StepCategory,
    status: 'pending',
    order: index + 1,
  }));
}

function buildPlan(goal: string): Plan {
  const steps = makeSteps(goal);
  return {
    plan_id: `mobile_${Date.now()}`,
    goal_title: goal,
    total_minutes: steps.reduce((sum, step) => sum + step.duration_minutes, 0),
    metadata_permission: true,
    blocked_apps: [],
    blocked_sites: [],
    status: 'draft',
    current_step_index: 0,
    source: 'mobile',
    created_at: new Date().toISOString(),
    steps,
  };
}

function normalizePlan(plan: Partial<Plan>): Plan {
  const fallback = buildPlan(plan.goal_title || '오늘 할 일');
  const steps = Array.isArray(plan.steps) ? plan.steps : fallback.steps;
  return {
    ...fallback,
    ...plan,
    plan_id: plan.plan_id || fallback.plan_id,
    goal_title: plan.goal_title || fallback.goal_title,
    total_minutes: Number(plan.total_minutes) || steps.reduce((sum, step) => sum + Number(step.duration_minutes || 0), 0),
    metadata_permission: Boolean(plan.metadata_permission ?? true),
    blocked_apps: Array.isArray(plan.blocked_apps) ? plan.blocked_apps : [],
    blocked_sites: Array.isArray(plan.blocked_sites) ? plan.blocked_sites : [],
    status: plan.status || 'draft',
    current_step_index: Number(plan.current_step_index) || 0,
    source: 'mobile',
    steps: steps.map((step, index) => ({
      id: step.id || `step_${index + 1}`,
      title: step.title || '작은 작업',
      duration_minutes: Number(step.duration_minutes) || 5,
      category: step.category === 'ROUTINE' ? 'ROUTINE' : 'WORK',
      status: (step.status as StepStatus) || 'pending',
      order: Number(step.order) || index + 1,
    })),
  };
}

export default function App() {
  const [screen, setScreen] = useState<Screen>('speak');
  const [goal, setGoal] = useState('');
  const [serverInput, setServerInput] = useState(getDefaultServer);
  const [serverUrl, setServerUrl] = useState(getDefaultServer);
  const [plan, setPlan] = useState<Plan | null>(null);
  const [status, setStatus] = useState<PcStatus | null>(null);
  const [toast, setToast] = useState('');
  const [timerSeconds, setTimerSeconds] = useState(0);
  const [isBusy, setIsBusy] = useState(false);
  const tickRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const statusRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const firstRunnableStep = useMemo(
    () => plan?.steps.find((step) => step.status !== 'completed') || plan?.steps[0],
    [plan],
  );

  useEffect(() => {
    if (!toast) return;
    const handle = setTimeout(() => setToast(''), 2200);
    return () => clearTimeout(handle);
  }, [toast]);

  useEffect(() => {
    return () => {
      if (tickRef.current) clearInterval(tickRef.current);
      if (statusRef.current) clearInterval(statusRef.current);
    };
  }, []);

  const applyServer = () => {
    const normalized = normalizeServerUrl(serverInput);
    setServerInput(normalized);
    setServerUrl(normalized);
    setToast('PC 서버 주소를 저장했어요');
  };

  const createPlan = () => {
    const nextGoal = goal.trim();
    if (!nextGoal) {
      setToast('목표를 한 줄만 적어주세요');
      return;
    }
    setPlan(buildPlan(nextGoal));
    setScreen('microstep');
  };

  const updateCategory = (stepId: string, category: StepCategory) => {
    setPlan((current) =>
      current
        ? {
            ...current,
            steps: current.steps.map((step) => (step.id === stepId ? { ...step, category } : step)),
          }
        : current,
    );
  };

  const sendPlanToPc = async () => {
    if (!plan) {
      setToast('먼저 목표를 작은 작업으로 나눠주세요');
      return;
    }

    const payload = normalizePlan({
      ...plan,
      status: 'active',
      current_step_index: 0,
      steps: plan.steps.map((step, index) => ({
        ...step,
        status: index === 0 ? 'active' : 'pending',
      })),
    });

    setIsBusy(true);
    try {
      const response = await fetch(`${serverUrl}/api/mobile/plan`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      if (!response.ok) throw new Error('plan failed');
      const data = await response.json();
      let savedPlan = normalizePlan(data.plan || data || payload);
      try {
        const startResponse = await fetch(`${serverUrl}/api/plan/start`, { method: 'POST' });
        if (startResponse.ok) {
          const startData = await startResponse.json();
          savedPlan = normalizePlan({
            ...savedPlan,
            current_step_index: Number(startData.current_step_index) || 0,
            steps: savedPlan.steps.map((step) =>
              step.id === startData.started_step?.id
                ? { ...step, status: 'active' }
                : step.status === 'active'
                  ? { ...step, status: 'pending' }
                  : step,
            ),
          });
        }
      } catch {
        setToast('계획은 보냈지만 PC 시작 확인은 못했어요');
      }
      setPlan(savedPlan);
      startStopTimer();
      setScreen('stop');
      void fetchPcStatus();
      if (statusRef.current) clearInterval(statusRef.current);
      statusRef.current = setInterval(fetchPcStatus, 3000);
    } catch {
      setToast('PC 서버에 연결하지 못했어요. 주소를 확인해주세요');
    } finally {
      setIsBusy(false);
    }
  };

  const startStopTimer = () => {
    setTimerSeconds(0);
    if (tickRef.current) clearInterval(tickRef.current);
    tickRef.current = setInterval(() => setTimerSeconds((value) => value + 1), 1000);
  };

  const fetchPcStatus = async () => {
    try {
      const response = await fetch(`${serverUrl}/status`);
      if (!response.ok) throw new Error('status failed');
      const nextStatus = (await response.json()) as PcStatus;
      setStatus(nextStatus);
      if (nextStatus.plan_completed) showDashboard();
    } catch {
      setStatus(null);
    }
  };

  const completeCurrentTask = async () => {
    try {
      const response = await fetch(`${serverUrl}/api/tasks/complete_current`, { method: 'POST' });
      if (response.ok) {
        const result = await response.json();
        if (result?.next_task) {
          setPlan((current) =>
            current
              ? {
                  ...current,
                  steps: current.steps.map((step) =>
                    step.id === result.next_task.id
                      ? { ...step, status: 'active' }
                      : step.status === 'active'
                        ? { ...step, status: 'completed' }
                        : step,
                  ),
                }
              : current,
          );
          startStopTimer();
          void fetchPcStatus();
          return;
        }
      }
    } catch {
      setPlan((current) =>
        current ? { ...current, steps: current.steps.map((step) => ({ ...step, status: 'completed' })) } : current,
      );
    }
    showDashboard();
  };

  const showDashboard = () => {
    if (tickRef.current) clearInterval(tickRef.current);
    if (statusRef.current) clearInterval(statusRef.current);
    setScreen('dashboard');
  };

  const activeTitle = (() => {
    const active = status?.current_task || status?.task;
    if (typeof active === 'string') return active;
    return active?.title || firstRunnableStep?.title || '작업을 시작하는 중입니다';
  })();

  return (
    <SafeAreaView style={styles.page}>
      <StatusBar style="dark" />
      <KeyboardAvoidingView style={styles.frame} behavior={Platform.OS === 'ios' ? 'padding' : undefined}>
        {screen === 'speak' && (
          <View style={styles.speakScreen}>
            <View style={styles.settingsRow}>
              <TextInput
                value={serverInput}
                onChangeText={setServerInput}
                autoCapitalize="none"
                autoCorrect={false}
                keyboardType="url"
                placeholder="PC 서버 IP:5000"
                placeholderTextColor={colors.textSecondary}
                style={styles.serverInput}
              />
              <Pressable style={styles.serverButton} onPress={applyServer}>
                <Text style={styles.serverButtonText}>IP</Text>
              </Pressable>
            </View>

            <Text style={styles.speakTitle}>
              오늘 머릿속에 있는 일을{'\n'}작게 쪼개볼까요?
            </Text>

            <View style={styles.micSection}>
              <Pressable style={({ pressed }) => [styles.giantMic, pressed && styles.pressedSmall]} onPress={createPlan}>
                <LinearGradient colors={['#C8F0C5', '#DFFAB0', '#FFF2CC']} style={styles.giantMicGradient}>
                  <Text style={styles.micIcon}>🎙</Text>
                  <Text style={styles.micText}>말로 시작하기</Text>
                </LinearGradient>
              </Pressable>
            </View>

            <View style={styles.inputBar}>
              <TextInput
                value={goal}
                onChangeText={setGoal}
                onSubmitEditing={createPlan}
                placeholder="직접 입력해도 괜찮아요..."
                placeholderTextColor={colors.textSecondary}
                style={styles.goalInput}
                returnKeyType="send"
              />
              <Pressable style={styles.sendBtn} onPress={createPlan}>
                <Text style={styles.sendText}>›</Text>
              </Pressable>
            </View>
            <Text style={styles.statusMsg}>AI가 당신의 말을 듣기 위해 대기 중입니다</Text>
          </View>
        )}

        {screen === 'microstep' && plan && (
          <View style={styles.microScreen}>
            <Text style={styles.msTitle}>오늘의 마이크로 스텝</Text>
            <Text style={styles.msSubtitle}>총 {plan.steps.length}개의 마이크로 스텝으로 쪼갰어요</Text>

            <ScrollView style={styles.timelineScroll} showsVerticalScrollIndicator={false}>
              <View style={styles.timelineWrap}>
                <View style={styles.timelineLine} />
                {plan.steps.map((step) => (
                  <View key={step.id} style={styles.taskNode}>
                    <View style={styles.taskDot} />
                    <View style={styles.taskCard}>
                      <View style={styles.taskHeader}>
                        <Text style={styles.taskTitle}>{step.title}</Text>
                        <Text style={styles.taskTime}>{minutesLabel(step.duration_minutes)}</Text>
                      </View>
                      <View style={styles.catToggle}>
                        {(['WORK', 'ROUTINE'] as StepCategory[]).map((category) => (
                          <Pressable
                            key={category}
                            style={[styles.catBtn, step.category === category && styles.catBtnActive]}
                            onPress={() => updateCategory(step.id, category)}
                          >
                            <Text style={[styles.catBtnText, step.category === category && styles.catBtnTextActive]}>
                              {category === 'WORK' ? 'Work' : 'Routine'}
                            </Text>
                          </Pressable>
                        ))}
                      </View>
                    </View>
                  </View>
                ))}
              </View>
            </ScrollView>

            <Pressable style={({ pressed }) => [styles.sendPcBtn, pressed && styles.pressedSmall]} onPress={sendPlanToPc} disabled={isBusy}>
              <LinearGradient colors={['#FFB86C', '#FF8A7A']} style={styles.sendPcGradient}>
                <Text style={styles.sendPcText}>{isBusy ? 'PC로 보내는 중...' : 'PC로 보내고 시작하기'}</Text>
              </LinearGradient>
            </Pressable>
          </View>
        )}

        {screen === 'stop' && (
          <LinearGradient colors={['#FF8A7A', '#FFD6B8']} style={styles.stopScreen}>
            <Text style={styles.stopLabel}>PC 작업 중</Text>
            <Text style={styles.stopTaskName}>{activeTitle}</Text>

            <View style={styles.stopPill}>
              <View style={styles.stopDot} />
              <View style={styles.stopPillInfo}>
                <Text style={styles.stopPillLabel}>Ready to come back?</Text>
                <Text style={styles.stopPillTask} numberOfLines={1}>
                  {activeTitle}
                </Text>
              </View>
              <View style={styles.stopDivider} />
              <Text style={styles.stopTimer}>
                {Number(status?.overrun_seconds) > 0 ? `+${formatSeconds(Number(status?.overrun_seconds))}` : formatSeconds(timerSeconds)}
              </Text>
            </View>

            <Text style={styles.stopHint}>
              PC에서 작업을 진행하고 있어요.{'\n'}완료하면 아래 버튼을 눌러주세요.
            </Text>

            <Pressable style={({ pressed }) => [styles.doneBtn, pressed && styles.pressedSmall]} onPress={completeCurrentTask}>
              <Text style={styles.doneText}>오늘 작업 완료</Text>
            </Pressable>
          </LinearGradient>
        )}

        {screen === 'dashboard' && <Dashboard plan={plan} status={status} timerSeconds={timerSeconds} />}

        {!!toast && (
          <View style={styles.toast}>
            <Text style={styles.toastText}>{toast}</Text>
          </View>
        )}
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}

function Dashboard({ plan, status, timerSeconds }: { plan: Plan | null; status: PcStatus | null; timerSeconds: number }) {
  const total = Number(status?.plan_progress?.total) || plan?.steps.length || 0;
  const completed =
    Number(status?.plan_progress?.completed) ||
    plan?.steps.filter((step) => step.status === 'completed').length ||
    total;
  const percent = total ? Math.round((completed / total) * 100) : 0;
  const overrunMinutes = Math.max(0, Math.ceil((Number(status?.overrun_seconds) || 0) / 60));
  const distractions = Number(status?.violation_count || status?.distraction_count || 0);
  const work = plan?.steps.filter((step) => step.category === 'WORK') || [];
  const routine = plan?.steps.filter((step) => step.category === 'ROUTINE') || [];

  return (
    <ScrollView style={styles.dashboardScreen} showsVerticalScrollIndicator={false}>
      <View style={styles.chartWrap}>
        <View style={styles.circleBg}>
          <View style={[styles.circleFill, { opacity: Math.max(0.12, percent / 100) }]} />
          <View style={styles.chartInfo}>
            <Text style={styles.pct}>{percent}%</Text>
            <Text style={styles.pctLabel}>COMPLETE</Text>
          </View>
        </View>
      </View>

      <View style={styles.summaryBar}>
        <Summary label="집중" value={`${Math.max(0, Math.round(timerSeconds / 60))}m`} />
        <Summary label="초과" value={`+${overrunMinutes}m`} coral />
        <Summary label="분산" value={`${distractions}회`} />
      </View>

      <View style={styles.diaryGrid}>
        <View style={styles.checklistSection}>
          <ReviewSection title="Deep Work" tasks={work} category="WORK" />
          <ReviewSection title="Routine" tasks={routine} category="ROUTINE" />
        </View>
        <View style={styles.timeMarks}>
          {Array.from({ length: 9 }).map((_, index) => {
            const step = plan?.steps[index];
            return (
              <View key={index} style={styles.timeSlot}>
                <Text style={styles.hour}>{index + 9 > 12 ? index - 3 : index + 9}</Text>
                <View
                  style={[
                    styles.bar,
                    !step && styles.barNone,
                    step?.category === 'WORK' && styles.barWork,
                    step?.category === 'ROUTINE' && styles.barRoutine,
                  ]}
                />
              </View>
            );
          })}
        </View>
      </View>

      <View style={styles.insightFooter}>
        <Text style={styles.insightBold}>패턴 피드백</Text>
        <Text style={styles.insightText}>{buildInsight(percent, overrunMinutes, distractions)}</Text>
      </View>
    </ScrollView>
  );
}

function Summary({ label, value, coral = false }: { label: string; value: string; coral?: boolean }) {
  return (
    <View style={styles.sumItem}>
      <Text style={styles.sLabel}>{label}</Text>
      <Text style={[styles.sVal, coral && { color: colors.coral }]}>{value}</Text>
    </View>
  );
}

function ReviewSection({ title, tasks, category }: { title: string; tasks: PlanStep[]; category: StepCategory }) {
  const visible = tasks.length
    ? tasks
    : [{ id: category, title: category === 'WORK' ? '집중 작업 없음' : '루틴 작업 없음', status: 'pending' as StepStatus }];
  return (
    <View>
      <Text style={styles.secTitle}>{title}</Text>
      {visible.slice(0, 4).map((task) => (
        <View key={task.id} style={styles.checkItem}>
          <View style={styles.chkBox}>
            <Text style={styles.chkMark}>{task.status === 'pending' ? '' : 'V'}</Text>
          </View>
          <Text style={[styles.chkText, category === 'WORK' ? styles.hlBlue : styles.hlGreen]}>{task.title}</Text>
        </View>
      ))}
    </View>
  );
}

function buildInsight(percent: number, overrunMinutes: number, distractions: number) {
  if (percent >= 100) return '모든 스텝을 끝냈어요. 오늘은 마무리 기준이 분명해서 다음 작업으로 넘어가기 쉬웠습니다.';
  if (overrunMinutes > 0) return '예상보다 시간이 조금 길어졌어요. 다음에는 첫 스텝을 5분 단위로 더 작게 잡아보면 좋겠습니다.';
  if (distractions > 0) return '중간에 흐름이 흔들린 시간이 있었지만 다시 돌아오는 순서가 남아 있었어요.';
  return '작게 쪼갠 덕분에 시작 장벽이 낮아졌어요. 다음 계획도 첫 스텝은 아주 쉽게 잡아주세요.';
}

const styles = StyleSheet.create({
  page: {
    flex: 1,
    backgroundColor: colors.bgPage,
  },
  frame: {
    flex: 1,
    backgroundColor: colors.bgPage,
    position: 'relative',
  },
  pressedSmall: {
    transform: [{ scale: 0.97 }],
  },
  speakScreen: {
    flex: 1,
    paddingTop: 28,
    paddingHorizontal: 24,
    paddingBottom: 24,
  },
  settingsRow: {
    flexDirection: 'row',
    gap: 8,
    marginBottom: 18,
  },
  serverInput: {
    flex: 1,
    height: 42,
    backgroundColor: colors.bgSurface,
    borderWidth: 1,
    borderColor: colors.borderSoft,
    borderRadius: 100,
    paddingHorizontal: 16,
    color: colors.textPrimary,
    fontSize: 13,
  },
  serverButton: {
    width: 42,
    height: 42,
    borderRadius: 21,
    backgroundColor: colors.chipApricot,
    alignItems: 'center',
    justifyContent: 'center',
  },
  serverButtonText: {
    color: '#fff',
    fontWeight: '800',
    fontSize: 12,
  },
  speakTitle: {
    fontSize: 24,
    fontWeight: '600',
    lineHeight: 32,
    color: colors.textPrimary,
  },
  micSection: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
  },
  giantMic: {
    width: 220,
    height: 220,
    borderRadius: 110,
    shadowColor: '#A8E6A3',
    shadowOpacity: 0.5,
    shadowRadius: 48,
    shadowOffset: { width: 0, height: 12 },
    elevation: 10,
    overflow: 'hidden',
  },
  giantMicGradient: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
  },
  micIcon: {
    fontSize: 56,
    lineHeight: 64,
    marginBottom: 8,
  },
  micText: {
    fontSize: 14,
    fontWeight: '700',
    color: colors.focusLabel,
  },
  inputBar: {
    minHeight: 66,
    backgroundColor: colors.bgSurface,
    borderWidth: 1,
    borderColor: colors.borderSoft,
    borderRadius: 100,
    paddingLeft: 24,
    paddingRight: 16,
    flexDirection: 'row',
    alignItems: 'center',
    shadowColor: '#3D312E',
    shadowOpacity: 0.05,
    shadowRadius: 12,
    shadowOffset: { width: 0, height: 4 },
    elevation: 2,
  },
  goalInput: {
    flex: 1,
    minWidth: 0,
    fontSize: 15,
    color: colors.textPrimary,
  },
  sendBtn: {
    width: 34,
    height: 34,
    borderRadius: 17,
    backgroundColor: colors.chipApricot,
    alignItems: 'center',
    justifyContent: 'center',
    marginLeft: 8,
  },
  sendText: {
    color: '#fff',
    fontSize: 28,
    fontWeight: '800',
    lineHeight: 30,
  },
  statusMsg: {
    textAlign: 'center',
    fontSize: 11,
    fontWeight: '700',
    color: colors.textSecondary,
    letterSpacing: 1.1,
    marginTop: 16,
  },
  microScreen: {
    flex: 1,
    paddingTop: 28,
    paddingHorizontal: 24,
    paddingBottom: 24,
  },
  msTitle: {
    fontSize: 22,
    fontWeight: '600',
    color: colors.textPrimary,
  },
  msSubtitle: {
    fontSize: 12,
    color: colors.textSecondary,
    marginTop: 4,
  },
  timelineScroll: {
    flex: 1,
    marginTop: 4,
  },
  timelineWrap: {
    position: 'relative',
    paddingLeft: 32,
    paddingTop: 16,
    paddingBottom: 8,
  },
  timelineLine: {
    position: 'absolute',
    left: 7,
    top: 0,
    bottom: 0,
    width: 2,
    backgroundColor: colors.chipApricot,
    opacity: 0.65,
  },
  taskNode: {
    position: 'relative',
    marginBottom: 20,
  },
  taskDot: {
    position: 'absolute',
    left: -30,
    top: 20,
    width: 12,
    height: 12,
    borderRadius: 6,
    backgroundColor: colors.chipApricot,
    borderWidth: 3,
    borderColor: '#fff',
    zIndex: 2,
  },
  taskCard: {
    backgroundColor: colors.bgSurface,
    borderWidth: 1,
    borderColor: colors.borderSoft,
    borderRadius: 20,
    paddingVertical: 18,
    paddingHorizontal: 20,
    shadowColor: '#3D312E',
    shadowOpacity: 0.05,
    shadowRadius: 12,
    shadowOffset: { width: 0, height: 4 },
    elevation: 2,
  },
  taskHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'flex-start',
    marginBottom: 10,
    gap: 8,
  },
  taskTitle: {
    flex: 1,
    fontSize: 15,
    fontWeight: '600',
    color: colors.textPrimary,
    lineHeight: 21,
  },
  taskTime: {
    fontSize: 12,
    fontWeight: '500',
    color: colors.focusLabel,
    backgroundColor: colors.routineGreen,
    paddingVertical: 3,
    paddingHorizontal: 10,
    borderRadius: 100,
    overflow: 'hidden',
  },
  catToggle: {
    flexDirection: 'row',
    gap: 8,
  },
  catBtn: {
    paddingVertical: 5,
    paddingHorizontal: 12,
    borderRadius: 100,
    backgroundColor: 'rgba(0,0,0,0.04)',
  },
  catBtnActive: {
    backgroundColor: colors.chipPeach,
  },
  catBtnText: {
    fontSize: 11,
    fontWeight: '700',
    color: colors.textSecondary,
  },
  catBtnTextActive: {
    color: '#8A4800',
  },
  sendPcBtn: {
    width: '100%',
    borderRadius: 20,
    overflow: 'hidden',
    marginTop: 12,
    shadowColor: colors.coral,
    shadowOpacity: 0.35,
    shadowRadius: 24,
    shadowOffset: { width: 0, height: 8 },
    elevation: 5,
  },
  sendPcGradient: {
    padding: 16,
    alignItems: 'center',
  },
  sendPcText: {
    color: '#fff',
    fontSize: 16,
    fontWeight: '700',
  },
  stopScreen: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
    paddingTop: 28,
    paddingHorizontal: 28,
    paddingBottom: 48,
    gap: 28,
  },
  stopLabel: {
    fontSize: 12,
    fontWeight: '700',
    color: 'rgba(255,255,255,0.9)',
    letterSpacing: 1.7,
    textTransform: 'uppercase',
  },
  stopTaskName: {
    fontSize: 20,
    fontWeight: '600',
    color: colors.textPrimary,
    textAlign: 'center',
    lineHeight: 29,
  },
  stopPill: {
    maxWidth: '100%',
    flexDirection: 'row',
    alignItems: 'center',
    gap: 14,
    paddingVertical: 14,
    paddingHorizontal: 22,
    backgroundColor: 'rgba(255,255,255,0.72)',
    borderRadius: 100,
    shadowColor: colors.coral,
    shadowOpacity: 0.4,
    shadowRadius: 48,
    shadowOffset: { width: 0, height: 12 },
    elevation: 6,
  },
  stopDot: {
    width: 10,
    height: 10,
    borderRadius: 5,
    backgroundColor: colors.coral,
    shadowColor: colors.coral,
    shadowOpacity: 0.8,
    shadowRadius: 10,
  },
  stopPillInfo: {
    minWidth: 0,
  },
  stopPillLabel: {
    fontSize: 10,
    fontWeight: '700',
    color: colors.coral,
    textTransform: 'uppercase',
    letterSpacing: 1,
    lineHeight: 13,
  },
  stopPillTask: {
    maxWidth: 150,
    fontSize: 14,
    fontWeight: '600',
    color: colors.textPrimary,
  },
  stopDivider: {
    width: 1,
    height: 16,
    backgroundColor: 'rgba(255,138,122,0.25)',
  },
  stopTimer: {
    fontSize: 14,
    color: 'rgba(61,49,46,0.6)',
    fontWeight: '500',
  },
  stopHint: {
    fontSize: 13,
    color: 'rgba(61,49,46,0.6)',
    textAlign: 'center',
    lineHeight: 22,
  },
  doneBtn: {
    width: '100%',
    padding: 16,
    borderRadius: 20,
    backgroundColor: 'rgba(255,255,255,0.88)',
    alignItems: 'center',
    shadowColor: colors.coral,
    shadowOpacity: 0.2,
    shadowRadius: 16,
    shadowOffset: { width: 0, height: 4 },
    elevation: 3,
  },
  doneText: {
    color: colors.coral,
    fontSize: 16,
    fontWeight: '700',
  },
  dashboardScreen: {
    flex: 1,
    paddingTop: 28,
    paddingHorizontal: 24,
    paddingBottom: 40,
  },
  chartWrap: {
    position: 'relative',
    width: 180,
    height: 180,
    marginHorizontal: 'auto',
    marginBottom: 24,
    alignItems: 'center',
    justifyContent: 'center',
  },
  circleBg: {
    width: 180,
    height: 180,
    borderRadius: 90,
    borderWidth: 10,
    borderColor: '#eee',
    alignItems: 'center',
    justifyContent: 'center',
  },
  circleFill: {
    position: 'absolute',
    inset: -10,
    borderRadius: 90,
    borderWidth: 10,
    borderColor: colors.coral,
  },
  chartInfo: {
    alignItems: 'center',
  },
  pct: {
    fontSize: 36,
    fontWeight: '700',
    color: colors.textPrimary,
  },
  pctLabel: {
    fontSize: 11,
    fontWeight: '600',
    color: colors.textSecondary,
    marginTop: 2,
  },
  summaryBar: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    marginBottom: 28,
    backgroundColor: '#fff',
    padding: 15,
    borderRadius: 20,
    borderWidth: 1,
    borderColor: colors.borderLine,
  },
  sumItem: {
    flex: 1,
    alignItems: 'center',
  },
  sLabel: {
    fontSize: 10,
    fontWeight: '700',
    color: colors.textSecondary,
    marginBottom: 4,
  },
  sVal: {
    fontSize: 15,
    fontWeight: '700',
    color: colors.textPrimary,
  },
  diaryGrid: {
    flexDirection: 'row',
    gap: 15,
  },
  checklistSection: {
    flex: 1,
    gap: 20,
  },
  secTitle: {
    fontSize: 11,
    fontWeight: '800',
    color: colors.textSecondary,
    letterSpacing: 0.55,
    textTransform: 'uppercase',
  },
  checkItem: {
    flexDirection: 'row',
    alignItems: 'flex-start',
    gap: 10,
    marginTop: 10,
  },
  chkBox: {
    width: 18,
    height: 18,
    borderWidth: 1.5,
    borderColor: colors.textPrimary,
    borderRadius: 3,
    alignItems: 'center',
    justifyContent: 'center',
  },
  chkMark: {
    fontSize: 12,
    fontWeight: '900',
    color: colors.textPrimary,
  },
  chkText: {
    flex: 1,
    fontSize: 14,
    fontWeight: '600',
    color: colors.textPrimary,
    lineHeight: 20,
  },
  hlBlue: {
    backgroundColor: colors.taskBlue,
  },
  hlGreen: {
    backgroundColor: colors.routineGreen,
  },
  timeMarks: {
    width: 65,
    borderLeftWidth: 1,
    borderLeftColor: colors.borderLine,
    paddingLeft: 10,
  },
  timeSlot: {
    flexDirection: 'row',
    alignItems: 'center',
    height: 26,
    gap: 6,
  },
  hour: {
    fontSize: 9,
    color: colors.textSecondary,
    width: 15,
    textAlign: 'right',
  },
  bar: {
    flex: 1,
    height: 22,
    borderRadius: 3,
  },
  barWork: {
    backgroundColor: colors.taskBlue,
    borderLeftWidth: 3,
    borderLeftColor: '#7BB6E0',
  },
  barRoutine: {
    backgroundColor: colors.routineGreen,
    borderLeftWidth: 3,
    borderLeftColor: '#B7D980',
  },
  barNone: {
    backgroundColor: 'rgba(0,0,0,0.02)',
  },
  insightFooter: {
    marginTop: 24,
    marginBottom: 40,
    backgroundColor: '#fdf6e3',
    padding: 18,
    borderRadius: 20,
    borderWidth: 1,
    borderColor: '#efe3c1',
  },
  insightBold: {
    fontSize: 13,
    fontWeight: '700',
    color: '#5d5645',
    marginBottom: 4,
  },
  insightText: {
    fontSize: 13,
    color: '#5d5645',
    lineHeight: 20,
  },
  toast: {
    position: 'absolute',
    left: 24,
    right: 24,
    bottom: 24,
    borderRadius: 20,
    paddingVertical: 14,
    paddingHorizontal: 16,
    backgroundColor: 'rgba(61,49,46,0.9)',
    alignItems: 'center',
  },
  toastText: {
    color: '#fff',
    fontSize: 13,
    textAlign: 'center',
  },
});
