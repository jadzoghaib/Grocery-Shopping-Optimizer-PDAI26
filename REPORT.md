# GroceryAI — Prototyping Report
### From Shopping List Generator to Full-Stack Nutrition App

---

## What We Built

What started as a grocery shopping optimizer turned into something quite a bit more complete over this sprint. The app now handles the full nutrition loop — from figuring out what to eat, to finding where to buy it, to tracking what your body actually needs. It runs live on Render at:

🔗 **https://grocery-shopping-optimizer-pdai26.onrender.com**

Here's everything it does today:

| Feature | What it does |
|---|---|
| **Meal Planner** | Builds a weekly meal plan using linear programming (PuLP) against your calorie/macro targets, budget, and food preferences |
| **Smart Shopping List** | 3-step AI pipeline: consolidates ingredients → matches Mercadona products via TF-IDF → selects best SKU with LLM |
| **AI Chat Assistant** | ReAct agent that searches recipes and Mercadona products, adds items to your basket mid-conversation |
| **Nutrition Coach** | Calculates TDEE + macros (Mifflin-St Jeor), builds full weekly plans for keto / Mediterranean / IF / DASH / bulking & cutting |
| **Fridge Mode** | Type in what you have at home → get recipe suggestions that use those ingredients |
| **Body Optimizer** | Runs your meal plan against DRI nutrient tables, flags gaps, suggests supplements |
| **News Feed** | Pulls health & nutrition news, indexes it with Qdrant embeddings for semantic search |
| **Basket Debate** | Two AI agents — a budget optimizer and a nutritionist — argue about your shopping basket and a moderator gives a verdict |
| **Calendar Export** | Weekly meal plan → `.ics` file (Google Calendar, Outlook, Apple Calendar) |
| **History Tracker** | Logs every shopping run with per-item cost breakdown |

---

## What Changed This Sprint

### 1. LangGraph Agents — Proper ReAct Architecture

The biggest structural change was replacing the manual LLM loop with LangGraph's `create_react_agent`. Before this, every tool-calling flow was a hand-written `while` loop with a hard cap of 6 iterations. Now, LangGraph manages the state machine — the agent decides what tools to call and when, loops until it has an answer, and the code is roughly 80% shorter.

We did this for two separate agents:

**Grocery Chat Agent** (`services/rag.py`)  
Tools: `search_recipes`, `search_mercadona`. The agent chains these in whatever order makes sense for the question — "what's in a carbonara?" hits recipes first; "does Mercadona sell pancetta?" hits the product index directly.

**Nutrition Coach Agent** (`services/nutrition_agent.py`) — *new*  
Tools: `calculate_macros` (deterministic Mifflin-St Jeor math), `lookup_food` (local USDA nutrition table), `search_nutrition_knowledge` (TF-IDF over nutrition reference docs). Ask it "I'm 80 kg, 180 cm, 28 years old, moderately active, want to cut" and it'll compute your TDEE, give you daily targets, and build a full weekly meal plan with per-meal macros.

```
User message
    ↓
[LangGraph ReAct loop]
    ↓
  Agent → calls tool(s) → gets results → loops if needed
    ↓
  Final response + optional JSON payload (basket items / meal plan)
    ↓
FastAPI returns to frontend
```

---

### 2. Shopping Pipeline — Robustness Layers

The old shopping pipeline failed silently. If Groq returned broken JSON or hallucinated a product name, the UI just got nothing. We added four cooperating layers that run on every LLM call:

- **Pydantic v2 schema validation** — strict models for both Pass 1 (consolidation) and Pass 3 (SKU selection). Bad JSON raises immediately and routes to the fallback.
- **Runtime guards** — checks for hallucinated SKUs (is the chosen product actually in the candidate list?), price math (`packs × unit_price ≈ total_price`), and a deterministic `match_quality` classifier that cross-checks the LLM's self-reported tag.
- **Rule-based fallbacks** — pure Python: if Groq fails on any item, that item gets handled with regex pack-size extraction and TF-IDF top-1 selection. The rest of the list is unaffected.
- **Structured logging** — every call is saved to `data/llm_logs/shopping_<date>.jsonl` with a content-addressed cache keyed by `sha256(model + "\n" + prompt)`. Same prompt never hits the API twice.

The UI now renders match quality visually:  
🟢 exact match → normal row  
🔴 substitute → red tint + `ⓘ` hover tooltip with the reason  
🟡 not available → amber row  

---

### 3. Groq Key Rotation Pool

Since the whole app runs on Groq's free tier, rate limits were a constant issue. The fix was a pool of 4 API keys (`GROQ_API_KEY` through `GROQ_API_KEY_4`) with automatic rotation logic in `core/groq_client.py`:

- On a `429` (rate limit) → that key goes on a 60-second cooldown, next key takes over immediately
- On a `401` (invalid key) → 1-hour cooldown
- If all keys are exhausted → deterministic fallback path kicks in
- Users can optionally supply their own key in the Settings panel; it always takes priority over the pool

---

### 4. Deployment on Render (512 MB Free Tier)

Getting the app to run on Render's free tier was the most painful part of this sprint. The issue: `import` statements at the top of files in Python execute at module load time. With a stack this size — LangGraph, langchain-core, scikit-learn, Dash/Plotly — loading everything at startup consumed more than 512 MB before uvicorn could even open a socket. Render kept reporting "No open ports detected."

The fix was **lazy imports** — every heavy package was moved inside the function that actually needs it:

```python
# Before (loads at server startup — OOM):
from langgraph.prebuilt import create_react_agent

# After (loads on first request only):
def _build_agent(api_key):
    from langgraph.prebuilt import create_react_agent
    ...
```

We applied this to six places: `services/rag.py`, `services/nutrition_agent.py`, `core/shopping.py`, `core/optimizer.py`, and gated the Dash/Plotly mount in `server.py` behind `DISABLE_DASH=1`. The server now starts in under 3 seconds and loads heavy packages on demand.

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              Browser (SPA)                                   │
│   Dashboard · Meal Planner · Basket · Nutrition · Fridge · Body · News       │
└─────────────────────────────┬───────────────────────────────────────────────┘
                              │  REST / JSON
┌─────────────────────────────▼───────────────────────────────────────────────┐
│                         FastAPI  (server.py)                                 │
│  /api/meal-plan   /api/shopping-list   /api/chat   /api/nutrition-chat       │
│  /api/fridge      /api/body           /api/news    /api/debate               │
└──────┬─────────┬──────────┬──────────┬─────────────┬──────────┬─────────────┘
       │         │          │          │             │          │
  PuLP LP    3-pass LLM  Grocery   Nutrition     News RAG   Debate
  optimizer  + guards    ReAct     ReAct         (Qdrant +  (2 agents
  (meal plan) (shopping) Agent     Agent         HuggingFace + moderator)
                          │          │            embeddings)
                     search_recipes  calculate_macros
                     search_mercadona lookup_food
                          │          search_nutrition_knowledge
                     TF-IDF index
                     (scikit-learn)

                    ┌──────────────────────────────────┐
                    │     Groq Key Rotation Pool        │
                    │  Key 1 → Key 2 → Key 3 → Key 4   │
                    │  429/401 → cooldown → next key    │
                    │  All fail → rule-based fallback   │
                    └──────────────────────────────────┘
```

---

## What We'd Like to Do Next

The original plan included a fine-tuned model from Hugging Face as an alternative backend for the nutrition coach — something domain-specific that would give better dietary advice than a general-purpose LLM. We had the architecture wired up (the same key-rotation pattern would work for HF endpoints), but **the HuggingFace Inference API free trial expired before we could test it properly**. That's the honest reason it's not in there.

Beyond that, the backlog includes:
- Persistent user profiles (body stats, allergies, goals) stored server-side instead of browser localStorage
- Upgrading the nutrition knowledge base retrieval from TF-IDF to proper sentence embeddings
- A mobile-optimised layout (the sidebar collapses, but it's still clearly desktop-first)
- An evaluation harness for the nutrition agent similar to what we built for the shopping pipeline (`eval/run_eval.py`)

---

*Built with FastAPI · LangGraph · Groq llama-3.3-70b-versatile · scikit-learn · PuLP · Qdrant*  
*Deployed on Render — https://grocery-shopping-optimizer-pdai26.onrender.com*
