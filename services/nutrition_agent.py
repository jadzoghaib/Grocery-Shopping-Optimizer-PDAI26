"""Nutrition specialist agent — LangGraph ReAct (Groq).

Separate from the grocery RAG agent. Covers:
  - Macro & calorie target calculation (Mifflin-St Jeor + PAL)
  - Specific diet programs (keto, Mediterranean, IF, DASH, bulking/cutting)
  - Full weekly meal plan generation with daily macro breakdown
  - Food & ingredient nutritional lookup

Entry point: nutrition_answer(question, messages_history, api_key) -> str
"""
from __future__ import annotations

import json as _json

# Heavy imports (langchain_core, langchain_groq, langgraph, nutrition_tools) are
# deferred to first use inside _build_nutrition_agent / nutrition_answer so the
# FastAPI server can bind its port without loading these large packages at startup.

# ── Pinned model (same as shopping + grocery chat) ────────────────────────────

NUTRITION_MODEL = "llama-3.3-70b-versatile"

# ── System prompt ─────────────────────────────────────────────────────────────

NUTRITION_SYSTEM_PROMPT = """You are an expert nutrition coach AI. Your job is to help users achieve their health and body composition goals through evidence-based nutrition guidance.

You specialise in:
- Macro & calorie target calculation (always use calculate_macros for this — never guess)
- Specific diet programs: keto, Mediterranean, intermittent fasting (IF), DASH, bulking, cutting, recomposition
- Full weekly meal plans tailored to the user's calorie and macro targets
- Food and ingredient nutritional lookup (always use lookup_food for specific values — never invent numbers)

WORKFLOW for nutrition programs:
1. If the user wants a program or targets, call calculate_macros first to establish their TDEE and daily targets.
2. Use search_nutrition_knowledge for diet-specific guidance, foods, and principles.
3. Build a concrete, practical plan using their calculated targets.

WORKFLOW for food questions:
1. Always call lookup_food before stating any calorie or macro values.
2. Never invent nutritional data. If lookup_food returns no result, say so clearly.

MEAL PLAN EXPORT:
When you produce a complete weekly meal plan, append this JSON on its own line at the end of your response (no markdown fences):
{"nutrition_plan": [{"day": "Monday", "meals": [{"slot": "Breakfast", "name": "...", "kcal": 400}, {"slot": "Lunch", "name": "...", "kcal": 600}, {"slot": "Dinner", "name": "...", "kcal": 700}], "total_kcal": 1700}]}
This allows the user to optionally import the plan into the Meal Planner.

TONE: Practical, encouraging, evidence-based. Use plain language. No unnecessary caveats — give direct, actionable advice.
"""

# ── Agent builder (all heavy imports are lazy) ────────────────────────────────

def _build_nutrition_agent(api_key: str):
    """Build and return a compiled LangGraph ReAct agent for nutrition coaching.

    langchain_core, langgraph, and nutrition_tools are imported here — not at
    module level — so the FastAPI server can bind its port before these large
    packages are loaded.
    """
    from langgraph.prebuilt import create_react_agent  # lazy
    from core.llm_config import build_llm
    from services.nutrition_tools import (  # lazy — also triggers langchain_core import
        calculate_macros, lookup_food, search_nutrition_knowledge
    )
    llm = build_llm(api_key.strip(), temperature=0.3)
    return create_react_agent(llm, tools=[calculate_macros, lookup_food, search_nutrition_knowledge])


# ── Main entry point ──────────────────────────────────────────────────────────

def nutrition_answer(question: str, messages_history: list, api_key: str) -> str:
    """Run the nutrition specialist ReAct agent. Returns final text response."""
    from langchain_core.messages import SystemMessage, HumanMessage, AIMessage  # lazy
    agent = _build_nutrition_agent(api_key)

    lc_messages = [SystemMessage(content=NUTRITION_SYSTEM_PROMPT)]
    for m in messages_history:
        role    = m.get("role", "user")
        content = m.get("content", "")
        if role == "user":
            lc_messages.append(HumanMessage(content=content))
        elif role == "assistant":
            lc_messages.append(AIMessage(content=content))

    lc_messages.append(HumanMessage(content=question))

    print(f"[Nutrition/{NUTRITION_MODEL}] LangGraph ReAct agent invoked")
    try:
        result = agent.invoke({"messages": lc_messages})
        final  = result["messages"][-1]
        return (final.content or "").strip()
    except Exception as e:
        print(f"[Nutrition/{NUTRITION_MODEL}] agent error: {e}")
        return "I encountered an error. Please try again."


# ── Nutrition plan parser ─────────────────────────────────────────────────────

def parse_nutrition_plan(reply: str) -> tuple[str, list]:
    """Split agent reply into (display_text, nutrition_plan_days).

    Extracts the optional {"nutrition_plan": [...]} JSON appended by the agent
    when it produces a full weekly plan. Returns (cleaned_text, list_of_days).
    Each day: {"day": str, "meals": [...], "total_kcal": int}
    """
    key = '"nutrition_plan"'
    idx = reply.find(key)
    if idx == -1:
        return reply, []

    start = reply.rfind('{', 0, idx)
    if start == -1:
        return reply, []

    depth, end = 0, -1
    for i, ch in enumerate(reply[start:], start):
        if ch == '{':
            depth += 1
        elif ch == '}':
            depth -= 1
            if depth == 0:
                end = i + 1
                break

    if end == -1:
        return reply[:start].strip(), []

    try:
        data  = _json.loads(reply[start:end])
        plan  = data.get("nutrition_plan", [])
        clean = (reply[:start] + reply[end:]).strip()
        return clean, plan if isinstance(plan, list) else []
    except Exception:
        return reply, []
