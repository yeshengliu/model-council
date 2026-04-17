export type Stage = "research" | "fanout" | "review" | "synthesis";
export type ThreadSummary = {
  id: string;
  title: string;
  latest_question?: string;
  created_at?: string;
  updated_at?: string;
  turn_count: number;
};
export type CouncilMemberInfo = {
  name: string;
  display_name: string;
  enabled?: boolean;
  binary: string;
  runtime_model_source: string;
  invocation: string[];
  options: { label: string; value: string }[];
  selected_model_label?: string;
  selected_model_key?: string;
  thinking_enabled?: boolean;
  thinking_supported?: boolean;
};
export type CliSettings = {
  enabled: boolean;
  default_model: string;
  thinking_enabled?: boolean;
};
export type SettingsOption = {
  key: string;
  label: string;
};
export type SettingsMeta = {
  display_name: string;
  models: SettingsOption[];
  thinking: {
    supported: boolean;
    label: string;
    description: string;
    auto_on_model_keys?: string[];
    auto_on_text?: string;
    auto_off_text?: string;
  };
};
export type AppSettings = {
  research_enabled: boolean;
};
export type AppSettingsMeta = {
  label: string;
  description: string;
};
export type SettingsPayload = {
  settings: Record<string, CliSettings>;
  options: Record<string, SettingsMeta>;
  app_settings: AppSettings;
  app_options: Record<string, AppSettingsMeta>;
};
export type SavedMemberEntry = { display_name: string; label?: string; text?: string; error?: string };
export type CouncilRun = {
  id: string;
  thread_id: string;
  parent_id?: string | null;
  turn_index: number;
  is_followup?: boolean;
  created_at?: string;
  question: string;
  chairman: string;
  debate_enabled?: boolean;
  anonymization?: Record<string, string>;
  runtime_models?: Record<string, string>;
  research?: Record<string, SavedMemberEntry> | { chairman?: string; text?: string | null; error?: string } | null;
  answers: Record<string, SavedMemberEntry>;
  reviews: Record<string, SavedMemberEntry>;
  debate?: {
    rounds?: Array<{
      round_index: number;
      focus_points?: string[];
      responses: Record<string, SavedMemberEntry>;
    }>;
    referee_summaries?: Array<{
      round_index: number;
      decision?: string;
      focus_points?: string[];
      text?: string;
    }>;
    stopped_reason?: string | null;
  } | null;
  synthesis?: { chairman?: string; text?: string; error?: string } | null;
};
export type ThreadDetail = {
  id: string;
  title: string;
  created_at?: string;
  updated_at?: string;
  turn_count: number;
  runs: CouncilRun[];
};
export type CouncilInfo = {
  members: CouncilMemberInfo[];
  chairman: string;
};

export type CouncilEvent =
  | {
      type: "start";
      id: string;
      thread_id: string;
      parent_id?: string | null;
      turn_index: number;
      is_followup: boolean;
      debate_enabled?: boolean;
      question: string;
      chairman: string;
      members: { name: string; display_name: string; label: string }[];
    }
  | { type: "stage"; stage: Stage; status: "started" | "done" }
  | { type: "model_started"; stage: Stage; model: string }
  | { type: "model_meta"; stage: Stage; model: string; runtime_model?: string }
  | { type: "delta"; stage: Stage; model: string; text: string }
  | { type: "chairman_fallback"; from: string; to: string; reason: string }
  | { type: "answer"; model: string; display_name: string; label: string; text?: string; error?: string }
  | { type: "review"; reviewer: string; display_name: string; text?: string; error?: string }
  | { type: "debate_round_started"; round: number }
  | { type: "debate_turn"; round: number; model: string; display_name: string; text?: string; error?: string }
  | { type: "debate_round_done"; round: number }
  | { type: "debate_referee"; round: number; decision: string; focus_points?: string[]; text: string }
  | { type: "synthesis"; chairman: string; text?: string; error?: string }
  | { type: "research"; model: string; display_name: string; text?: string | null; error?: string }
  | { type: "done"; id: string; thread_id: string; path: string };

export async function* streamAsk(
  payload: {
    question: string;
    thread_id?: string | null;
    parent_id?: string | null;
    debate_enabled?: boolean;
  },
  signal?: AbortSignal,
): AsyncGenerator<CouncilEvent> {
  const resp = await fetch("/api/ask", {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
    body: JSON.stringify(payload),
    signal,
  });
  if (!resp.ok || !resp.body) {
    throw new Error(`ask failed: ${resp.status} ${await resp.text()}`);
  }

  const reader = resp.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { value, done } = await reader.read();
    buffer += decoder.decode(value ?? new Uint8Array(), { stream: !done });

    for (const frame of drainFrames(() => buffer, (next) => { buffer = next; })) {
      const event = parseFrame(frame);
      if (event) yield event;
    }

    if (done) break;
  }

  if (buffer.trim()) {
    const event = parseFrame(buffer);
    if (event) yield event;
  }
}

export async function listConversations(signal?: AbortSignal): Promise<ThreadSummary[]> {
  const resp = await fetch("/api/conversations", { signal });
  if (!resp.ok) {
    throw new Error(`history failed: ${resp.status} ${await resp.text()}`);
  }
  return (await resp.json()) as ThreadSummary[];
}

export async function getThread(id: string, signal?: AbortSignal): Promise<ThreadDetail> {
  const resp = await fetch(`/api/threads/${id}`, { signal });
  if (!resp.ok) {
    throw new Error(`thread failed: ${resp.status} ${await resp.text()}`);
  }
  return (await resp.json()) as ThreadDetail;
}

export async function getCouncilInfo(signal?: AbortSignal): Promise<CouncilInfo> {
  const resp = await fetch("/api/council", { signal });
  if (!resp.ok) {
    throw new Error(`council info failed: ${resp.status} ${await resp.text()}`);
  }
  return (await resp.json()) as CouncilInfo;
}

export async function getSettings(signal?: AbortSignal): Promise<SettingsPayload> {
  const resp = await fetch("/api/settings", { signal });
  if (!resp.ok) {
    throw new Error(`settings failed: ${resp.status} ${await resp.text()}`);
  }
  return (await resp.json()) as SettingsPayload;
}

export async function saveSettings(
  payload: { settings?: Record<string, CliSettings>; app_settings?: AppSettings },
  signal?: AbortSignal,
): Promise<SettingsPayload> {
  const resp = await fetch("/api/settings", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
    signal,
  });
  if (!resp.ok) {
    throw new Error(`settings save failed: ${resp.status} ${await resp.text()}`);
  }
  return (await resp.json()) as SettingsPayload;
}

function drainFrames(getBuffer: () => string, setBuffer: (value: string) => void): string[] {
  const frames: string[] = [];
  while (true) {
    const buffer = getBuffer();
    const match = buffer.match(/\r?\n\r?\n/);
    if (!match || match.index == null) break;
    frames.push(buffer.slice(0, match.index));
    setBuffer(buffer.slice(match.index + match[0].length));
  }
  return frames;
}

function parseFrame(frame: string): CouncilEvent | null {
  const dataLines = frame
    .split(/\r?\n/)
    .filter((line) => line.startsWith("data:"))
    .map((line) => line.slice(5).trimStart());
  if (dataLines.length === 0) return null;

  const raw = dataLines.join("\n");
  try {
    return JSON.parse(raw) as CouncilEvent;
  } catch (e) {
    console.warn("bad SSE payload", raw, e);
    return null;
  }
}
