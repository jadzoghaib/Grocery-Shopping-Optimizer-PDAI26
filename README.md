
# GroceryAI — Full-Stack Nutrition & Shopping App

![Python](https://img.shields.io/badge/Python-3.11-blue.svg)
![FastAPI](https://img.shields.io/badge/FastAPI-0.100+-green.svg)
![LangGraph](https://img.shields.io/badge/Agents-LangGraph-blueviolet.svg)
![LLM](https://img.shields.io/badge/LLM-Groq%20llama--3.3--70b-orange.svg)
![Deploy](https://img.shields.io/badge/Deploy-Render-purple.svg)

An end-to-end nutrition and grocery management app. It handles meal planning, AI-powered shopping list generation against real Mercadona supermarket data, a nutrition coaching agent, a fridge-to-recipe engine, body optimizer, health news feed, and a multi-agent basket debate — all in one SPA backed by a FastAPI server.

🔗 **Live demo: https://grocery-shopping-optimizer-pdai26.onrender.com**

---

## Quick Start

```bash
pip install -r requirements.txt
python server.py
```

Open **http://localhost:8000**. Add your Groq key in the **Settings** panel (gear icon) or set `GROQ_API_KEY` in your environment.

---

## Features

### 🍽️ Meal Plan Optimizer
Linear programming (PuLP) builds a weekly meal plan that hits your calorie / macro targets within budget. Set daily goals per person, exclude disliked ingredients, pick cuisine preferences, and choose a variability mode (High = unique meals every day, Low = batch cooking). Rate meals thumbs-up / thumbs-down — ratings shift future plan generation.

### 🛒 Smart Shopping List — 3-Pass AI Pipeline

```
Meal plan ingredients
        ↓
  Pass 1 — Groq LLM
  Consolidate duplicates,
  normalise units to g/ml/count
        ↓
  Pass 2 — TF-IDF (scikit-learn)
  Retrieve top-5 Mercadona SKU
  candidates per ingredient
  (bilingual EN→ES fallback)
        ↓
  Pass 3 — Groq LLM
  Pick best SKU, infer pack size,
  compute packs needed + total cost
  + match_quality tag
        ↓
  Shopping list DataFrame
  (exact / alternative / none)
```

Every LLM call is wrapped with **Pydantic v2 validation**, **runtime guards** (hallucination check, price consistency, pack sizing), a **rule-based fallback** for failing items, and a **content-addressed JSONL cache** (`sha256(model + prompt)` → `data/llm_logs/cache/`).

The UI renders match quality visually:
| `match_quality` | Rendering |
|---|---|
| `exact` | normal row |
| `alternative` | red tint + `ⓘ` hover showing the LLM's substitution reason |
| `none` | amber tint — item unavailable at Mercadona |

### 🤖 Grocery Chat Assistant (LangGraph ReAct)
Conversational agent backed by `create_react_agent`. It decides autonomously when to call `search_recipes` or `search_mercadona`, chains multiple tool calls in one turn if needed, and can add Mercadona products directly to your basket from inside the chat.

### 🥗 Nutrition Coach (LangGraph ReAct) — *new*
Separate specialist agent at `#/nutrition`. Tools:
- **`calculate_macros`** — Mifflin-St Jeor TDEE + goal-adjusted macro targets (lose / maintain / gain)
- **`lookup_food`** — local USDA-derived nutrition table (~500 foods, kcal/protein/carbs/fat per 100 g)
- **`search_nutrition_knowledge`** — TF-IDF search over nutrition reference docs in `data/nutrition_kb/`

Covers macro targets, specific diet programs (keto, Mediterranean, IF, DASH, bulking, cutting), and full weekly meal plan generation with per-day macro breakdown. Produced meal plans can be imported directly into the Meal Planner.

### 🧊 Fridge Mode
Type your available ingredients → TF-IDF matches against the recipe database. If a strong match is found it returns database recipes; otherwise it generates a new recipe via Groq. No wasted groceries.

### 💪 Body Optimizer
Runs your active meal plan against Dietary Reference Intakes (DRI) for 20+ micronutrients. Flags deficiencies, suggests specific supplements ranked by gap severity. Separate Groq-powered coach chat for personalised advice.

### 📰 Health News RAG
Fetches health & nutrition news, embeds articles with `sentence-transformers` (HuggingFace), stores them in Qdrant, and exposes a semantic search endpoint. The news scheduler runs every 6 hours in the background (gated by `DISABLE_NEWS_SCHEDULER=1` for memory-constrained deployments).

### ⚖️ Basket Debate (Multi-Agent)
Two LangGraph ReAct agents analyse your shopping basket from opposite angles:
- **Budget Optimizer** — minimises cost, flags overpriced items
- **Nutritionist** — evaluates macro coverage and ingredient quality
- **Moderator LLM** — reads both arguments and produces a balanced verdict

### 🗓️ Calendar & History
One-click `.ics` export to Google Calendar / Outlook / Apple Calendar. Full purchase history with per-order cost breakdown and spending-over-time chart (Plotly).

### 📚 Recipe Forum
Submit your own recipes with macros and instructions. User-submitted recipes are prioritised in the meal plan optimizer.

---

## Groq Key Rotation Pool

The app supports up to 4 Groq API keys for automatic rate-limit failover. Set them as environment variables:

```
GROQ_API_KEY=gsk_...
GROQ_API_KEY_2=gsk_...
GROQ_API_KEY_3=gsk_...
GROQ_API_KEY_4=gsk_...
```

Rotation logic (`core/groq_client.py`):
- `429` (rate limit) → key goes on **60-second cooldown**, next key takes over
- `401` (invalid key) → **1-hour cooldown**
- All keys exhausted → deterministic rule-based fallback path
- User-supplied key from the Settings panel always takes priority over the pool

---

## Architecture

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
└──────┬─────────┬──────────┬───────────┬────────────┬─────────────┬──────────┘
       │         │          │           │            │             │
  PuLP LP    3-pass LLM  Grocery    Nutrition     News RAG     Debate
  optimizer  pipeline    ReAct      ReAct         Qdrant +     2 agents
  (core/     (core/      Agent      Agent         HuggingFace  + moderator
  optimizer) shopping)  (rag.py)  (nutrition_    embeddings   (debate.py)
                                   agent.py)    (news_rag.py)
                            │          │
                       TF-IDF index   calculate_macros
                       recipes +      lookup_food
                       Mercadona      search_nutrition_knowledge

                    ┌──────────────────────────────────┐
                    │     Groq Key Rotation Pool        │
                    │  Key 1 → Key 2 → Key 3 → Key 4   │
                    │  429/401 → cooldown → next key    │
                    │  All fail → rule-based fallback   │
                    └──────────────────────────────────┘
```

---

## Technology Stack

| Layer | Technology |
|---|---|
| **Web framework** | FastAPI + uvicorn |
| **Frontend** | Vanilla HTML / CSS / JavaScript (SPA, dark theme) |
| **Optimization** | PuLP (linear programming) |
| **Product search** | scikit-learn TF-IDF + cosine similarity |
| **LLM provider** | Groq `llama-3.3-70b-versatile` — all pipelines |
| **Agent framework** | LangGraph `create_react_agent` (grocery chat + nutrition + debate) |
| **Schema validation** | Pydantic v2 (shopping pipeline) |
| **Vector store** | Qdrant (news RAG) |
| **Embeddings** | `sentence-transformers` via HuggingFace (news indexing) |
| **Analytics** | Plotly Dash — meal plan, shopping, history dashboards |
| **Data** | Food.com recipes (~5 900 rows), Mercadona live API (7-day cache) |
| **Deployment** | Render (`render.yaml` included) |

---

## Deploy on Render

1. Push the repo to GitHub.
2. Create a **Web Service** on [render.com](https://render.com), connect the repo — `render.yaml` handles the rest.
3. Add these environment variables in the Render dashboard:

| Variable | Purpose |
|---|---|
| `GROQ_API_KEY` | Required — primary Groq key |
| `GROQ_API_KEY_2/3/4` | Optional — rotation pool keys |
| `DISABLE_NEWS_SCHEDULER` | Set to `1` on free tier to skip HuggingFace embedding model at startup |
| `DISABLE_DASH` | Set to `1` on free tier to skip Dash/Plotly (~150 MB) at startup |

> **Free-tier note:** The app uses lazy imports for all heavy packages (langchain, sklearn, Dash/Plotly) so that uvicorn can bind its port before loading them. Startup RAM is well under 512 MB; heavy packages load on the first request that needs them.

---

## Project Structure

```
server.py                      ← FastAPI entry point + all route handlers
core/
  optimizer.py                 ← PuLP linear programming meal planner
  shopping.py                  ← 3-pass LLM shopping pipeline (LangGraph StateGraph)
  shopping_schemas.py          ← Pydantic v2 models for LLM outputs
  shopping_guards.py           ← Runtime validation guards
  shopping_fallback.py         ← Rule-based fallback (no LLM)
  shopping_logger.py           ← JSONL logging + content-addressed cache
  groq_client.py               ← 4-key rotation pool with cooldown logic
  llm_config.py                ← Pinned model IDs + decoding params
  data.py                      ← Recipe & Mercadona data loading
  config.py                    ← Cuisine map, recipe filters
services/
  rag.py                       ← Grocery ReAct agent (LangGraph)
  nutrition_agent.py           ← Nutrition coach ReAct agent (LangGraph)
  nutrition_tools.py           ← calculate_macros, lookup_food, search_nutrition_knowledge
  debate.py                    ← Multi-agent basket debate (LangGraph)
  fridge.py                    ← Fridge-to-recipe engine (TF-IDF + Groq fallback)
  body.py                      ← Nutrient gap analysis + supplement recommendations
  news_rag.py                  ← Qdrant-backed news semantic search
  news_scheduler.py            ← APScheduler background news ingest
  retrieval.py                 ← Multi-source retrieval (recipes, YouTube, web)
static/
  index.html                   ← SPA shell
  css/style.css                ← Dark theme UI
  js/app.js                    ← Frontend application (~3 000 lines, SPA routing)
data/
  recipes.csv                  ← Food.com recipe dataset
  mercadona_cache.csv          ← 7-day Mercadona product cache
  nutrition_kb/foods.csv       ← USDA-derived food nutrition table
  user_recipes.json            ← User-submitted recipes
eval/
  run_eval.py                  ← Eval harness (live + replay modes)
  ground_truth/                ← 180 hand-labelled examples (Pass 1 + Pass 3)
render.yaml                    ← Render deployment config
```

---

## Evaluation & Reproducibility

The shopping pipeline has a full eval harness:

```bash
# Collection pass — talks to Groq, caches responses
python -m eval.run_eval --mode live --out eval/results/$(date +%F)/

# Replay pass — fully offline, zero API credits
python -m eval.run_eval --mode replay --out eval/results/$(date +%F)/
```

Outputs `metrics.json` (Wilson 95% CIs + dataset SHA-256) and `report.md` (Raw LLM vs Post-fallback vs Baseline, top-10 failures, match_quality confusion matrix). Exit code `2` on regression below `--threshold-top1` (default 0.70) for CI gating.

