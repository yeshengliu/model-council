import type { Stage } from "../api";

type StageStatus = "pending" | "running" | "done";

export function StageBar({ stages }: { stages: Record<Stage, StageStatus> }) {
  const labels: Record<Stage, string> = {
    research: "0 · Research",
    fanout: "1 · Independent",
    review: "2 · Peer review",
    synthesis: "3 · Synthesis",
  };
  const order: Stage[] = (["research", "fanout", "review", "synthesis"] as Stage[])
    .filter((s) => s !== "research" || stages.research !== "pending");
  return (
    <div className="stage-bar">
      {order.map((s) => {
        const status = stages[s];
        return (
          <div key={s} className={`stage-segment stage-${status}`}>
            <div className="stage-label">{labels[s]}</div>
            <div className="stage-track">
              <div className={`stage-fill stage-fill-${status}`} />
            </div>
          </div>
        );
      })}
    </div>
  );
}
