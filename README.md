# Model Council

<p align="center">
  <img src="output/app-icon/model-council-art-icon-1024.png" alt="Model Council app icon" width="160" />
</p>

Model Council is a local multi-model reasoning app built on top of the CLIs you already pay for:

- **Claude Code**
- **Gemini CLI**
- **Codex CLI**

It runs those tools as subprocesses, lets them research, answer, debate, and synthesize, and stores everything as reusable conversation threads.

Inspired by [karpathy/llm-council](https://github.com/karpathy/llm-council).

## Why this exists

Most “multi-model” apps just ask several models once and average the result. This project is meant to be more adversarial:

- models answer independently
- models can critique or debate each other
- a chairman synthesizes the final answer
- follow-up questions stay in the same thread with prior context

The goal is not perfect neutrality. The goal is a more inspectable answer path.

## Features

- **Normal mode**
  - web research
  - independent answers
  - peer review
  - synthesis
- **Debate mode**
  - web research
  - independent answers
  - multi-round rebuttal
  - referee summaries
  - synthesis
- **Threaded follow-ups**
  - new questions create a thread
  - follow-ups append a new run to the selected thread
- **Per-model settings**
  - enable or disable models
  - choose default model per CLI
  - toggle thinking where supported
- **Live UI**
  - shows the currently active stage first
  - streams research / answers / debate before the final answer appears

## Current model roles

- **Claude + Codex** can run the web research stage
- **Claude, Gemini, Codex** can answer, debate, and synthesize
- chairman fallback is automatic if the current chairman is rate-limited

At least **2 models must remain enabled**.

## Requirements

You need all three CLIs installed and logged in on the same machine:

```bash
claude auth status
gemini --version
codex login status
```

You also need:

- `uv`
- `node >= 20`
- `python3`
- Xcode command line tools (`xcrun`, `swiftc`)

## Provider disclaimer

Model Council is a local wrapper around official provider tools. You are responsible for complying with the applicable terms, usage policies, rate limits, and account restrictions for Claude Code, Gemini CLI / Gemini API, and Codex CLI / OpenAI.

This project is intended for users running those tools with their own accounts and credentials on their own machines. It is not a claim of endorsement, partnership, or guaranteed policy compliance from Anthropic, Google, or OpenAI.

If you adapt this project into a hosted service, shared proxy, team gateway, or any flow that routes provider requests on behalf of other users, review the providers' commercial terms and authentication rules before doing so.

## Quick start

### Development

```bash
# backend
uv venv
uv pip install -e .
uv run uvicorn backend.main:app --reload --port 8000

# frontend (separate terminal)
cd frontend
npm install
npm run dev
```

Open [http://localhost:5173](http://localhost:5173).

Run the backend smoke tests:

```bash
uv run python -m unittest discover -s tests
```

### Single-port mode

```bash
cd frontend
npm install
npm run build
cd ..

uv run uvicorn backend.main:app --port 8000
```

Open [http://localhost:8000](http://localhost:8000).

### Local app bundle

Anyone on a supported Mac can build the unsigned macOS wrapper from source:

```bash
python3 scripts/build_macos_app.py
```

Build requirements:

- macOS
- `python3`
- `node >= 20`
- Xcode command line tools (`xcrun`, `swiftc`)
- the icon files in `output/app-icon/`

This repackages the current frontend build and backend entrypoint into:

- `macos/build/Model Council.app`
- `macos/build/Model-Council-macOS.zip`

Install flow:

1. Unzip the archive if needed.
2. Drag `Model Council.app` into `/Applications` or run it in place.
3. On first launch, right-click the app and choose **Open** to bypass Gatekeeper once.
4. The wrapper checks `claude`, `gemini`, and `codex` before starting the bundled backend.

The macOS wrapper keeps using the existing web UI, so frontend design changes ship into the app by rebuilding and repackaging.

## How to use it

- Type a question and click **Ask** for the standard council flow
- Long-press **Debate** to run the debate flow
- Select a thread from the left rail to continue it with follow-ups
- Open **Model settings** to:
  - enable / disable models
  - switch each CLI’s default model
  - change thinking behavior where supported
