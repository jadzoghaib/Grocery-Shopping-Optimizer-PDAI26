"""Multi-agent basket debate — Budget Optimizer vs Nutritionist.

Architecture (matches the Agentic AI diagram):

  Each agent has:
    Memory     — shared basket state + conversation history
    Tools      — deterministic analysis functions
    Orchestrator LLM  — LangGraph create_react_agent (Groq)
    Planning   — ReAct reasoning loop decides which tools to call
    Feedback   — tool results loop back into the agent before final response

  Multi-agent protocol:
    1. Budget agent analyses basket with its tools → produces argument
    2. Nutrition agent analyses basket with its tools → produces argument
    3. Moderator LLM reads both arguments → produces a balanced verdict

Public API
----------
debate_basket(items, api_key) -> dict
    Returns {"budget": str, "nutrition": str, "verdict": str, "total": float}
"""
from __future__ import annotations

import json

DEBATE_MODEL = "llama-3.3-70b-versatile"

# ══════════════════════════════════════════════════════════════════════════════
# Shared basket state  (passed to both agents as tool input)
# ══════════════════════════════════════════════════════════════════════════════

def _parse_basket(items: list[dict]) -> list[dict]:
    """Normalise raw shopping-list row dicts into a clean list."""
    parsed = []
    for it in items:
        parsed.append({
            "name":       it.get("SKU") or it.get("name") or it.get("Ingredient") or "?",
            "price":      float(it.get("Total Price") or it.get("total_price") or it.get("price") or 0),
            "count":      int(it.get("Count") or it.get("count") or 1),
            "pack_size":  it.get("Pack Size") or it.get("pack_size") or "",
            "unit_price": float(it.get("Unit Price") or it.get("unit_price") or 0),
        })
    return parsed


# ══════════════════════════════════════════════════════════════════════════════
# Budget agent tools  (deterministic — no LLM inside)
# ══════════════════════════════════════════════════════════════════════════════

def _make_budget_tools(basket: list[dict]):
    """Return LangChain tools scoped to this basket."""
    from langchain_core.tools import tool

    @tool
    def get_basket_cost_breakdown() -> str:
        """Return a cost breakdown of all items in the basket, sorted by price descending."""
        sorted_items = sorted(basket, key=lambda x: x["price"], reverse=True)
        total = sum(i["price"] for i in basket)
        lines = [f"Total basket: €{total:.2f}\n"]
        for i in sorted_items:
            pct = (i["price"] / total * 100) if total else 0
            lines.append(
                f"- {i['name']}: €{i['price']:.2f} ({pct:.0f}%) "
                f"— {i['count']} × {i['pack_size']} @ €{i['unit_price']:.2f} each"
            )
        return "\n".join(lines)

    @tool
    def identify_overbuying() -> str:
        """Identify items where the user may have bought more packs than needed for a week."""
        flags = []
        for i in basket:
            # Heuristic: more than 3 packs of anything perishable is potentially over-buying
            name_lower = i["name"].lower()
            is_perishable = any(k in name_lower for k in [
                "leche", "milk", "yogur", "yogurt", "fruta", "fruit",
                "verdura", "vegetable", "pollo", "chicken", "carne", "meat",
                "fish", "pescado", "pan", "bread",
            ])
            if is_perishable and i["count"] > 3:
                flags.append(
                    f"- {i['name']}: {i['count']} packs — may be over-buying for one week"
                )
        return "\n".join(flags) if flags else "No obvious over-buying detected."

    @tool
    def get_category_cost_split() -> str:
        """Estimate what % of spend goes to protein, produce, and pantry categories."""
        protein_kw  = ["pollo", "chicken", "carne", "meat", "pescado", "fish",
                       "huevo", "egg", "atun", "tuna", "salmon", "jamon", "ham"]
        produce_kw  = ["fruta", "fruit", "verdura", "vegetable", "lechuga", "lettuce",
                       "tomate", "tomato", "zanahoria", "carrot", "manzana", "apple",
                       "platano", "banana", "naranja", "orange"]

        protein_cost = produce_cost = pantry_cost = 0.0
        for i in basket:
            n = i["name"].lower()
            if any(k in n for k in protein_kw):
                protein_cost += i["price"]
            elif any(k in n for k in produce_kw):
                produce_cost += i["price"]
            else:
                pantry_cost += i["price"]

        total = sum(i["price"] for i in basket) or 1
        return (
            f"Protein:  €{protein_cost:.2f} ({protein_cost/total*100:.0f}%)\n"
            f"Produce:  €{produce_cost:.2f} ({produce_cost/total*100:.0f}%)\n"
            f"Pantry:   €{pantry_cost:.2f} ({pantry_cost/total*100:.0f}%)"
        )

    @tool
    def search_cheaper_alternative(product_name: str) -> str:
        """Search Mercadona for a cheaper alternative to a specific product. Returns up to 3 options with prices."""
        try:
            from core.shopping import _search_bilingual_scored
            candidates, _ = _search_bilingual_scored(product_name, top_k=3)
            if candidates.empty:
                return f"No alternatives found for '{product_name}' in Mercadona."
            lines = [f"Mercadona alternatives for '{product_name}':"]
            for _, row in candidates.iterrows():
                name  = str(row.get("name", ""))
                price = float(row.get("price", 0))
                unit  = str(row.get("unit", ""))
                lines.append(f"  - {name} ({unit}): €{price:.2f}")
            return "\n".join(lines)
        except Exception as e:
            return f"Search error: {e}"

    return [get_basket_cost_breakdown, identify_overbuying, get_category_cost_split, search_cheaper_alternative]


# ══════════════════════════════════════════════════════════════════════════════
# Nutrition agent tools  (deterministic — no LLM inside)
# ══════════════════════════════════════════════════════════════════════════════

def _make_nutrition_tools(basket: list[dict]):
    from langchain_core.tools import tool

    @tool
    def check_food_group_coverage() -> str:
        """Check which major food groups are present or missing in the basket."""
        groups = {
            "Protein (meat/fish/eggs/legumes)": [
                "pollo", "chicken", "carne", "meat", "pescado", "fish",
                "huevo", "egg", "atun", "tuna", "salmon", "legumbre",
                "garbanzo", "lenteja", "lentil", "jamon", "ham",
            ],
            "Dairy": [
                "leche", "milk", "yogur", "yogurt", "queso", "cheese",
                "mantequilla", "butter",
            ],
            "Vegetables": [
                "verdura", "vegetable", "lechuga", "lettuce", "tomate",
                "tomato", "zanahoria", "carrot", "espinaca", "spinach",
                "brocoli", "broccoli", "cebolla", "onion", "ajo", "garlic",
            ],
            "Fruit": [
                "fruta", "fruit", "manzana", "apple", "platano", "banana",
                "naranja", "orange", "uva", "grape", "fresa", "strawberry",
            ],
            "Whole grains": [
                "arroz", "rice", "pasta", "avena", "oat", "pan integral",
                "whole", "integral", "quinoa",
            ],
            "Healthy fats": [
                "aceite", "oil", "aceitunas", "olive", "aguacate", "avocado",
                "nuez", "walnut", "almendra", "almond",
            ],
        }

        basket_text = " ".join(i["name"].lower() for i in basket)
        present  = [g for g, kws in groups.items() if any(k in basket_text for k in kws)]
        missing  = [g for g, kws in groups.items() if not any(k in basket_text for k in kws)]

        return (
            f"Present:  {', '.join(present) if present else 'none detected'}\n"
            f"Missing:  {', '.join(missing) if missing else 'none — good coverage!'}"
        )

    @tool
    def identify_ultra_processed() -> str:
        """Flag items that are likely ultra-processed (high sugar, refined, packaged snacks)."""
        ultra_kw = [
            "galleta", "cookie", "biscuit", "refresco", "soda", "cola",
            "patatas fritas", "chips", "snack", "bolleria", "pastry",
            "salchicha", "sausage", "nugget", "precocinado", "processed",
            "zumo", "juice", "cereales azucar", "energy drink",
        ]
        flagged = [
            i["name"] for i in basket
            if any(k in i["name"].lower() for k in ultra_kw)
        ]
        return (
            f"Ultra-processed items detected: {', '.join(flagged)}"
            if flagged else "No obvious ultra-processed items detected."
        )

    @tool
    def count_produce_variety() -> str:
        """Count distinct fruit and vegetable types in the basket."""
        produce_kw = [
            "tomate", "tomato", "lechuga", "lettuce", "zanahoria", "carrot",
            "espinaca", "spinach", "brocoli", "broccoli", "cebolla", "onion",
            "pimiento", "pepper", "calabacin", "courgette", "berenjena",
            "manzana", "apple", "platano", "banana", "naranja", "orange",
            "fresa", "strawberry", "uva", "grape", "pera", "pear",
            "limon", "lemon", "kiwi", "melon", "sandia", "watermelon",
        ]
        found = []
        for i in basket:
            name = i["name"].lower()
            for kw in produce_kw:
                if kw in name and kw not in found:
                    found.append(kw)
        return (
            f"{len(found)} produce variety/varieties found: {', '.join(found)}"
            if found else "No produce detected in basket."
        )

    @tool
    def search_healthier_alternative(product_name: str) -> str:
        """Search Mercadona for a healthier or fresher alternative to a specific product. Returns up to 3 options."""
        try:
            from core.shopping import _search_bilingual_scored
            candidates, _ = _search_bilingual_scored(product_name, top_k=3)
            if candidates.empty:
                return f"No alternatives found for '{product_name}' in Mercadona."
            lines = [f"Mercadona alternatives for '{product_name}':"]
            for _, row in candidates.iterrows():
                name  = str(row.get("name", ""))
                price = float(row.get("price", 0))
                unit  = str(row.get("unit", ""))
                lines.append(f"  - {name} ({unit}): €{price:.2f}")
            return "\n".join(lines)
        except Exception as e:
            return f"Search error: {e}"

    return [check_food_group_coverage, identify_ultra_processed, count_produce_variety, search_healthier_alternative]


# ══════════════════════════════════════════════════════════════════════════════
# System prompts
# ══════════════════════════════════════════════════════════════════════════════

_BUDGET_SYSTEM = """\
You are a frugal Budget Optimizer AI reviewing a grocery basket.
Your mandate: reduce cost without breaking the meal plan.

You have four tools:
- get_basket_cost_breakdown: see every item ranked by spend
- identify_overbuying: flag perishables bought in excess
- get_category_cost_split: see spend across protein / produce / pantry
- search_cheaper_alternative: look up real Mercadona products to find a cheaper swap

WORKFLOW:
1. Call get_basket_cost_breakdown to understand the full cost picture.
2. Call identify_overbuying to find waste.
3. Call get_category_cost_split to see where the money goes.
4. Call search_cheaper_alternative for the 1-2 most expensive items to find real Mercadona swaps.
5. Synthesise into EXACTLY 4-5 bullet points (• character) covering:
   • The 2 most expensive items — with a real Mercadona cheaper alternative and price
   • Any over-buying detected
   • Cost split verdict (is the balance sensible?)
   • One concrete "swap X for Y, save €Z" recommendation using actual Mercadona products
   • Overall verdict: cost-efficient / acceptable / over-budget

Rules: cite actual product names and prices. Under 200 words total."""

_NUTRITION_SYSTEM = """\
You are a certified Nutritionist AI reviewing a grocery basket.
Your mandate: maximise nutritional completeness and quality.

You have four tools:
- check_food_group_coverage: see which major food groups are present/missing
- identify_ultra_processed: flag unhealthy processed items
- count_produce_variety: count distinct fruits and vegetables
- search_healthier_alternative: look up real Mercadona products for a healthier substitute

WORKFLOW:
1. Call check_food_group_coverage to identify gaps.
2. Call identify_ultra_processed to flag poor choices.
3. Call count_produce_variety to assess diversity.
4. For any critical gap, call search_healthier_alternative to find a real Mercadona product that fills it.
5. Synthesise into EXACTLY 4-5 bullet points (• character) covering:
   • Protein quality and variety
   • Key nutritional gaps identified — with a real Mercadona product suggestion
   • Ultra-processed items to reduce
   • Produce variety score (aim for 5+ types)
   • One addition under €2 from Mercadona that most improves nutritional density

Rules: reference actual product names from Mercadona. Evidence-based only. Under 200 words."""

_MODERATOR_SYSTEM = """\
You are a neutral Moderator synthesising two specialist perspectives on a grocery basket.

You will receive:
- Budget Optimizer's argument
- Nutritionist's argument

Your job: write a balanced 3-bullet verdict that:
• Identifies where both agents AGREE (the clearest action items)
• Notes the key TRADE-OFF if they conflict (e.g. cheaper option is less nutritious)
• Gives ONE final recommendation that best balances cost and nutrition

Keep it under 100 words. Start directly with the bullets — no preamble."""

_BUDGET_CHAT_SYSTEM = """\
You are a frugal Budget Optimizer AI debating a grocery basket in a LIVE CHAT.

CRITICAL RULES:
1. If the conversation history shows you already gave a full basket analysis, DO NOT repeat it.
   Instead, answer the user's SPECIFIC question directly and concisely.
2. Only call tools when the user asks for NEW information not already covered.
3. Keep responses SHORT — 2-4 sentences or 2-3 bullets unless asked for more.
4. If you suggest a product swap, be SPECIFIC: name the product, approximate price, and why it saves money.

ACTIONS — if you suggest adding or swapping a Mercadona product, append this block at the
very end of your response (after a blank line):
---ACTIONS---
[{"type":"add","label":"Add <product name>","query":"<mercadona search term>"},
 {"type":"replace","label":"Replace <old> with <new>","remove":"<old product name>","query":"<new search term>"}]

You have tools: get_basket_cost_breakdown, identify_overbuying, get_category_cost_split, search_cheaper_alternative.
Only call them if the user's question requires information you don't already have."""

_NUTRITION_CHAT_SYSTEM = """\
You are a certified Nutritionist AI debating a grocery basket in a LIVE CHAT.

CRITICAL RULES:
1. If the conversation history shows you already gave a full nutritional analysis, DO NOT repeat it.
   Instead, answer the user's SPECIFIC question directly and concisely.
2. Only call tools when you need information not already provided in the conversation.
3. Keep responses SHORT — 2-4 sentences or 2-3 bullets unless asked for more.
4. If you suggest adding a product, be SPECIFIC: name the Mercadona product and its nutritional benefit.

ACTIONS — if you suggest adding or swapping a Mercadona product, append this block at the
very end of your response (after a blank line):
---ACTIONS---
[{"type":"add","label":"Add <product name>","query":"<mercadona search term>"},
 {"type":"replace","label":"Replace <old> with <new>","remove":"<old product name>","query":"<new search term>"}]

You have tools: check_food_group_coverage, identify_ultra_processed, count_produce_variety, search_healthier_alternative.
Only call them if the user's question requires fresh information."""

_MODERATOR_CHAT_SYSTEM = """\
You are a neutral Moderator in a live multi-agent debate about a grocery basket.
You participate alongside the Budget Optimizer and Nutritionist AI agents.

CRITICAL RULES:
1. If the conversation history shows a full analysis was already given, DO NOT repeat it.
   Synthesise and MOVE THE CONVERSATION FORWARD.
2. Answer the user's SPECIFIC question — don't just summarise what others said.
3. Keep responses SHORT: 2-4 sentences or 2-3 bullets.
4. When both agents agree on a swap, you may also suggest it with an ACTIONS block.

ACTIONS — if recommending a Mercadona product change, optionally append:
---ACTIONS---
[{"type":"add","label":"Add <product>","query":"<search term>"},
 {"type":"replace","label":"Replace <old> with <new>","remove":"<old>","query":"<new search>"}]

Never invent prices or product names — only use what the agents or tools have confirmed."""


# ══════════════════════════════════════════════════════════════════════════════
# Agent runner
# ══════════════════════════════════════════════════════════════════════════════

def _run_agent(system_prompt: str, tools: list, basket_text: str, api_key: str) -> str:
    """Run a single LangGraph ReAct agent and return its final response."""
    from langchain_groq import ChatGroq
    from langchain_core.messages import SystemMessage, HumanMessage
    from langgraph.prebuilt import create_react_agent

    from core.llm_config import build_llm
    llm   = build_llm(api_key.strip(), temperature=0.3)
    agent = create_react_agent(llm, tools=tools)

    messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=f"Here is the basket to analyse:\n\n{basket_text}\n\nBegin your analysis now."),
    ]

    try:
        result = agent.invoke({"messages": messages})
        return (result["messages"][-1].content or "").strip()
    except Exception as e:
        return f"(Agent error: {e})"


def _run_moderator(budget_arg: str, nutrition_arg: str, api_key: str) -> str:
    """Final moderator pass — synthesises both agents' arguments."""
    from langchain_groq import ChatGroq
    from langchain_core.messages import SystemMessage, HumanMessage

    from core.llm_config import build_llm
    llm = build_llm(api_key.strip(), temperature=0.2)
    msg = (
        f"BUDGET OPTIMIZER SAYS:\n{budget_arg}\n\n"
        f"NUTRITIONIST SAYS:\n{nutrition_arg}\n\n"
        "Give your balanced verdict now."
    )
    try:
        result = llm.invoke([SystemMessage(content=_MODERATOR_SYSTEM), HumanMessage(content=msg)])
        return (result.content or "").strip()
    except Exception as e:
        return f"(Moderator error: {e})"


# ══════════════════════════════════════════════════════════════════════════════
# Public API
# ══════════════════════════════════════════════════════════════════════════════

def debate_basket(items: list[dict], api_key: str) -> dict:
    """Run both agentic specialists + moderator against the basket.

    Returns::

        {
            "budget":    "<Budget Optimizer bullet-point argument>",
            "nutrition": "<Nutritionist bullet-point argument>",
            "verdict":   "<Moderator balanced synthesis>",
            "total":     12.34,
        }
    """
    basket = _parse_basket(items)
    total  = sum(i["price"] for i in basket)

    # Format basket as readable text for the agent messages
    basket_text = "\n".join(
        f"- {i['name']} × {i['count']} ({i['pack_size']}) = €{i['price']:.2f}"
        for i in basket
    ) + f"\n\nTotal: €{total:.2f}"

    # Build tools scoped to this basket
    budget_tools    = _make_budget_tools(basket)
    nutrition_tools = _make_nutrition_tools(basket)

    # Run both agents (sequential — avoids rate-limit spikes)
    budget_reply    = _run_agent(_BUDGET_SYSTEM,    budget_tools,    basket_text, api_key)
    nutrition_reply = _run_agent(_NUTRITION_SYSTEM, nutrition_tools, basket_text, api_key)

    # Moderator synthesises both
    verdict = _run_moderator(budget_reply, nutrition_reply, api_key)

    return {
        "budget":    budget_reply,
        "nutrition": nutrition_reply,
        "verdict":   verdict,
        "total":     round(total, 2),
    }


# ══════════════════════════════════════════════════════════════════════════════
# Multi-agent chat API  (single-turn, stateless — history injected as context)
# ══════════════════════════════════════════════════════════════════════════════

_AGENT_LABELS = {
    "budget":    "Budget Optimizer",
    "nutrition": "Nutritionist",
    "moderator": "Moderator",
}

_AGENT_SYSTEMS = {
    "budget":    _BUDGET_CHAT_SYSTEM,
    "nutrition": _NUTRITION_CHAT_SYSTEM,
    "moderator": _MODERATOR_CHAT_SYSTEM,
}


def run_agent_chat(
    agent_id: str,
    message: str,
    history: list[dict],
    groq_key: str,
    items: list[dict],
    basket_text: str,
) -> str:
    """Run one agent turn inside the multi-agent chat interface.

    Parameters
    ----------
    agent_id   : "budget" | "nutrition" | "moderator"
    message    : the current user message
    history    : list of ``{role, agent, content}`` dicts (all previous turns)
    groq_key   : Groq API key
    items      : raw shopping-list rows (needed to build basket-scoped tools)
    basket_text: pre-formatted basket string embedded in the prompt for context
    """
    from langchain_core.messages import SystemMessage, HumanMessage
    from core.llm_config import build_llm

    system_prompt = _AGENT_SYSTEMS.get(agent_id, _MODERATOR_CHAT_SYSTEM)
    llm = build_llm(groq_key.strip(), temperature=0.3)

    # Build conversation history as a readable context block so the agent
    # is aware of what other agents (and the user) have said previously.
    history_block = ""
    if history:
        lines = []
        for h in history:
            role    = h.get("role", "user")
            agent   = h.get("agent")
            content = h.get("content", "")
            if role == "user":
                lines.append(f"User: {content}")
            else:
                label = _AGENT_LABELS.get(agent, agent or "Agent")
                lines.append(f"{label}: {content}")
        history_block = (
            "\n\n--- CONVERSATION HISTORY ---\n"
            + "\n\n".join(lines)
            + "\n--- END OF HISTORY ---\n"
        )

    user_content = (
        f"Basket being analysed:\n\n{basket_text}"
        f"{history_block}\n"
        f"Current message from user: {message}"
    )

    if agent_id in ("budget", "nutrition"):
        from langgraph.prebuilt import create_react_agent

        basket = _parse_basket(items)
        tools = (
            _make_budget_tools(basket)
            if agent_id == "budget"
            else _make_nutrition_tools(basket)
        )
        agent = create_react_agent(llm, tools=tools)
        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_content),
        ]
        try:
            result = agent.invoke({"messages": messages})
            return (result["messages"][-1].content or "").strip()
        except Exception as e:
            return f"(Agent error: {e})"

    # Moderator — no tools, plain LLM call
    try:
        result = llm.invoke([
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_content),
        ])
        return (result.content or "").strip()
    except Exception as e:
        return f"(Moderator error: {e})"
