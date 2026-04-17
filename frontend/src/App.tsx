import { useEffect, useRef, useState, type CSSProperties } from "react";
import {
  getCouncilInfo,
  getSettings,
  getThread,
  listConversations,
  saveSettings,
  streamAsk,
  type AppSettings,
  type AppSettingsMeta,
  type CliSettings,
  type CouncilEvent,
  type CouncilRun,
  type SettingsMeta,
  type Stage,
  type ThreadDetail,
  type ThreadSummary,
} from "./api";
import { ModelCard, type CardStatus } from "./components/ModelCard";

type StageStatus = "pending" | "running" | "done";
type Member = { name: string; display_name: string; label: string };
type ActivityTone = "info" | "live" | "done" | "error";

interface CardState {
  status: CardStatus;
  acc: string;
  finalText?: string;
  error?: string;
  startedAt?: number;
  finishedAt?: number;
  chunks: number;
  rateLimited?: boolean;
}

interface DebateRoundState {
  roundIndex: number;
  focusPoints: string[];
  responses: Record<string, CardState>;
}

interface RefereeSummaryState {
  roundIndex: number;
  decision: string;
  focusPoints: string[];
  text: string;
}

interface RunState {
  id: string;
  threadId: string;
  parentId?: string | null;
  turnIndex: number;
  isFollowup: boolean;
  createdAt?: string;
  question: string;
  chairman: string;
  debateEnabled: boolean;
  members: Member[];
  runtimeModels: Record<string, string>;
  stages: Record<Stage, StageStatus>;
  research: Record<string, CardState>;
  answers: Record<string, CardState>;
  reviews: Record<string, CardState>;
  debateRounds: DebateRoundState[];
  refereeSummaries: RefereeSummaryState[];
  debateStoppedReason?: string | null;
  synth: CardState;
  activityText?: string;
  activityTone?: ActivityTone;
  runStartedAt: number | null;
}

interface ThreadView {
  id: string;
  title: string;
  createdAt?: string;
  updatedAt?: string;
  turnCount: number;
  runs: RunState[];
}

const EMPTY_CARD: CardState = { status: "idle", acc: "", chunks: 0 };
const STAGE_ORDER: Stage[] = ["research", "fanout", "review", "synthesis"];
const DEFAULT_RESEARCH_PARTICIPANTS = ["claude", "codex"];
const STAGE_TITLES: Record<Stage, string> = {
  research: "Web Research",
  fanout: "Independent Answers",
  review: "Peer Reviews",
  synthesis: "Final Answer",
};

export function App() {
  const [question, setQuestion] = useState("");
  const [debateHoldProgress, setDebateHoldProgress] = useState(0);
  const [debateHolding, setDebateHolding] = useState(false);
  const [busy, setBusy] = useState(false);
  const [settings, setSettings] = useState<Record<string, CliSettings>>({});
  const [settingsMeta, setSettingsMeta] = useState<Record<string, SettingsMeta>>({});
  const [appSettings, setAppSettings] = useState<AppSettings>({ research_enabled: true });
  const [appSettingsMeta, setAppSettingsMeta] = useState<Record<string, AppSettingsMeta>>({});
  const [settingsBusy, setSettingsBusy] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [fatal, setFatal] = useState<string | null>(null);
  const [history, setHistory] = useState<ThreadSummary[]>([]);
  const [historyBusy, setHistoryBusy] = useState(false);
  const [selectedThread, setSelectedThread] = useState<ThreadView | null>(null);
  const [autoFollowTop, setAutoFollowTop] = useState(true);
  const topAnchorRef = useRef<HTMLDivElement | null>(null);
  const debateHoldFrameRef = useRef<number | null>(null);
  const debateHoldStartedAtRef = useRef<number | null>(null);
  const debateTriggeredRef = useRef(false);
  const composerMode = selectedThread ? "followup" : "new";
  const latestRun = selectedThread?.runs[0] ?? null;

  useEffect(() => {
    void loadCouncilInfo();
    void loadSettings();
    void refreshHistory();
  }, []);

  useEffect(() => {
    const onScroll = () => {
      setAutoFollowTop(window.scrollY < 220);
    };
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, []);

  useEffect(() => {
    if (!busy || !autoFollowTop) return;
    topAnchorRef.current?.scrollIntoView({ block: "start", behavior: "smooth" });
  }, [busy, autoFollowTop, latestRun?.id, latestRun?.activityText, latestRun?.stages.research, latestRun?.stages.fanout, latestRun?.stages.review, latestRun?.stages.synthesis]);

  useEffect(() => {
    return () => {
      if (debateHoldFrameRef.current != null) window.cancelAnimationFrame(debateHoldFrameRef.current);
    };
  }, []);

  async function loadCouncilInfo() {
    try {
      await getCouncilInfo();
    } catch (e) {
      setFatal(String(e));
    }
  }

  async function loadSettings() {
    try {
      const payload = await getSettings();
      setSettings(payload.settings);
      setSettingsMeta(payload.options);
      setAppSettings(payload.app_settings);
      setAppSettingsMeta(payload.app_options);
    } catch (e) {
      setFatal(String(e));
    }
  }

  async function refreshHistory() {
    setHistoryBusy(true);
    try {
      setHistory(await listConversations());
    } catch (e) {
      setFatal(String(e));
    } finally {
      setHistoryBusy(false);
    }
  }

  async function loadHistoryItem(id: string) {
    if (busy) return;
    setFatal(null);
    try {
      const thread = await getThread(id);
      setSelectedThread(fromThreadDetail(thread));
      setQuestion("");
      setAutoFollowTop(false);
    } catch (e) {
      setFatal(String(e));
    }
  }

  function startNewThreadMode() {
    if (busy) return;
    setSelectedThread(null);
    setFatal(null);
  }

  async function ask(useDebate = false) {
    const trimmed = question.trim();
    if (!trimmed || busy) return;
    setFatal(null);
    setBusy(true);
    setAutoFollowTop(true);
    const payload = selectedThread
      ? { question: trimmed, thread_id: selectedThread.id, parent_id: selectedThread.runs[0]?.id ?? null, debate_enabled: useDebate }
      : { question: trimmed, debate_enabled: useDebate };

    try {
      for await (const ev of streamAsk(payload)) {
        apply(ev);
      }
      await refreshHistory();
      setQuestion("");
    } catch (e) {
      setFatal(String(e));
    } finally {
      setBusy(false);
    }
  }

  function apply(ev: CouncilEvent) {
    switch (ev.type) {
      case "start": {
        const run = createRunFromStart(ev);
        setSelectedThread((current) => {
          if (current && current.id === ev.thread_id) {
            const runs = [run, ...current.runs.filter((item) => item.id !== run.id)];
            return {
              ...current,
              updatedAt: new Date().toISOString(),
              turnCount: Math.max(current.turnCount + 1, runs.length),
              runs,
            };
          }
          return {
            id: ev.thread_id,
            title: ev.question,
            createdAt: new Date().toISOString(),
            updatedAt: new Date().toISOString(),
            turnCount: 1,
            runs: [run],
          };
        });
        patchLatestRun((runState) => withRunActivity(runState, "info", ev.is_followup ? "Follow-up council started." : "New council started."));
        break;
      }
      case "stage":
        patchLatestRun((run) => withRunActivity({
          ...run,
          stages: { ...run.stages, [ev.stage]: ev.status === "started" ? "running" : "done" },
        }, ev.status === "started" ? "info" : "done", ev.status === "started" ? `${STAGE_TITLES[ev.stage]} started.` : `${STAGE_TITLES[ev.stage]} finished.`));
        break;
      case "model_started":
        patchLatestRun((run) => {
          const patch = beginCard;
          if (ev.stage === "research") {
            return withRunActivity({ ...run, research: { ...run.research, [ev.model]: patch(run.research[ev.model] ?? EMPTY_CARD) } }, "live", "Web research is gathering sources.");
          }
          if (ev.stage === "fanout") {
            return withRunActivity({ ...run, answers: { ...run.answers, [ev.model]: patch(run.answers[ev.model] ?? EMPTY_CARD) } }, "live", `${getMemberDisplay(run, ev.model)} is drafting an answer.`);
          }
          if (ev.stage === "review") {
            if (run.debateEnabled) {
              return withRunActivity(run, "live", "Debate exchange in progress.");
            }
            return withRunActivity({ ...run, reviews: { ...run.reviews, [ev.model]: patch(run.reviews[ev.model] ?? EMPTY_CARD) } }, "live", `${getMemberDisplay(run, ev.model)} is reviewing peers.`);
          }
          return withRunActivity({ ...run, synth: patch(run.synth) }, "live", "Chairman is synthesizing the final answer.");
        });
        break;
      case "model_meta":
        if (ev.runtime_model) {
          patchLatestRun((run) => ({ ...run, runtimeModels: { ...run.runtimeModels, [ev.model]: ev.runtime_model! } }));
        }
        break;
      case "delta":
        patchLatestRun((run) => {
          const patch = appendCardDelta;
          if (ev.stage === "research") return { ...run, research: { ...run.research, [ev.model]: patch(run.research[ev.model] ?? EMPTY_CARD, ev.text) } };
          if (ev.stage === "fanout") return { ...run, answers: { ...run.answers, [ev.model]: patch(run.answers[ev.model] ?? EMPTY_CARD, ev.text) } };
          if (ev.stage === "review") {
            if (run.debateEnabled) return run;
            return { ...run, reviews: { ...run.reviews, [ev.model]: patch(run.reviews[ev.model] ?? EMPTY_CARD, ev.text) } };
          }
          return { ...run, synth: patch(run.synth, ev.text) };
        });
        break;
      case "research":
        patchLatestRun((run) => withRunActivity({
          ...run,
          research: {
            ...run.research,
            [ev.model]: finalize(run.research[ev.model] ?? EMPTY_CARD, ev.text ?? undefined, ev.error, isRateLimited(ev.error)),
          },
        }, ev.error ? "error" : "done", ev.error ? `${ev.display_name} research failed.` : `${ev.display_name} research finished.`));
        break;
      case "answer":
        patchLatestRun((run) => withRunActivity({
          ...run,
          answers: {
            ...run.answers,
            [ev.model]: finalize(run.answers[ev.model] ?? EMPTY_CARD, ev.text, ev.error, isRateLimited(ev.error)),
          },
        }, ev.error ? "error" : "done", ev.error ? `${ev.display_name} failed during independent answers.` : `${ev.display_name} finished answering.`));
        break;
      case "debate_round_started":
        patchLatestRun((run) => withRunActivity({
          ...run,
          debateRounds: [...run.debateRounds, { roundIndex: ev.round, focusPoints: [], responses: {} }],
        }, "live", `Debate round ${ev.round} in progress.`));
        break;
      case "debate_turn":
        patchLatestRun((run) => ({
          ...withRunActivity(run, ev.error ? "error" : "done", ev.error ? `${ev.display_name} failed in debate round ${ev.round}.` : `${ev.display_name} responded in debate round ${ev.round}.`),
          debateRounds: run.debateRounds.map((round) => round.roundIndex === ev.round ? {
            ...round,
            responses: {
              ...round.responses,
              [ev.model]: finalize(round.responses[ev.model] ?? EMPTY_CARD, ev.text, ev.error, isRateLimited(ev.error)),
            },
          } : round),
        }));
        break;
      case "debate_round_done":
        patchLatestRun((run) => withRunActivity(run, "done", `Debate round ${ev.round} completed.`));
        break;
      case "debate_referee":
        patchLatestRun((run) => ({
          ...withRunActivity(run, "info", ev.decision === "CONTINUE" ? `Referee requests another debate round.` : `Referee stopped the debate.`),
          refereeSummaries: [...run.refereeSummaries.filter((item) => item.roundIndex !== ev.round), {
            roundIndex: ev.round,
            decision: ev.decision,
            focusPoints: ev.focus_points ?? [],
            text: ev.text,
          }],
          debateRounds: run.debateRounds.map((round) => round.roundIndex === ev.round ? { ...round, focusPoints: ev.focus_points ?? [] } : round),
          debateStoppedReason: ev.decision === "CONTINUE" ? null : `referee stopped after round ${ev.round}`,
        }));
        break;
      case "review":
        patchLatestRun((run) => withRunActivity({
          ...run,
          reviews: {
            ...run.reviews,
            [ev.reviewer]: finalize(run.reviews[ev.reviewer] ?? EMPTY_CARD, ev.text, ev.error, isRateLimited(ev.error)),
          },
        }, ev.error ? "error" : "done", ev.error ? `${ev.display_name} failed during peer review.` : `${ev.display_name} finished peer review.`));
        break;
      case "chairman_fallback":
        patchLatestRun((run) => withRunActivity({
          ...run,
          chairman: ev.to,
          synth: {
            ...EMPTY_CARD,
            status: "waiting",
          },
        }, "error", `${getMemberDisplay(run, ev.from)} hit a rate limit. Chairman fallback switched to ${getMemberDisplay(run, ev.to)}.`));
        break;
      case "synthesis":
        patchLatestRun((run) => withRunActivity({
          ...run,
          chairman: ev.chairman,
          synth: finalize(run.synth, ev.text, ev.error, isRateLimited(ev.error)),
        }, ev.error ? "error" : "done", ev.error ? "Chairman synthesis failed." : "Final answer completed."));
        break;
      case "done":
        patchLatestRun((run) => withRunActivity(run, "done", "Run saved."));
        setSelectedThread((current) => current ? { ...current, id: ev.thread_id, turnCount: current.runs.length } : current);
        break;
    }
  }

  function patchLatestRun(transform: (run: RunState) => RunState) {
    setSelectedThread((current) => {
      if (!current || current.runs.length === 0) return current;
      const [latest, ...rest] = current.runs;
      return {
        ...current,
        updatedAt: new Date().toISOString(),
        runs: [transform(latest), ...rest],
      };
    });
  }

  async function persistSettings(next: {
    settings?: Record<string, CliSettings>;
    app_settings?: AppSettings;
  }) {
    setSettingsBusy(true);
    if (next.settings) setSettings(next.settings);
    if (next.app_settings) setAppSettings(next.app_settings);
    try {
      const payload = await saveSettings(next);
      setSettings(payload.settings);
      setSettingsMeta(payload.options);
      setAppSettings(payload.app_settings);
      setAppSettingsMeta(payload.app_options);
      await loadCouncilInfo();
    } catch (e) {
      setFatal(String(e));
      await loadSettings();
    } finally {
      setSettingsBusy(false);
    }
  }

  function updateCliSetting(cli: string, patch: Partial<CliSettings>) {
    const next = {
      ...settings,
      [cli]: {
        ...settings[cli],
        ...patch,
      },
    };
    void persistSettings({ settings: next });
  }

  function updateAppSetting(patch: Partial<AppSettings>) {
    void persistSettings({ app_settings: { ...appSettings, ...patch } });
  }

  function cancelDebateHold(resetProgress = true) {
    if (debateHoldFrameRef.current != null) {
      window.cancelAnimationFrame(debateHoldFrameRef.current);
      debateHoldFrameRef.current = null;
    }
    debateHoldStartedAtRef.current = null;
    setDebateHolding(false);
    debateTriggeredRef.current = false;
    if (resetProgress) setDebateHoldProgress(0);
  }

  function startDebateHold() {
    if (busy || debateHolding) return;
    cancelDebateHold();
    const startedAt = performance.now();
    debateHoldStartedAtRef.current = startedAt;
    debateTriggeredRef.current = false;
    setDebateHolding(true);
    setDebateHoldProgress(0);
    const tick = (now: number) => {
      if (debateHoldStartedAtRef.current == null) return;
      const next = Math.min((now - debateHoldStartedAtRef.current) / 1000, 1);
      setDebateHoldProgress(next);
      if (next >= 1) {
        debateTriggeredRef.current = true;
        if (debateHoldFrameRef.current != null) {
          window.cancelAnimationFrame(debateHoldFrameRef.current);
          debateHoldFrameRef.current = null;
        }
        debateHoldStartedAtRef.current = null;
        setDebateHolding(false);
        void ask(true);
        window.setTimeout(() => setDebateHoldProgress(0), 180);
        return;
      }
      debateHoldFrameRef.current = window.requestAnimationFrame(tick);
    };
    debateHoldFrameRef.current = window.requestAnimationFrame(tick);
  }

  return (
    <div className="app shell">
      <aside className="history-rail">
        <div className="history-head">
          <div>
            <div className="history-kicker">Threads</div>
            <h2>Council history</h2>
          </div>
          <button className="history-refresh" onClick={() => void refreshHistory()} disabled={historyBusy}>
            {historyBusy ? "Refreshing…" : "Refresh"}
          </button>
        </div>
        <div className="history-list">
          {history.length === 0 ? (
            <div className="history-empty">No saved threads yet.</div>
          ) : (
            history.map((item) => (
              <button
                key={item.id}
                className={`history-item ${selectedThread?.id === item.id ? "active" : ""}`}
                onClick={() => void loadHistoryItem(item.id)}
                disabled={busy}
              >
                <div className="history-item-date">{formatHistoryDate(item.updated_at ?? item.created_at)}</div>
                <div className="history-item-question">{item.title || item.latest_question || "(untitled thread)"}</div>
                <div className="history-item-meta">{item.turn_count} turn{item.turn_count === 1 ? "" : "s"}</div>
              </button>
            ))
          )}
        </div>
      </aside>

      <main className="main-panel">
        <div ref={topAnchorRef} />
        <header className="main-header">
          <div>
            <h1>Model Council</h1>
            <p>Ask a new question or keep pushing the current thread with follow-up turns.</p>
          </div>
          <button
            className="settings-trigger"
            onClick={() => setSettingsOpen(true)}
            disabled={Object.keys(settingsMeta).length === 0}
            aria-label="Open model settings"
          >
            <span className="settings-trigger-icon" aria-hidden>⚙</span>
            Model settings
          </button>
        </header>

        {settingsOpen && Object.keys(settingsMeta).length > 0 && (
          <SettingsModal
            onClose={() => setSettingsOpen(false)}
            settings={settings}
            settingsMeta={settingsMeta}
            appSettings={appSettings}
            appSettingsMeta={appSettingsMeta}
            settingsBusy={settingsBusy}
            busy={busy}
            onUpdate={updateCliSetting}
            onAppUpdate={updateAppSetting}
          />
        )}

        <section className="composer-panel">
          <div className="composer-head">
            <div>
              <div className="composer-kicker">{composerMode === "followup" ? "Follow-up in this thread" : "New question"}</div>
              <div className="composer-subtitle">
                {selectedThread
                  ? `Continuing a ${selectedThread.turnCount}-turn thread. New follow-ups will be added on top.`
                  : "Start a new thread. Once selected, future asks become follow-ups for that thread."}
              </div>
            </div>
            {selectedThread && (
              <button className="secondary-action" onClick={startNewThreadMode} disabled={busy}>
                Start new thread
              </button>
            )}
          </div>
          <div className="input-row">
            <textarea
              placeholder={selectedThread ? "Ask a follow-up that builds on the latest run…" : "Ask a contested question…"}
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) ask();
              }}
              disabled={busy}
            />
            <button
              type="button"
              className={`debate-button ${debateHolding ? "is-holding" : ""}`}
              onPointerDown={(e) => {
                e.preventDefault();
                startDebateHold();
              }}
              onPointerUp={() => {
                if (!debateTriggeredRef.current) cancelDebateHold();
              }}
              onPointerLeave={() => {
                if (!debateTriggeredRef.current) cancelDebateHold();
              }}
              onPointerCancel={() => cancelDebateHold()}
              onContextMenu={(e) => e.preventDefault()}
              disabled={busy || !question.trim()}
            >
              <span className="debate-button-fill" style={{ "--hold-progress": debateHoldProgress } as CSSProperties} />
              <span className="debate-button-copy">
                <strong>{busy ? "Running…" : "Debate"}</strong>
                {debateHolding && <span>Keep holding…</span>}
              </span>
            </button>
            <button onClick={() => void ask(false)} disabled={busy || !question.trim()}>
              <span>{busy ? "Running…" : selectedThread ? "Follow up" : "Ask"}</span>
              <span className="ask-shortcut">⌘↵</span>
            </button>
          </div>
        </section>

        {fatal && <div className="fatal">{fatal}</div>}

        <section className="thread-timeline">
          {!selectedThread && !busy && <EmptyState />}
          {selectedThread?.runs.map((run) => (
            <RunCard
              key={run.id}
              run={run}
              researchEnabled={appSettings.research_enabled}
            />
          ))}
        </section>

        <footer>Subscriptions used: Claude Code · Gemini CLI · Codex CLI</footer>
      </main>
    </div>
  );
}

function RunCard({
  run,
  researchEnabled,
}: {
  run: RunState;
  researchEnabled: boolean;
}) {
  const latestStats = getRunStats(run, researchEnabled);
  const researchMembers = getResearchParticipants(run, researchEnabled);
  const spotlightStage = getSpotlightStage(run);
  const showFinalAnswer = shouldShowFinalAnswer(run);
  const showAnswers = shouldShowAnswers(run);
  const showResearch = shouldShowResearch(run, researchEnabled);
  const showReviews = !run.debateEnabled && shouldShowReviews(run);
  const showDebate = run.debateEnabled && shouldShowDebate(run);
  return (
    <article className="run-card">
      <header className="run-card-head">
        <div className="run-card-meta">
          <span className="run-card-turn">Turn {run.turnIndex + 1}</span>
          {run.isFollowup && <span className="run-card-followup">follow-up</span>}
          <span className="run-card-date">{formatHistoryDate(run.createdAt)}</span>
        </div>
        <h2 className="run-card-question">{run.question}</h2>
        <div className="run-card-status">
          <span>{latestStats.currentStage ? STAGE_TITLES[latestStats.currentStage] : "Complete"}</span>
          <span>{formatRunCountSummary(run, latestStats, researchEnabled)}</span>
          {run.activityText && <span className={`run-activity tone-${run.activityTone ?? "info"}`}>{run.activityText}</span>}
        </div>
      </header>

      {spotlightStage && (
        <section className="run-spotlight">
          <div className="run-spotlight-head">
            <div className="run-spotlight-title">{getSpotlightTitle(run, spotlightStage)}</div>
            {run.activityText && <div className="run-spotlight-note">{run.activityText}</div>}
          </div>

          {spotlightStage === "research" && (
            <div className="cards">
              {researchMembers.map((member) => {
                const card = run.research[member.name] ?? EMPTY_CARD;
                return (
                  <ModelCard
                    key={`${run.id}-spotlight-research-${member.name}`}
                    name={member.name}
                    displayName={member.display_name}
                    runtimeModel={run.runtimeModels[member.name]}
                    heading={`Web research (${member.display_name})`}
                    status={card.status}
                    text={card.finalText ?? card.acc}
                    error={card.error}
                    startedAt={card.startedAt}
                    finishedAt={card.finishedAt}
                    chunks={card.chunks}
                    rateLimited={card.rateLimited}
                  />
                );
              })}
            </div>
          )}

          {spotlightStage === "fanout" && (
            <div className="cards">
              {run.members.map((member) => {
                const card = run.answers[member.name] ?? EMPTY_CARD;
                return (
                  <ModelCard
                    key={`${run.id}-spotlight-answer-${member.name}`}
                    name={member.name}
                    displayName={member.display_name}
                    runtimeModel={run.runtimeModels[member.name]}
                    label={member.label}
                    heading={member.display_name}
                    status={card.status}
                    text={card.finalText ?? card.acc}
                    error={card.error}
                    startedAt={card.startedAt}
                    finishedAt={card.finishedAt}
                    chunks={card.chunks}
                    rateLimited={card.rateLimited}
                  />
                );
              })}
            </div>
          )}

          {spotlightStage === "review" && (
            run.debateEnabled ? (
              <>
                {run.refereeSummaries.length > 0 && (
                  <div className="cards">
                    <ModelCard
                      name="referee"
                      displayName="Debate Referee"
                      runtimeModel=""
                      heading={`Referee summary (Round ${run.refereeSummaries[run.refereeSummaries.length - 1].roundIndex})`}
                      status="done"
                      text={run.refereeSummaries[run.refereeSummaries.length - 1].text}
                      chunks={0}
                    />
                  </div>
                )}
                {run.debateRounds.length > 0 && (
                  <div className="cards">
                    {run.members.map((member) => {
                      const latestRound = run.debateRounds[run.debateRounds.length - 1];
                      const card = latestRound.responses[member.name] ?? EMPTY_CARD;
                      return (
                        <ModelCard
                          key={`${run.id}-spotlight-debate-${latestRound.roundIndex}-${member.name}`}
                          name={member.name}
                          displayName={member.display_name}
                          runtimeModel={run.runtimeModels[member.name]}
                          heading={`Debate by ${member.display_name}`}
                          status={card.status}
                          text={card.finalText ?? card.acc}
                          error={card.error}
                          startedAt={card.startedAt}
                          finishedAt={card.finishedAt}
                          chunks={card.chunks}
                          rateLimited={card.rateLimited}
                        />
                      );
                    })}
                  </div>
                )}
              </>
            ) : (
              <div className="cards">
                {run.members.map((member) => {
                  const card = run.reviews[member.name] ?? EMPTY_CARD;
                  return (
                    <ModelCard
                      key={`${run.id}-spotlight-review-${member.name}`}
                      name={member.name}
                      displayName={member.display_name}
                      runtimeModel={run.runtimeModels[member.name]}
                      heading={`Review by ${member.display_name}`}
                      status={card.status}
                      text={card.finalText ?? card.acc}
                      error={card.error}
                      startedAt={card.startedAt}
                      finishedAt={card.finishedAt}
                      chunks={card.chunks}
                      rateLimited={card.rateLimited}
                    />
                  );
                })}
              </div>
            )
          )}
        </section>
      )}

      {showFinalAnswer && (
        <section className="run-section run-section-pop">
          <div className="run-section-title">
            Final answer
            <span className="chairman-tag">chairman: {getMemberDisplay(run, run.chairman)}</span>
            {run.debateEnabled && <span className="chairman-tag">debate</span>}
          </div>
          <ModelCard
            name={run.chairman || "chairman"}
            displayName={getMemberDisplay(run, run.chairman)}
            runtimeModel={run.runtimeModels[run.chairman]}
            status={run.synth.status}
            text={run.synth.finalText ?? run.synth.acc}
            error={run.synth.error}
            startedAt={run.synth.startedAt}
            finishedAt={run.synth.finishedAt}
            chunks={run.synth.chunks}
            rateLimited={run.synth.rateLimited}
            heading={getMemberDisplay(run, run.chairman)}
          />
        </section>
      )}

      {showDebate ? (
        <>
          {run.refereeSummaries.slice().sort((a, b) => b.roundIndex - a.roundIndex).map((summary) => (
            <details className="run-fold run-section-pop" open key={`${run.id}-ref-${summary.roundIndex}`}>
              <summary>
                <span>Referee summary</span>
                <span className="run-fold-meta">Round {summary.roundIndex} · {summary.decision}</span>
              </summary>
              <div className="cards">
                <ModelCard
                  name="referee"
                  displayName="Debate Referee"
                  runtimeModel=""
                  heading="Referee summary"
                  status="done"
                  text={summary.text}
                  chunks={0}
                />
              </div>
            </details>
          ))}

          {run.debateRounds.slice().sort((a, b) => b.roundIndex - a.roundIndex).map((round) => (
            <details className="run-fold run-section-pop" open key={`${run.id}-debate-${round.roundIndex}`}>
              <summary>
                <span>Debate round {round.roundIndex}</span>
                <span className="run-fold-meta">{countFinished(round.responses)}/{Math.max(run.members.length, 0)}</span>
              </summary>
              <div className="cards">
                {round.focusPoints.length > 0 && (
                  <div className="question-context">
                    <div className="question-context-kicker">Focus points</div>
                    <div className="question-context-body">{round.focusPoints.map((point) => `- ${point}`).join("\n")}</div>
                  </div>
                )}
                {run.members.map((member) => {
                  const card = round.responses[member.name] ?? EMPTY_CARD;
                  return (
                    <ModelCard
                      key={`${run.id}-debate-${round.roundIndex}-${member.name}`}
                      name={member.name}
                      displayName={member.display_name}
                      runtimeModel={run.runtimeModels[member.name]}
                      heading={`Debate by ${member.display_name}`}
                      status={card.status}
                      text={card.finalText ?? card.acc}
                      error={card.error}
                      startedAt={card.startedAt}
                      finishedAt={card.finishedAt}
                      chunks={card.chunks}
                      rateLimited={card.rateLimited}
                    />
                  );
                })}
              </div>
            </details>
          ))}
        </>
      ) : showReviews ? (
        <details className="run-fold run-section-pop">
          <summary>
            <span>Peer reviews</span>
            <span className="run-fold-meta">{latestStats.reviewCount}/{Math.max(run.members.length, 0)}</span>
          </summary>
          <div className="cards">
            {run.members.map((member) => {
              const card = run.reviews[member.name] ?? EMPTY_CARD;
              return (
                <ModelCard
                  key={`${run.id}-review-${member.name}`}
                  name={member.name}
                  displayName={member.display_name}
                  runtimeModel={run.runtimeModels[member.name]}
                  heading={`Review by ${member.display_name}`}
                  status={card.status}
                  text={card.finalText ?? card.acc}
                  error={card.error}
                  startedAt={card.startedAt}
                  finishedAt={card.finishedAt}
                  chunks={card.chunks}
                  rateLimited={card.rateLimited}
                />
              );
            })}
          </div>
        </details>
      ) : null}

      {showAnswers && (
        <details className="run-fold run-section-pop">
          <summary>
            <span>Independent answers</span>
            <span className="run-fold-meta">{latestStats.answerCount}/{Math.max(run.members.length, 0)}</span>
          </summary>
          <div className="cards">
            {run.members.map((member) => {
              const card = run.answers[member.name] ?? EMPTY_CARD;
              return (
                <ModelCard
                  key={`${run.id}-answer-${member.name}`}
                  name={member.name}
                  displayName={member.display_name}
                  runtimeModel={run.runtimeModels[member.name]}
                  label={member.label}
                  heading={member.display_name}
                  status={card.status}
                  text={card.finalText ?? card.acc}
                  error={card.error}
                  startedAt={card.startedAt}
                  finishedAt={card.finishedAt}
                  chunks={card.chunks}
                  rateLimited={card.rateLimited}
                />
              );
            })}
          </div>
        </details>
      )}

      {showResearch && (
        <details className="run-fold run-section-pop">
          <summary>
            <span>Web research</span>
            <span className="run-fold-meta">{latestStats.researchDone}/{Math.max(researchMembers.length, 0)}</span>
          </summary>
          <div className="cards research-cards">
            {researchMembers.map((member) => {
              const card = run.research[member.name] ?? EMPTY_CARD;
              return (
                <ModelCard
                  key={`${run.id}-research-${member.name}`}
                  name={member.name}
                  displayName={member.display_name}
                  runtimeModel={run.runtimeModels[member.name]}
                  heading={`Web research (${member.display_name})`}
                  status={card.status}
                  text={card.finalText ?? card.acc}
                  error={card.error}
                  startedAt={card.startedAt}
                  finishedAt={card.finishedAt}
                  chunks={card.chunks}
                  rateLimited={card.rateLimited}
                />
              );
            })}
          </div>
        </details>
      )}

      <details className="run-fold">
        <summary>
          <span>Question context</span>
          <span className="run-fold-meta">{run.isFollowup ? "Follow-up" : "Root question"}</span>
        </summary>
        <div className="question-context">
          <div className="question-context-kicker">{run.isFollowup ? "Follow-up question" : "Root question"}</div>
          <div className="question-context-body">{run.question}</div>
        </div>
      </details>
    </article>
  );
}

function createRunFromStart(ev: Extract<CouncilEvent, { type: "start" }>): RunState {
  const seed = Object.fromEntries(ev.members.map((member) => [member.name, { ...EMPTY_CARD, status: "waiting" as const }]));
  return {
    id: ev.id,
    threadId: ev.thread_id,
    parentId: ev.parent_id,
    turnIndex: ev.turn_index,
    isFollowup: ev.is_followup,
    createdAt: new Date().toISOString(),
    question: ev.question,
    chairman: ev.chairman,
    debateEnabled: Boolean(ev.debate_enabled),
    members: ev.members,
    runtimeModels: {},
    stages: { research: "pending", fanout: "pending", review: "pending", synthesis: "pending" },
    research: {},
    answers: seed,
    reviews: seed,
    debateRounds: [],
    refereeSummaries: [],
    debateStoppedReason: null,
    synth: { ...EMPTY_CARD, status: "waiting" },
    activityText: ev.is_followup ? "Follow-up council started." : "New council started.",
    activityTone: "info",
    runStartedAt: Date.now(),
  };
}

function fromThreadDetail(thread: ThreadDetail): ThreadView {
  return {
    id: thread.id,
    title: thread.title,
    createdAt: thread.created_at,
    updatedAt: thread.updated_at,
    turnCount: thread.turn_count,
    runs: thread.runs.map(fromSavedRun),
  };
}

function fromSavedRun(run: CouncilRun): RunState {
  return {
    id: run.id,
    threadId: run.thread_id,
    parentId: run.parent_id,
    turnIndex: run.turn_index,
    isFollowup: Boolean(run.is_followup || run.parent_id),
    createdAt: run.created_at,
    question: run.question,
    chairman: run.synthesis?.chairman ?? run.chairman,
    debateEnabled: Boolean(run.debate_enabled),
    members: buildMembers(run),
    runtimeModels: run.runtime_models ?? {},
    stages: {
      research: hasResearchEntries(run.research) ? "done" : "pending",
      fanout: "done",
      review: "done",
      synthesis: "done",
    },
    research: buildResearchCards(run.research),
    answers: buildCards(run.answers),
    reviews: buildCards(run.reviews),
    debateRounds: buildDebateRounds(run.debate),
    refereeSummaries: buildRefereeSummaries(run.debate),
    debateStoppedReason: run.debate?.stopped_reason ?? null,
    synth: fromSavedEntry(run.synthesis ?? {}),
    activityText: "Loaded from history.",
    activityTone: "done",
    runStartedAt: run.created_at ? Date.parse(run.created_at) : null,
  };
}

function buildMembers(run: CouncilRun): Member[] {
  const debateRoundNames = (run.debate?.rounds ?? []).flatMap((round) => Object.keys(round.responses ?? {}));
  const names = Array.from(new Set([
    ...Object.keys(run.answers || {}),
    ...Object.keys(run.reviews || {}),
    ...debateRoundNames,
    run.chairman,
    run.synthesis?.chairman ?? "",
    ...Object.keys(run.runtime_models || {}),
  ].filter(Boolean)));

  return names.map((name) => {
    const answer = run.answers?.[name];
    const review = run.reviews?.[name];
    return {
      name,
      display_name: answer?.display_name ?? review?.display_name ?? humanizeName(name),
      label: answer?.label ?? run.anonymization?.[name] ?? "?",
    };
  });
}

function buildDebateRounds(debate: CouncilRun["debate"]): DebateRoundState[] {
  return (debate?.rounds ?? []).map((round) => ({
    roundIndex: round.round_index,
    focusPoints: round.focus_points ?? [],
    responses: buildCards(round.responses ?? {}),
  }));
}

function buildRefereeSummaries(debate: CouncilRun["debate"]): RefereeSummaryState[] {
  return (debate?.referee_summaries ?? []).map((item) => ({
    roundIndex: item.round_index,
    decision: item.decision ?? "STOP",
    focusPoints: item.focus_points ?? [],
    text: item.text ?? "",
  }));
}

function beginCard(state: CardState): CardState {
  return {
    ...state,
    status: "streaming",
    acc: "",
    error: undefined,
    startedAt: Date.now(),
    finishedAt: undefined,
    chunks: 0,
    rateLimited: false,
  };
}

function appendCardDelta(state: CardState, text: string): CardState {
  return {
    ...state,
    status: state.status === "done" || state.status === "error" ? state.status : "streaming",
    acc: state.acc + text,
    chunks: state.chunks + 1,
  };
}

function finalize(state: CardState, finalText?: string, error?: string, rateLimited = false): CardState {
  if (error) {
    return { ...state, status: "error", error, finishedAt: Date.now(), rateLimited };
  }
  return {
    ...state,
    status: "done",
    finalText: finalText ?? state.acc,
    finishedAt: Date.now(),
    rateLimited: false,
  };
}

function withRunActivity(run: RunState, tone: ActivityTone, text: string): RunState {
  return { ...run, activityTone: tone, activityText: text };
}

function buildCards(entries: Record<string, { text?: string; error?: string }>): Record<string, CardState> {
  return Object.fromEntries(
    Object.entries(entries || {}).map(([name, entry]) => [name, fromSavedEntry(entry)]),
  );
}

function buildResearchCards(
  research: CouncilRun["research"],
): Record<string, CardState> {
  if (!research || Array.isArray(research)) return {};
  if ("text" in research || "error" in research || "chairman" in research) {
    const legacyModel = typeof research.chairman === "string" ? research.chairman : "claude";
    return {
      [legacyModel]: fromSavedEntry({
        text: research.text ?? undefined,
        error: research.error,
      }),
    };
  }
  return buildCards(research as Record<string, { text?: string; error?: string }>);
}

function hasResearchEntries(research: CouncilRun["research"]): boolean {
  return Object.keys(buildResearchCards(research)).length > 0;
}

function fromSavedEntry(entry: { text?: string; error?: string }): CardState {
  if (entry.error) {
    return {
      ...EMPTY_CARD,
      status: "error",
      error: entry.error,
      finalText: undefined,
      rateLimited: isRateLimited(entry.error),
    };
  }
  return {
    ...EMPTY_CARD,
    status: entry.text ? "done" : "idle",
    finalText: entry.text,
    acc: entry.text ?? "",
    chunks: 0,
  };
}

function getResearchParticipants(run: RunState, researchEnabled: boolean): Member[] {
  const names = Object.keys(run.research);
  if (names.length > 0) {
    return names.map((name) => run.members.find((member) => member.name === name) ?? { name, display_name: humanizeName(name), label: "?" });
  }
  if (!researchEnabled) return [];
  return run.members.filter((member) => DEFAULT_RESEARCH_PARTICIPANTS.includes(member.name));
}

function countFinished(cards: Record<string, CardState>): number {
  return Object.values(cards).filter((card) => card.status === "done" || card.status === "error").length;
}

function getRunStats(run: RunState, researchEnabled: boolean) {
  const researchMembers = getResearchParticipants(run, researchEnabled);
  const researchCount = researchEnabled ? researchMembers.length : 0;
  const answerCount = countFinished(run.answers);
  const reviewCount = countFinished(run.reviews);
  const researchDone = countFinished(run.research);
  const synthDone = run.synth.status === "done" || run.synth.status === "error" ? 1 : 0;
  const currentStage = STAGE_ORDER.find((stage) => run.stages[stage] === "running");
  return {
    currentStage,
    answerCount,
    reviewCount,
    researchCount,
    researchDone,
    timeline: [
      { label: "Final answer", status: run.stages.synthesis, count: synthDone ? "1/1" : run.synth.status === "streaming" ? "0/1" : "0/1" },
      { label: "Peer reviews", status: run.stages.review, count: `${reviewCount}/${Math.max(run.members.length, 0)}` },
      { label: "Independent answers", status: run.stages.fanout, count: `${answerCount}/${Math.max(run.members.length, 0)}` },
      ...(researchEnabled ? [{ label: "Web research", status: run.stages.research, count: `${researchDone}/${Math.max(researchCount, 0)}` }] : []),
    ],
  };
}

function formatRunCountSummary(
  run: RunState,
  stats: ReturnType<typeof getRunStats>,
  researchEnabled: boolean,
): string {
  const parts = [
    `A ${stats.answerCount}/${Math.max(run.members.length, 0)}`,
    run.debateEnabled ? `D ${run.debateRounds.length} rounds` : `R ${stats.reviewCount}/${Math.max(run.members.length, 0)}`,
  ];
  if (researchEnabled || Object.keys(run.research).length > 0) {
    parts.push(`W ${stats.researchDone}/${Math.max(getResearchParticipants(run, researchEnabled).length, 0)}`);
  }
  return parts.join(" · ");
}

function getSpotlightStage(run: RunState): Stage | null {
  if (run.stages.research === "running") return "research";
  if (run.stages.fanout === "running") return "fanout";
  if (run.stages.review === "running") return "review";
  return null;
}

function getSpotlightTitle(run: RunState, stage: Stage): string {
  if (stage === "research") return "Current stage: Web research";
  if (stage === "fanout") return "Current stage: Independent answers";
  if (stage === "review") {
    return run.debateEnabled ? "Current stage: Debate in progress" : "Current stage: Peer reviews";
  }
  return `Current stage: ${STAGE_TITLES[stage]}`;
}

function shouldShowFinalAnswer(run: RunState): boolean {
  return run.stages.synthesis !== "pending" || run.synth.status !== "waiting";
}

function shouldShowAnswers(run: RunState): boolean {
  return run.stages.fanout !== "pending" || Object.values(run.answers).some((card) => card.status !== "waiting");
}

function shouldShowResearch(run: RunState, researchEnabled: boolean): boolean {
  return (researchEnabled && run.stages.research !== "pending") || Object.keys(run.research).length > 0;
}

function shouldShowReviews(run: RunState): boolean {
  return run.stages.review !== "pending" || Object.values(run.reviews).some((card) => card.status !== "waiting");
}

function shouldShowDebate(run: RunState): boolean {
  return run.debateRounds.length > 0 || run.refereeSummaries.length > 0 || run.stages.review !== "pending";
}

function getMemberDisplay(run: RunState, name: string): string {
  return run.members.find((member) => member.name === name)?.display_name ?? humanizeName(name);
}

function useElapsed(startedAt: number | null, ticking: boolean): number {
  const [, setTick] = useState(0);
  useEffect(() => {
    if (!ticking || !startedAt) return;
    const id = window.setInterval(() => setTick((value) => value + 1), 150);
    return () => window.clearInterval(id);
  }, [startedAt, ticking]);
  if (!startedAt) return 0;
  const end = ticking ? Date.now() : startedAt;
  return Math.max(0, (end - startedAt) / 1000);
}

function isRateLimited(error?: string): boolean {
  if (!error) return false;
  const text = error.toLowerCase();
  return text.includes("rate limit") || text.includes("hit your limit") || text.includes("quota") || text.includes("too many requests");
}

function humanizeName(name: string): string {
  return name
    .split(/[-_]/g)
    .filter(Boolean)
    .map((part) => part[0]?.toUpperCase() + part.slice(1))
    .join(" ");
}

function formatHistoryDate(value?: string): string {
  if (!value) return "Unknown time";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat(undefined, {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  }).format(date);
}

function EmptyState() {
  return (
    <div className="empty-state">
      Start a new question at the top or open an existing thread from the history rail.
    </div>
  );
}

interface SettingsModalProps {
  onClose: () => void;
  settings: Record<string, CliSettings>;
  settingsMeta: Record<string, SettingsMeta>;
  appSettings: AppSettings;
  appSettingsMeta: Record<string, AppSettingsMeta>;
  settingsBusy: boolean;
  busy: boolean;
  onUpdate: (cli: string, patch: Partial<CliSettings>) => void;
  onAppUpdate: (patch: Partial<AppSettings>) => void;
}

function SettingsModal({
  onClose,
  settings,
  settingsMeta,
  appSettings,
  appSettingsMeta,
  settingsBusy,
  busy,
  onUpdate,
  onAppUpdate,
}: SettingsModalProps) {
  const enabledCount = Object.values(settings).filter((item) => item?.enabled !== false).length;
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <div className="modal-overlay" role="dialog" aria-modal="true" onClick={onClose}>
      <div className="modal-dialog" onClick={(e) => e.stopPropagation()}>
        <div className="modal-head">
          <div>
            <div className="modal-kicker">Settings</div>
            <h2 className="modal-title">Council configuration</h2>
          </div>
          <button className="modal-close" onClick={onClose} aria-label="Close settings">×</button>
        </div>
        {appSettingsMeta.research_enabled && (
          <label className="settings-toggle settings-toggle-block">
            <span>
              <span className="settings-label">{appSettingsMeta.research_enabled.label}</span>
              <span className="settings-help">{appSettingsMeta.research_enabled.description}</span>
            </span>
            <input
              type="checkbox"
              checked={Boolean(appSettings.research_enabled)}
              onChange={(e) => onAppUpdate({ research_enabled: e.target.checked })}
              disabled={busy || settingsBusy}
            />
          </label>
        )}
        <div className="settings-grid">
          {Object.entries(settingsMeta).map(([name, meta]) => {
            const current = settings[name] ?? {};
            const enabled = current.enabled ?? true;
            const canToggleEnabled = !(enabled && enabledCount <= 2) && !busy && !settingsBusy;
            const selectedKey = current.default_model ?? meta.models[0]?.key ?? "";
            const autoKeys = meta.thinking.auto_on_model_keys ?? [];
            const thinkingAuto = !meta.thinking.supported && autoKeys.length > 0;
            const autoActive = thinkingAuto && autoKeys.includes(selectedKey);
            return (
              <div
                key={name}
                className={`settings-card ${enabled ? "is-enabled" : "is-disabled"} ${canToggleEnabled ? "is-clickable" : "is-locked"}`}
                onClick={() => {
                  if (!canToggleEnabled) return;
                  onUpdate(name, { enabled: !enabled });
                }}
                role="button"
                tabIndex={0}
                onKeyDown={(e) => {
                  if (!canToggleEnabled) return;
                  if (e.key === "Enter" || e.key === " ") {
                    e.preventDefault();
                    onUpdate(name, { enabled: !enabled });
                  }
                }}
                aria-pressed={enabled}
              >
                <div className="settings-card-head">
                  <div className="settings-name">{meta.display_name}</div>
                  <span className={`settings-card-state ${enabled ? "is-enabled" : "is-disabled"}`}>
                    {enabled ? "Active" : "Inactive"}
                  </span>
                </div>
                <label className="settings-field">
                  <span className="settings-label">Default model</span>
                  <select
                    value={selectedKey}
                    onChange={(e) => onUpdate(name, { default_model: e.target.value })}
                    disabled={busy || settingsBusy}
                    onClick={(e) => e.stopPropagation()}
                    onKeyDown={(e) => e.stopPropagation()}
                  >
                    {meta.models.map((model) => (
                      <option key={model.key} value={model.key}>
                        {model.label}
                      </option>
                    ))}
                  </select>
                </label>
                {thinkingAuto ? (
                  <div className={`settings-status ${autoActive ? "is-on" : "is-off"}`}>
                    <span>
                      <span className="settings-label">{meta.thinking.label}</span>
                      <span className="settings-help">{meta.thinking.description}</span>
                    </span>
                    <span className="settings-status-pill">
                      {autoActive
                        ? (meta.thinking.auto_on_text ?? "Enabled")
                        : (meta.thinking.auto_off_text ?? "Managed by CLI")}
                    </span>
                  </div>
                ) : (
                  <label className={`settings-toggle ${!meta.thinking.supported ? "is-disabled" : ""}`}>
                    <span>
                      <span className="settings-label">{meta.thinking.label}</span>
                      <span className="settings-help">{meta.thinking.description}</span>
                    </span>
                    <input
                      type="checkbox"
                      checked={Boolean(current.thinking_enabled)}
                      onChange={(e) => onUpdate(name, { thinking_enabled: e.target.checked })}
                      disabled={busy || settingsBusy || !meta.thinking.supported}
                      onClick={(e) => e.stopPropagation()}
                      onKeyDown={(e) => e.stopPropagation()}
                    />
                  </label>
                )}
              </div>
            );
          })}
        </div>
        <div className="modal-foot">
          {settingsBusy ? "Saving…" : "Changes are saved automatically."}
          <button className="modal-done" onClick={onClose}>Done</button>
        </div>
      </div>
    </div>
  );
}
