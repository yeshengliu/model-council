import { useEffect, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

export type CardStatus = "idle" | "waiting" | "streaming" | "done" | "error";

export interface ModelCardProps {
  name: string;
  displayName: string;
  runtimeModel?: string;
  label?: string;
  status: CardStatus;
  text: string;
  error?: string;
  startedAt?: number;
  finishedAt?: number;
  heading?: string;
  accentColor?: string;
  chunks?: number;
  rateLimited?: boolean;
}

const colorByName: Record<string, string> = {
  claude: "#d97706",
  gemini: "#58a6ff",
  codex: "#3fb950",
};

export function ModelCard({
  name,
  displayName,
  runtimeModel,
  label,
  status,
  text,
  error,
  startedAt,
  finishedAt,
  heading,
  accentColor,
  chunks = 0,
  rateLimited = false,
}: ModelCardProps) {
  const accent = accentColor ?? colorByName[name] ?? "#8b949e";
  const elapsed = useElapsed(startedAt, finishedAt, status === "streaming" || status === "waiting");
  const runtimeLabel = runtimeModel?.trim() || "Model unavailable";
  const runtimeClassName = runtimeModel?.trim() ? "model-runtime" : "model-runtime model-runtime-unknown";

  return (
    <div
      className={`model-card status-${status} ${rateLimited ? "is-rate-limited" : ""}`}
      style={{ "--accent": accent } as React.CSSProperties}
    >
      <div className="model-card-header">
        <span className="model-dot" />
        <div className="model-title">
          <span className="model-name">{heading ?? displayName}</span>
          <span className={runtimeClassName}>{runtimeLabel}</span>
        </div>
        {label && <span className="model-label">Model {label}</span>}
        <span className="model-elapsed">{elapsed ? `${elapsed.toFixed(1)}s` : ""}</span>
        <StatusBadge status={status} />
      </div>
      <div className="model-card-body">
        {rateLimited && (
          <div className="rate-limit-banner">
            <span className="rate-limit-icon" />
            Rate limited. The council can retry or fall back to another model.
          </div>
        )}
        {(status === "streaming" || status === "done") && chunks > 0 && (
          <div className="chunk-meta">{chunks} stream chunk{chunks === 1 ? "" : "s"}</div>
        )}
        {status === "idle" && <div className="placeholder-line">Ready.</div>}
        {status === "waiting" && (
          <>
            <div className="shimmer" />
            <div className="shimmer short" />
            <div className="shimmer" />
          </>
        )}
        {status === "error" && (
          <pre className="error-body">{error ?? "unknown error"}</pre>
        )}
        {(status === "streaming" || status === "done") && (
          <div className="markdown">
            <ReactMarkdown remarkPlugins={[remarkGfm]}>{text}</ReactMarkdown>
            {status === "streaming" && <span className="caret">▊</span>}
          </div>
        )}
      </div>
    </div>
  );
}

function StatusBadge({ status }: { status: CardStatus }) {
  const styles: Record<CardStatus, { label: string; className: string }> = {
    idle: { label: "idle", className: "badge-idle" },
    waiting: { label: "waiting", className: "badge-waiting" },
    streaming: { label: "streaming", className: "badge-streaming" },
    done: { label: "done", className: "badge-done" },
    error: { label: "error", className: "badge-error" },
  };
  const s = styles[status];
  return <span className={`status-badge ${s.className}`}>{s.label}</span>;
}

function useElapsed(startedAt?: number, finishedAt?: number, ticking?: boolean): number {
  const [, setTick] = useState(0);
  useEffect(() => {
    if (!ticking) return;
    const id = window.setInterval(() => setTick((t) => t + 1), 150);
    return () => window.clearInterval(id);
  }, [ticking]);
  if (!startedAt) return 0;
  const end = finishedAt ?? Date.now();
  return Math.max(0, (end - startedAt) / 1000);
}
