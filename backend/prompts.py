from __future__ import annotations

COUNCIL_SYSTEM = (
    "You are participating in a council of diverse AI models. "
    "Answer the user's question directly and honestly. Be concise but complete. "
    "Do not mention which model you are."
)

RESEARCH_SYSTEM = (
    "You are a research assistant preparing grounding material for a panel of AI models. "
    "Given a user question, use WebSearch and WebFetch to gather 5–10 concise, current, "
    "diverse findings that will help the panel answer. Prefer authoritative sources from "
    "the last 12 months when recency matters. Output ONLY a numbered list of findings; "
    "do not attempt to answer the question yourself.\n\n"
    "Format each finding as:\n"
    "N. <short factual statement> — Source: <brief description> (<URL>)"
)


def research_prompt(question: str) -> str:
    return (
        "Gather current, well-sourced findings that will help a council of AI models "
        "answer the question below. Return ONLY the numbered findings list.\n\n"
        f"## Question\n{question.strip()}"
    )


def wrap_with_research(question: str, research: str | None) -> str:
    if not research or not research.strip():
        return question
    return (
        "[Research context gathered from the web — prefer it over training data for "
        "time-sensitive claims; cite sources by the numbers below when relevant.]\n\n"
        f"{research.strip()}\n\n"
        "---\n\n"
        f"## Question\n{question.strip()}"
    )


def wrap_with_followup_context(question: str, parent_run: dict | None) -> str:
    if not parent_run:
        return question

    def _member_block(title: str, entries: dict | None) -> str:
        if not entries:
            return f"## {title}\n(none)"
        blocks: list[str] = []
        for name, entry in entries.items():
            if not isinstance(entry, dict):
                continue
            display = entry.get("display_name") or name
            body = entry.get("text") or f"(error: {entry.get('error', 'unknown error')})"
            blocks.append(f"### {display}\n{str(body).strip()}")
        return f"## {title}\n" + ("\n\n".join(blocks) if blocks else "(none)")

    research = parent_run.get("research") or {}
    research_block = _member_block("Previous web research", research)
    answers_block = _member_block("Previous independent answers", parent_run.get("answers") or {})
    reviews_block = _member_block("Previous peer reviews", parent_run.get("reviews") or {})
    synthesis = parent_run.get("synthesis") or {}
    synthesis_text = synthesis.get("text") or f"(error: {synthesis.get('error', 'unknown error')})"

    return (
        "[This is a follow-up question in an ongoing council thread. Use the previous run as context, "
        "but answer the new follow-up question directly.]\n\n"
        f"## Previous question\n{str(parent_run.get('question', '')).strip()}\n\n"
        f"{research_block}\n\n"
        f"{answers_block}\n\n"
        f"{reviews_block}\n\n"
        f"## Previous final answer\n{str(synthesis_text).strip()}\n\n"
        "---\n\n"
        f"## Follow-up question\n{question.strip()}"
    )


def peer_review_prompt(
    question: str,
    anonymized_others: list[tuple[str, str]],  # [(label, response), ...]
) -> str:
    blocks = "\n\n".join(
        f"### Response from Model {label}\n{body.strip()}"
        for label, body in anonymized_others
    )
    return (
        "You are reviewing responses from other AI models to the same question. "
        "Their identities are hidden. Rate each response on accuracy and insight (1-10), "
        "call out factual errors or weak reasoning, note genuine disagreements, and say what you would add or change.\n\n"
        f"## Original question\n{question.strip()}\n\n"
        f"## Responses to review\n{blocks}\n\n"
        "## Your review\n"
        "For each Model letter, produce:\n"
        "- **Accuracy**: <score>/10 — <one sentence>\n"
        "- **Insight**: <score>/10 — <one sentence>\n"
        "- **Disagreements / errors**: <bullet list, or 'none'>\n"
        "- **What you would add**: <brief>\n"
        "\nThen end with a one-line overall ranking (e.g. `Ranking: B > A`)."
    )


def synthesis_prompt(
    question: str,
    named_answers: list[tuple[str, str]],    # [(display_name, response), ...]
    named_reviews: list[tuple[str, str]],    # [(display_name, review), ...]
) -> str:
    answer_blocks = "\n\n".join(
        f"### {name}\n{body.strip()}" for name, body in named_answers
    )
    review_blocks = "\n\n".join(
        f"### Review by {name}\n{body.strip()}" for name, body in named_reviews
    )
    return (
        "You are the Chairman of an AI model council. Synthesize the final answer to the user's question.\n\n"
        "Principles:\n"
        "- Prefer claims supported by multiple council members.\n"
        "- Explicitly flag any unresolved disagreements rather than hiding them.\n"
        "- Correct any factual errors the reviewers identified.\n"
        "- Be direct and useful; do not summarize the process unless the user would benefit.\n\n"
        f"## Original question\n{question.strip()}\n\n"
        f"## Council answers\n{answer_blocks}\n\n"
        f"## Peer reviews\n{review_blocks}\n\n"
        "## Final consolidated answer\n"
        "Write the single best answer now. If there is a material disagreement, include a short "
        "**Disagreements** section at the end listing what remains contested and why it matters."
    )


def debate_rebuttal_prompt(
    question: str,
    own_answer: str,
    others: list[tuple[str, str]],
    focus_points: list[str] | None = None,
) -> str:
    others_block = "\n\n".join(
        f"### {name}\n{body.strip()}" for name, body in others
    )
    focus_block = ""
    if focus_points:
        focus_block = "## Focus points for this round\n" + "\n".join(f"- {point}" for point in focus_points) + "\n\n"
    return (
        "You are participating in a structured debate with other frontier AI models. "
        "Read their answers and respond only to the strongest unresolved disagreements.\n\n"
        f"## Original question\n{question.strip()}\n\n"
        f"## Your current position\n{own_answer.strip()}\n\n"
        f"{focus_block}"
        f"## Other model positions\n{others_block}\n\n"
        "## Your rebuttal\n"
        "Write four short sections:\n"
        "1. **Main disagreements** — 1-3 bullets naming the exact claims you reject.\n"
        "2. **Counterarguments** — concise rebuttals, distinguishing factual, reasoning, or scope disagreements.\n"
        "3. **Concessions / updates** — what you now accept, narrow, or revise.\n"
        "4. **Current position** — your updated best answer in 2-5 bullets.\n"
        "Be concrete. Do not just summarize everyone."
    )


def debate_referee_prompt(
    question: str,
    named_answers: list[tuple[str, str]],
    debate_rounds: list[dict],
) -> str:
    answer_blocks = "\n\n".join(
        f"### {name}\n{body.strip()}" for name, body in named_answers
    )
    round_blocks: list[str] = []
    for round_entry in debate_rounds:
        round_index = round_entry.get("round_index", 0)
        responses = round_entry.get("responses", {})
        body = "\n\n".join(
            f"### {name}\n{(entry.get('text') or entry.get('error') or '(no response)').strip()}"
            for name, entry in responses.items()
            if isinstance(entry, dict)
        )
        round_blocks.append(f"## Debate round {round_index}\n{body}")
    return (
        "You are the referee of a structured AI debate. Summarize the highest-value disagreements only.\n\n"
        f"## Original question\n{question.strip()}\n\n"
        f"## Initial answers\n{answer_blocks}\n\n"
        f"{chr(10).join(round_blocks)}\n\n"
        "Return exactly this format:\n"
        "Decision: CONTINUE or STOP\n"
        "Focus points:\n"
        "- <point>\n"
        "- <point>\n"
        "Convergences:\n"
        "- <point>\n"
        "Open disagreements:\n"
        "- <point>\n"
        "Reason:\n"
        "<one short paragraph>\n"
    )


def debate_synthesis_prompt(
    question: str,
    named_answers: list[tuple[str, str]],
    debate_rounds: list[dict],
    referee_summaries: list[str],
) -> str:
    answer_blocks = "\n\n".join(
        f"### {name}\n{body.strip()}" for name, body in named_answers
    )
    round_blocks: list[str] = []
    for round_entry in debate_rounds:
        round_index = round_entry.get("round_index", 0)
        responses = round_entry.get("responses", {})
        body = "\n\n".join(
            f"### {name}\n{(entry.get('text') or entry.get('error') or '(no response)').strip()}"
            for name, entry in responses.items()
            if isinstance(entry, dict)
        )
        round_blocks.append(f"## Debate round {round_index}\n{body}")
    referee_block = "\n\n".join(
        f"## Referee summary {index + 1}\n{text.strip()}"
        for index, text in enumerate(referee_summaries)
    )
    return (
        "You are the Chairman of an AI debate council. Produce the single best final answer.\n\n"
        "Principles:\n"
        "- Prefer claims that survived direct rebuttal.\n"
        "- If a model conceded a point, treat that as evidence of convergence.\n"
        "- Preserve unresolved disagreements explicitly.\n"
        "- Be concise but complete.\n\n"
        f"## Original question\n{question.strip()}\n\n"
        f"## Initial answers\n{answer_blocks}\n\n"
        f"{chr(10).join(round_blocks)}\n\n"
        f"{referee_block}\n\n"
        "## Final consolidated answer\n"
        "Write the best final answer now. End with a short **Disagreements** section if any material dispute remains."
    )
