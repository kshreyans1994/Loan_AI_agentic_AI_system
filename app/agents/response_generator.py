"""Response generation node — the final "Response Generation: LLM
generates accurate & contextual response" step. Grounds the reply in
plugin outputs and retrieved context rather than letting the model
freely narrate numbers, which matters a lot for a fintech use case."""
from __future__ import annotations

from langchain_groq import ChatGroq

from app.core.config import get_settings
from app.core.schemas import AgentState

RESPONSE_SYSTEM_PROMPT = """You are a helpful, concise loan application \
assistant. Use the structured data provided (plugin results, retrieved \
policy context, remembered facts about this user, and web search results \
when present) to answer the user. Never invent numbers that aren't in \
the provided data. If a human review decision is present, that decision \
is final — state it plainly and do not contradict or re-litigate it. If \
data is missing, ask the user for exactly what you \
need next. If you use a web search result, mention it's from a web \
lookup rather than stating it as settled policy. Keep responses \
conversational and under 5 sentences unless listing document \
requirements or offer details."""


def generate_response(state: AgentState) -> dict:
    settings = get_settings()
    llm = ChatGroq(api_key=settings.groq_api_key, model=settings.groq_model, temperature=0.3)

    last_user_message = next(
        (m.content for m in reversed(state.messages) if m.role == "user"), ""
    )

    context_parts = [f"User intent detected: {state.detected_intent}"]

    if state.supervisor_reasoning:
        context_parts.append(f"[supervisor] selected categories because: {state.supervisor_reasoning}")
    if state.intent_reasoning:
        context_parts.append(f"[intent agent] selected plugin(s) because: {state.intent_reasoning}")
    if state.risk_score is not None:
        context_parts.append(
            f"[decision agent] risk_score={state.risk_score}"
            + (f", factors: {'; '.join(state.risk_factors)}" if state.risk_factors else "")
        )

    if state.human_decision == "rejected":
        context_parts.append(
            "[human review] A human reviewer did NOT approve this response as drafted. "
            f"Reviewer note: {state.human_feedback or 'no note given'}. "
            "Do not present the plugin results as final — explain that this needs "
            "follow-up and relay the reviewer's note if there is one."
        )
    elif state.human_decision == "approved":
        context_parts.append(
            "[human review] A human reviewer approved this response."
            + (f" Reviewer note: {state.human_feedback}" if state.human_feedback else "")
        )

    if state.long_term_memory:
        remembered = "; ".join(f.fact for f in state.long_term_memory)
        context_parts.append(f"[remembered about this user] {remembered}")

    if state.plugin_results:
        for result in state.plugin_results:
            if result.success:
                context_parts.append(f"[{result.plugin_name}] result: {result.data}")
            else:
                context_parts.append(f"[{result.plugin_name}] failed: {result.error}")

    if state.retrieved_context:
        for chunk in state.retrieved_context:
            context_parts.append(f"[policy context - {chunk.source}] {chunk.content}")

    if state.web_search_results:
        for r in state.web_search_results:
            context_parts.append(f"[web result - {r.title}] {r.snippet} (source: {r.url})")

    context_block = "\n".join(context_parts)

    response = llm.invoke(
        [
            {"role": "system", "content": RESPONSE_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": f"User message: {last_user_message}\n\nAvailable data:\n{context_block}",
            },
        ]
    )

    return {"final_response": response.content}
