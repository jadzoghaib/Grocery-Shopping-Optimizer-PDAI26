"""FastAPI backend — wraps existing core logic for the modern web UI."""

import asyncio
import os
import json
import traceback

# Load .env before anything else (no-op if the file doesn't exist)
from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI, Query
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel
import uvicorn

# ── Core imports ──────────────────────────────────────────────────────────────
# NOTE: Heavy packages (Dash/Plotly, langgraph, sklearn) are imported lazily
# so that uvicorn can bind its port before loading them (Render free-tier OOM fix).
from core.config import CUISINE_MAP
from core.data import load_recipe_data, load_mercadona_db
# core.optimizer (numpy+pulp) and core.shopping (langgraph) are imported lazily
# inside the route handlers that need them — see _get_optimizer() / _get_shopping().
from core.groq_client import groq_with_rotation, resolve_key, pool_status, make_groq_client
from services.rag import rag_answer, parse_basket_intent, search_products
from services.nutrition_agent import nutrition_answer, parse_nutrition_plan
from services.fridge import fridge_suggest
from services.debate import debate_basket, run_agent_chat
from services.body import (fetch_health_news, analyze_nutrients, get_supplement_gaps,
                           NUTRIENT_META, estimate_extended_nutrients, body_coach_chat)
from services.news_rag import query_news, get_ingestion_status, ingest_news_articles, get_trends
from services.news_scheduler import start_scheduler, stop_scheduler

# dashboards.cache is a plain dict — always safe to import.
from dashboards import cache as dash_cache

# Dash + Plotly (dashboards.app) are very heavy (~150 MB).
# Set DISABLE_DASH=1 on memory-constrained deployments (e.g. Render free tier).
_DASH_ENABLED = not os.environ.get("DISABLE_DASH")
if _DASH_ENABLED:
    try:
        from dashboards.app import dash_app
        from a2wsgi import WSGIMiddleware
    except Exception as _dash_err:
        print(f"[server] Dash disabled (import error): {_dash_err}")
        _DASH_ENABLED = False

_DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")

# ── App ───────────────────────────────────────────────────────────────────────

app = FastAPI(title="Grocery Shopping Optimizer")


@app.on_event("startup")
async def _startup():
    # Inject the API key into env so the scheduler's CAG preprocessing step can use it
    groq_key = os.environ.get("GROQ_API_KEY", "")
    if groq_key:
        os.environ["GROQ_API_KEY"] = groq_key
    # Skip heavy news scheduler on memory-constrained environments (e.g. Render free tier)
    if not os.environ.get("DISABLE_NEWS_SCHEDULER"):
        start_scheduler()   # begins 60-second-delayed first ingest (RAG + CAG), then every 6 h

    # Pre-warm the recipe/Mercadona cache in a background thread so the first
    # meal-plan request is instant (instead of waiting for a cold Mercadona crawl).
    import threading
    def _prewarm():
        try:
            from core.data import load_recipe_data
            load_recipe_data()
        except Exception:
            pass
    threading.Thread(target=_prewarm, daemon=True).start()


@app.on_event("shutdown")
async def _shutdown():
    stop_scheduler()


# ── Request models ────────────────────────────────────────────────────────────

class MealPlanRequest(BaseModel):
    calories: float = 2000
    protein: float = 100
    carbs: float = 250
    fat: float = 65
    budget: float = 50
    max_time: int = 60
    dislikes: str = ""
    days: int = 7
    slots: list = ["Breakfast", "Lunch", "Snack", "Dinner"]
    cuisines: list = []
    people: int = 1
    variability: str = "High"


class ShoppingListRequest(BaseModel):
    items: list
    groq_key: str
    people: int = 1


class ChatRequest(BaseModel):
    message: str
    history: list = []
    api_key: str


class NutritionChatRequest(BaseModel):
    message: str
    history: list = []
    api_key: str


class FridgeRequest(BaseModel):
    ingredients: list[str]
    api_key: str


class HistorySyncRequest(BaseModel):
    history: list   # list of history session dicts from localStorage


class RecipeSubmit(BaseModel):
    name: str
    category: str = "Main Dish"
    ingredients: str = ""
    instructions: str = ""
    calories: float = 400
    protein: float = 25
    carbs: float = 40
    fat: float = 15
    prep_time: int = 30
    rating: float = 4.0
    source_url: str = ""


class RatingUpdate(BaseModel):
    recipe_name: str
    delta: float = 0.25


class SwapSuggestRequest(BaseModel):
    slot: str = "Lunch"          # Breakfast / Lunch / Dinner / Snack / Dessert
    calories: float = 400        # calorie target for proximity sort
    exclude: str = ""            # current recipe name to exclude


class PackFeedbackRequest(BaseModel):
    ingredient: str
    sku: str = ""
    vote: str  # "up" or "down"


class DebateRequest(BaseModel):
    items: list   # list of shopping-list row dicts
    api_key: str


class DebateChatRequest(BaseModel):
    agents: list[str]   # e.g. ["budget", "nutrition", "moderator"]
    message: str
    history: list = []  # [{role, agent, content}, ...]
    items: list = []    # shopping-list rows (for basket-scoped tools)
    api_key: str


class BodyAnalyzeRequest(BaseModel):
    meal_plan: list = []   # meal plan records from localStorage
    measurements: dict = {}  # {sex, age, weight_kg, height_cm, activity}


class BodyEstimateNutrientsRequest(BaseModel):
    meal_plan: list = []
    api_key: str = ""


class BodyCoachChatRequest(BaseModel):
    message: str
    history: list = []           # [{role, content}, ...]
    profile: dict = {}           # {sex, age, weight_kg, height_cm, activity}
    nutrient_data: dict = {}     # output of analyze_nutrients()
    supplements: list = []       # output of get_supplement_gaps()
    api_key: str = ""


class NewsQueryRequest(BaseModel):
    question: str
    api_key: str


# ── Helpers ───────────────────────────────────────────────────────────────────

def _load_json(name: str) -> dict | list:
    path = os.path.join(_DATA_DIR, name)
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {} if "rating" in name else []


def _save_json(name: str, data):
    path = os.path.join(_DATA_DIR, name)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def _df_to_records(df):
    """Convert DataFrame to JSON-safe list of dicts."""
    import pandas as pd
    if df is None or (isinstance(df, pd.DataFrame) and df.empty):
        return []
    records = df.to_dict(orient="records")
    for rec in records:
        for k, v in rec.items():
            if isinstance(v, float) and (v != v):  # NaN check
                rec[k] = None
    return records


# ── Routes ────────────────────────────────────────────────────────────────────

@app.get("/")
async def index():
    return FileResponse("static/index.html")


@app.get("/api/config")
async def get_config():
    status = pool_status()
    return {
        "cuisine_map": CUISINE_MAP,
        "default_slots": ["Breakfast", "Lunch", "Snack", "Dinner"],
        "variability_options": ["Low", "Medium", "High"],
        "groq_key": os.environ.get("GROQ_API_KEY", ""),
        # Let the frontend know server-side keys are available
        "server_keys_available": status["available"],
        "server_keys_total": status["total_keys"],
    }


@app.get("/api/groq-pool")
async def groq_pool_status():
    """Debug endpoint — shows key pool health without exposing key values."""
    return {"ok": True, **pool_status()}


@app.get("/api/memory")
async def memory_usage():
    """Report current process RSS memory usage (reads /proc/self/status on Linux)."""
    import sys
    try:
        # Linux: read VmRSS from /proc/self/status (no extra deps)
        rss_kb = None
        with open("/proc/self/status") as f:
            for line in f:
                if line.startswith("VmRSS:"):
                    rss_kb = int(line.split()[1])
                    break
        if rss_kb is not None:
            rss_mb = round(rss_kb / 1024, 1)
            return {
                "ok": True,
                "rss_mb": rss_mb,
                "limit_mb": 512,
                "used_pct": round(rss_mb / 512 * 100, 1),
                "headroom_mb": round(512 - rss_mb, 1),
                "disable_dash": bool(os.environ.get("DISABLE_DASH")),
                "disable_news_scheduler": bool(os.environ.get("DISABLE_NEWS_SCHEDULER")),
            }
    except Exception:
        pass
    # Fallback: use sys for a rough estimate
    return {"ok": False, "error": "Could not read /proc/self/status (non-Linux?)"}


@app.post("/api/meal-plan/generate")
async def generate_meal_plan(req: MealPlanRequest):
    try:
        import pandas as pd

        # Capture request values for use inside the executor thread
        _req = req

        def _run_plan():
            """All blocking work: data load + DataFrame merge + ILP — runs in thread pool."""
            df = load_recipe_data()
            ratings = _load_json("rating_adjustments.json")
            user_recipes = _load_json("user_recipes.json")

            if user_recipes:
                udf = pd.DataFrame(user_recipes)
                for col in ["calories", "protein", "carbs", "fat", "cost", "prep_time"]:
                    if col in udf.columns:
                        udf[col] = pd.to_numeric(udf[col], errors="coerce").fillna(0)
                if "AggregatedRating" not in udf.columns:
                    udf["AggregatedRating"] = pd.to_numeric(udf.get("rating"), errors="coerce").fillna(4.5)
                if "Keywords" not in udf.columns:
                    udf["Keywords"] = "user input"
                if "RecipeCategory" not in udf.columns:
                    udf["RecipeCategory"] = udf.get("category", "Main Dish")
                if "cost" not in udf.columns:
                    udf["cost"] = 5.0
                if "prep_time" not in udf.columns:
                    udf["prep_time"] = 30
                if "ingredients" not in udf.columns:
                    udf["ingredients"] = ""
                df = pd.concat([df, udf], ignore_index=True)

            from core.optimizer import optimize_meal_plan  # lazy — numpy+pulp
            return optimize_meal_plan(
                df,
                target_calories=_req.calories * _req.people,
                target_protein=_req.protein * _req.people,
                target_carbs=_req.carbs * _req.people,
                target_fat=_req.fat * _req.people,
                max_budget=_req.budget * _req.days if _req.budget else None,
                max_time=_req.max_time,
                dislikes=_req.dislikes,
                days=_req.days,
                selected_slots=_req.slots,
                cuisine_prefs=_req.cuisines if _req.cuisines else None,
                cuisine_map=CUISINE_MAP,
                people_count=_req.people,
                variability=_req.variability,
                rating_adjustments=ratings if ratings else None,
            )

        loop = asyncio.get_event_loop()
        result, message = await loop.run_in_executor(None, _run_plan)

        if result is None:
            return {"ok": False, "error": message}

        records = _df_to_records(result)
        # Compute nutrition summary
        totals = {"calories": 0, "protein": 0, "carbs": 0, "fat": 0, "cost": 0}
        day_count = 0
        for r in records:
            if r.get("Day") == "Day 1":
                for k in totals:
                    totals[k] += float(r.get(k) or 0)
                day_count += 1

        # Cache for Dash dashboards
        dash_cache.store("meal_plan", records)
        dash_cache.store("plan_targets", {
            "calories": req.calories, "protein": req.protein,
            "carbs": req.carbs, "fat": req.fat, "budget": req.budget,
        })

        return {"ok": True, "meal_plan": records, "nutrition": totals}

    except Exception as e:
        traceback.print_exc()
        return {"ok": False, "error": str(e)}


@app.post("/api/meal-plan/suggestions")
async def meal_swap_suggestions(req: SwapSuggestRequest):
    """Return up to 5 alternative recipes for a given meal slot + calorie target."""
    try:
        import pandas as pd, json, os

        df = load_recipe_data()
        user_recipes = _load_json("user_recipes.json")
        if user_recipes:
            udf = pd.DataFrame(user_recipes)
            for col in ["calories", "protein", "carbs", "fat", "cost", "prep_time"]:
                if col in udf.columns:
                    udf[col] = pd.to_numeric(udf[col], errors="coerce").fillna(0)
            if "AggregatedRating" not in udf.columns:
                udf["AggregatedRating"] = pd.to_numeric(udf.get("rating"), errors="coerce").fillna(4.0)
            if "RecipeCategory" not in udf.columns:
                udf["RecipeCategory"] = udf.get("category", pd.Series("Main Dish", index=udf.index))
            if "Keywords" not in udf.columns:
                udf["Keywords"] = ""
            df = pd.concat([df, udf], ignore_index=True)

        cats  = df.get("RecipeCategory", pd.Series("", index=df.index)).fillna("").str.lower()
        names = df.get("name",           pd.Series("", index=df.index)).fillna("").str.lower()
        keys  = df.get("Keywords",       pd.Series("", index=df.index)).fillna("").str.lower()

        slot = req.slot.lower()
        if "breakfast" in slot:
            bkws = "breakfast|oatmeal|pancake|waffle|toast|omelet|egg|cereal|granola|yogurt|frittata|quiche|bagel|muffin"
            mask = cats.str.contains("breakfast|oatmeal|pancake|waffle|egg", na=False) \
                 | names.str.contains(bkws, na=False) \
                 | keys.str.contains("breakfast|brunch", na=False)
        elif "snack" in slot:
            mask = cats.str.contains("snack|fruit|berries|nuts|spreads", na=False) \
                 | names.str.contains("snack|appetizer|dip|bites", na=False) \
                 | keys.str.contains("snack|appetizer", na=False)
        elif "dessert" in slot:
            mask = cats.str.contains("dessert|frozen dessert|pie|cookie|candy|cheesecake|gelatin", na=False) \
                 | names.str.contains("dessert|cake|cookie|brownie|pudding|ice cream|chocolate", na=False)
        else:
            # lunch / dinner / main
            excl = cats.str.contains("breakfast|pancake|waffle|oatmeal|dessert|cookie|candy|beverage", na=False) \
                 | names.str.contains("pancake|waffle|cereal|oatmeal", na=False)
            mask = ~excl

        filtered = df[mask].copy()
        if req.exclude:
            filtered = filtered[filtered["name"].fillna("").str.lower() != req.exclude.lower()]

        filtered["_cal_diff"] = (
            pd.to_numeric(filtered["calories"], errors="coerce").fillna(0) - req.calories
        ).abs()
        filtered["_rating"] = pd.to_numeric(
            filtered.get("AggregatedRating", filtered.get("rating", 0)), errors="coerce"
        ).fillna(0)
        filtered = filtered.sort_values(["_cal_diff", "_rating"], ascending=[True, False])

        keep_cols = ["name", "calories", "protein", "carbs", "fat", "cost",
                     "prep_time", "RecipeCategory", "AggregatedRating",
                     "ingredients", "instructions", "source_url"]
        available = [c for c in keep_cols if c in filtered.columns]
        top = filtered.head(5)[available].fillna("").to_dict(orient="records")
        return {"ok": True, "suggestions": top}
    except Exception as e:
        traceback.print_exc()
        return {"ok": False, "error": str(e)}


@app.get("/api/recipes/search")
async def search_recipes_by_name(q: str = Query("", alias="q")):
    """Case-insensitive name search across all recipes (dataset + user)."""
    try:
        import pandas as pd

        df = load_recipe_data()
        user_recipes = _load_json("user_recipes.json")
        if user_recipes:
            udf = pd.DataFrame(user_recipes)
            if "AggregatedRating" not in udf.columns:
                udf["AggregatedRating"] = pd.to_numeric(udf.get("rating"), errors="coerce").fillna(4.0)
            if "RecipeCategory" not in udf.columns:
                udf["RecipeCategory"] = udf.get("category", pd.Series("Main Dish", index=udf.index))
            df = pd.concat([df, udf], ignore_index=True)

        if not q.strip():
            return {"ok": True, "results": []}

        mask = df["name"].fillna("").str.lower().str.contains(q.lower().strip(), na=False)
        matched = df[mask].copy()
        matched["_rating"] = pd.to_numeric(
            matched.get("AggregatedRating", matched.get("rating", 0)), errors="coerce"
        ).fillna(0)
        matched = matched.sort_values("_rating", ascending=False)

        keep_cols = ["name", "calories", "protein", "carbs", "fat", "cost",
                     "prep_time", "RecipeCategory", "AggregatedRating",
                     "ingredients", "instructions", "source_url"]
        available = [c for c in keep_cols if c in matched.columns]
        results = matched.head(10)[available].fillna("").to_dict(orient="records")
        return {"ok": True, "results": results}
    except Exception as e:
        traceback.print_exc()
        return {"ok": False, "error": str(e)}


@app.post("/api/shopping-list/generate")
async def generate_shopping_list(req: ShoppingListRequest):
    try:
        from core.shopping import optimize_shopping_list_groq  # lazy — langgraph
        client = make_groq_client(resolve_key(req.groq_key))
        result = optimize_shopping_list_groq(req.items, client, people_count=req.people)
        records = _df_to_records(result)
        dash_cache.store("shopping", records)   # cache for Dash
        return {"ok": True, "shopping_list": records}
    except Exception as e:
        traceback.print_exc()
        return {"ok": False, "error": str(e)}


@app.get("/api/mercadona/search")
async def search_mercadona(q: str = Query(...), top_k: int = Query(10)):
    try:
        df = search_products(q, top_k=top_k, min_score=0.05)
        # Bilingual fallback: Mercadona products are in Spanish, so English queries
        # (e.g. "chicken") get zero TF-IDF scores. Try the Spanish translation.
        if df.empty:
            from core.ingredient_translations import ENGLISH_TO_SPANISH
            spanish = ENGLISH_TO_SPANISH.get(q.lower().strip())
            if spanish:
                df = search_products(spanish, top_k=top_k, min_score=0.05)
        # Last resort: very low threshold so at least something comes back
        if df.empty:
            df = search_products(q, top_k=top_k, min_score=0.01)
        return {"ok": True, "products": _df_to_records(df)}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@app.post("/api/chat")
async def chat(req: ChatRequest):
    try:
        reply = rag_answer(
            question=req.message,
            messages_history=req.history,
            api_key=resolve_key(req.api_key),
        )
        display, basket_items = parse_basket_intent(reply)
        return {"ok": True, "reply": display, "basket_items": basket_items}
    except Exception as e:
        traceback.print_exc()
        return {"ok": False, "error": str(e)}


@app.post("/api/history/sync")
async def sync_history(req: HistorySyncRequest):
    """Receive history from frontend localStorage and cache it for Dash dashboards."""
    dash_cache.store("history", req.history)
    return {"ok": True}


@app.post("/api/fridge/suggest")
async def fridge_suggest_endpoint(req: FridgeRequest):
    try:
        result = fridge_suggest(req.ingredients, resolve_key(req.api_key))
        return {"ok": True, **result}
    except Exception as e:
        traceback.print_exc()
        return {"ok": False, "error": str(e)}


@app.post("/api/nutrition-chat")
async def nutrition_chat(req: NutritionChatRequest):
    try:
        reply = nutrition_answer(
            question=req.message,
            messages_history=req.history,
            api_key=resolve_key(req.api_key),
        )
        display, plan = parse_nutrition_plan(reply)
        return {"ok": True, "reply": display, "nutrition_plan": plan}
    except Exception as e:
        traceback.print_exc()
        return {"ok": False, "error": str(e)}


@app.get("/api/recipes/user")
async def get_user_recipes():
    return {"recipes": _load_json("user_recipes.json")}


class RecipeImportRequest(BaseModel):
    url: str
    api_key: str = ""


@app.post("/api/recipes/import-url")
async def import_recipe_url(req: RecipeImportRequest):
    """Import a recipe from any web URL (JSON-LD first, Groq LLM fallback)."""
    try:
        from services.recipe_import import import_from_url
        resolved = resolve_key(req.api_key)
        groq_client = make_groq_client(resolved) if resolved else None
        loop = asyncio.get_event_loop()
        try:
            recipe = await asyncio.wait_for(
                loop.run_in_executor(None, lambda: import_from_url(req.url, groq_client)),
                timeout=30.0,
            )
        except asyncio.TimeoutError:
            return {"ok": False, "error": "URL import timed out (30 s). The site may be blocking scrapers."}
        return {"ok": True, "recipe": recipe}
    except Exception as e:
        traceback.print_exc()
        return {"ok": False, "error": str(e)}


@app.post("/api/recipes/import-youtube")
async def import_recipe_youtube(req: RecipeImportRequest):
    """Import a recipe from a YouTube video transcript via Groq LLM."""
    try:
        from services.recipe_import import import_from_youtube
        api_key = resolve_key(req.api_key)
        if not api_key:
            return {"ok": False, "error": "Groq API key required for YouTube import"}
        groq_client = make_groq_client(api_key)
        # Run in executor with a 45-second timeout so the button never gets stuck
        loop = asyncio.get_event_loop()
        try:
            recipe = await asyncio.wait_for(
                loop.run_in_executor(None, lambda: import_from_youtube(req.url, groq_client)),
                timeout=45.0,
            )
        except asyncio.TimeoutError:
            return {"ok": False, "error": "Extraction timed out (45 s). Check the video has captions/subtitles enabled."}
        return {"ok": True, "recipe": recipe}
    except Exception as e:
        traceback.print_exc()
        return {"ok": False, "error": str(e)}


@app.post("/api/recipes/submit")
async def submit_recipe(recipe: RecipeSubmit):
    recipes = _load_json("user_recipes.json")
    recipes.append(recipe.model_dump())
    _save_json("user_recipes.json", recipes)
    return {"ok": True, "count": len(recipes)}


@app.put("/api/recipes/user/{idx}")
async def update_user_recipe(idx: int, recipe: RecipeSubmit):
    recipes = _load_json("user_recipes.json")
    if idx < 0 or idx >= len(recipes):
        return {"ok": False, "error": "Recipe not found"}
    recipes[idx] = recipe.model_dump()
    _save_json("user_recipes.json", recipes)
    return {"ok": True}


@app.delete("/api/recipes/user/{idx}")
async def delete_user_recipe(idx: int):
    recipes = _load_json("user_recipes.json")
    if idx < 0 or idx >= len(recipes):
        return {"ok": False, "error": "Recipe not found"}
    recipes.pop(idx)
    _save_json("user_recipes.json", recipes)
    return {"ok": True, "count": len(recipes)}


@app.get("/api/ratings")
async def get_ratings():
    """Return all rating adjustments."""
    return {"ok": True, "adjustments": _load_json("rating_adjustments.json")}


@app.post("/api/rating")
async def update_rating(req: RatingUpdate):
    ratings = _load_json("rating_adjustments.json")
    current = ratings.get(req.recipe_name, 0.0)
    new_val = round(current + req.delta, 4)
    # Cap: adjustment alone is clamped to [-5, +5] so effective rating stays in [0, 5]
    new_val = max(-5.0, min(5.0, new_val))
    ratings[req.recipe_name] = new_val
    _save_json("rating_adjustments.json", ratings)
    return {"ok": True, "new_value": new_val}


@app.get("/api/calendar/export")
async def export_calendar(plan_json: str = Query(...)):
    """Generate an ICS file from a meal plan JSON string."""
    from datetime import datetime, timedelta
    meals = json.loads(plan_json)
    now = datetime.now()
    lines = [
        "BEGIN:VCALENDAR", "VERSION:2.0",
        "PRODID:-//GroceryOptimizer//EN", "CALSCALE:GREGORIAN",
    ]
    meal_hours = {"Breakfast": 8, "Lunch": 13, "Snack": 16, "Dinner": 20}
    for m in meals:
        day_num = int(str(m.get("Day", "Day 1")).replace("Day ", "")) - 1
        slot = m.get("Meal", "Lunch")
        hour = meal_hours.get(slot, 12)
        dt = now + timedelta(days=day_num)
        dt = dt.replace(hour=hour, minute=0, second=0)
        name = m.get("name", "Meal")
        cals = m.get("calories", "")
        lines += [
            "BEGIN:VEVENT",
            f"DTSTART:{dt.strftime('%Y%m%dT%H%M%S')}",
            f"DTEND:{(dt + timedelta(hours=1)).strftime('%Y%m%dT%H%M%S')}",
            f"SUMMARY:{slot}: {name}",
            f"DESCRIPTION:{name} — {cals} kcal",
            "END:VEVENT",
        ]
    lines.append("END:VCALENDAR")
    return Response(
        content="\r\n".join(lines),
        media_type="text/calendar",
        headers={"Content-Disposition": "attachment; filename=meal_plan.ics"},
    )


@app.post("/api/feedback/pack")
async def pack_feedback(req: PackFeedbackRequest):
    """Record a user thumbs-up / thumbs-down on a pack size suggestion.

    Data is stored in data/pack_feedback.json keyed by ingredient name
    (lower-case). The shopping pipeline reads this file on the next run
    and injects relevant feedback into the Pass 3 LLM prompt.
    """
    feedback = _load_json("pack_feedback.json")
    if not isinstance(feedback, dict):
        feedback = {}
    key = req.ingredient.lower().strip()
    entry = feedback.get(key, {"thumbs_up": 0, "thumbs_down": 0})
    if req.vote == "up":
        entry["thumbs_up"] = entry.get("thumbs_up", 0) + 1
    else:
        entry["thumbs_down"] = entry.get("thumbs_down", 0) + 1
    feedback[key] = entry
    _save_json("pack_feedback.json", feedback)
    return {"ok": True, "feedback": entry}


@app.get("/api/body/dri")
async def body_dri(
    sex: str = "male",
    age: int = 30,
    weight_kg: float = 75.0,
    height_cm: float = 175.0,
    activity: str = "moderate",
):
    """Compute full USDA DRI targets for this person (macros + all vitamins + minerals)."""
    try:
        from services.body import compute_full_dri, get_dri
        result = compute_full_dri(sex, age, weight_kg, height_cm, activity)
        # Also include the micronutrient DRI in bar-compatible units (vitamin_d_iu, etc.)
        result["micronutrient_dri"] = get_dri(sex, age)
        return {"ok": True, **result}
    except Exception as e:
        traceback.print_exc()
        return {"ok": False, "error": str(e)}


@app.get("/api/body/news")
async def body_news(refresh: bool = False):
    """Return cached health / longevity news feed."""
    try:
        articles = fetch_health_news(max_items=25, force_refresh=refresh)
        return {"ok": True, "articles": articles}
    except Exception as e:
        traceback.print_exc()
        return {"ok": False, "error": str(e), "articles": []}


@app.post("/api/body/estimate-nutrients")
async def body_estimate_nutrients(req: BodyEstimateNutrientsRequest):
    """Estimate 13 extended nutrients via USDA FoodData Central API + Groq fallback.

    For each ingredient:
      1. Parse into (food_name, portion_grams)
      2. Query USDA API → nutrients per 100 g  (measured lab data)
      3. Scale to portion: actual_intake = per_100g × (portion_g / 100)
      4. Sum all meals / days → daily average
      5. Groq estimates only for ingredients USDA can't match
    """
    try:
        api_key = resolve_key(req.api_key)
        meal_plan = req.meal_plan or (dash_cache.fetch("meal_plan") or [])

        def _run():
            return estimate_extended_nutrients(meal_plan, api_key)

        loop = asyncio.get_event_loop()
        estimates = await loop.run_in_executor(None, _run)
        return {"ok": True, "estimates": estimates}
    except Exception as e:
        traceback.print_exc()
        return {"ok": False, "error": str(e)}


@app.post("/api/body/coach-chat")
async def body_coach_chat_endpoint(req: BodyCoachChatRequest):
    """One turn of the Body Coach agent (context-aware nutrition assistant)."""
    try:
        api_key = resolve_key(req.api_key)

        def _run():
            return body_coach_chat(
                message=req.message,
                history=req.history,
                profile=req.profile,
                nutrient_data=req.nutrient_data,
                supplements=req.supplements,
                api_key=api_key,
            )

        loop = asyncio.get_event_loop()
        reply = await loop.run_in_executor(None, _run)
        return {"ok": True, "reply": reply}
    except Exception as e:
        traceback.print_exc()
        return {"ok": False, "error": str(e)}


@app.post("/api/body/analyze")
async def body_analyze(req: BodyAnalyzeRequest):
    """Cross-reference meal plan with USDA micronutrient data and return gaps."""
    try:
        # Use cached meal plan from Dash cache if request doesn't include one
        meal_plan = req.meal_plan or (dash_cache.fetch("meal_plan") or [])
        nutrient_data = analyze_nutrients(meal_plan, req.measurements)
        supplements = get_supplement_gaps(nutrient_data, req.measurements)
        return {
            "ok": True,
            "nutrient_data": nutrient_data,
            "supplements": supplements,
            "nutrient_meta": [
                {"key": k, "label": lbl, "unit": unit, "color": col}
                for k, lbl, unit, col in NUTRIENT_META
            ],
        }
    except Exception as e:
        traceback.print_exc()
        return {"ok": False, "error": str(e)}


@app.get("/api/body/news/trends")
async def news_trends():
    """Return the most recently detected trend signals."""
    return {"trends": get_trends()}


@app.get("/api/body/news/status")
async def news_rag_status():
    """Return Qdrant collection stats (ready flag + chunk count)."""
    return get_ingestion_status()


class IngestRequest(BaseModel):
    api_key: str = ""


@app.post("/api/body/news/ingest")
async def news_ingest(req: IngestRequest):
    """Manually trigger news ingestion (RAG + CAG) with force=True."""
    try:
        api_key = resolve_key(req.api_key)
        count = ingest_news_articles(force=True, api_key=api_key)
        status = get_ingestion_status()
        return {"ok": True, "chunks_ingested": count, **status}
    except Exception as e:
        traceback.print_exc()
        return {"ok": False, "error": str(e)}


@app.post("/api/body/news/query")
async def news_rag_query(req: NewsQueryRequest):
    """RAG query over ingested health/longevity articles."""
    try:
        result = query_news(req.question, resolve_key(req.api_key))
        return {"ok": True, **result}
    except Exception as e:
        traceback.print_exc()
        return {"ok": False, "error": str(e)}


@app.post("/api/debate")
async def debate(req: DebateRequest):
    """Run Budget Optimizer vs Nutritionist debate on the current basket."""
    try:
        result = debate_basket(req.items, resolve_key(req.api_key))
        return {"ok": True, **result}
    except Exception as e:
        traceback.print_exc()
        return {"ok": False, "error": str(e)}


@app.post("/api/debate/chat")
async def debate_chat(req: DebateChatRequest):
    """Multi-agent chat: run one or more agents against the basket and return replies."""
    try:
        from services.debate import _parse_basket

        basket = _parse_basket(req.items)
        total  = sum(i["price"] for i in basket)
        basket_text = (
            "\n".join(
                f"- {i['name']} × {i['count']} ({i['pack_size']}) = €{i['price']:.2f}"
                for i in basket
            )
            + f"\n\nTotal: €{total:.2f}"
        ) if basket else "(no basket items)"

        valid_agents = {"budget", "nutrition", "moderator"}
        replies = []
        for agent_id in req.agents:
            if agent_id not in valid_agents:
                continue
            reply = run_agent_chat(
                agent_id=agent_id,
                message=req.message,
                history=req.history,
                groq_key=resolve_key(req.api_key),
                items=req.items,
                basket_text=basket_text,
            )
            replies.append({"agent": agent_id, "content": reply})

        return {"ok": True, "replies": replies}
    except Exception as e:
        traceback.print_exc()
        return {"ok": False, "error": str(e)}


# ── Dash dashboards (only when DISABLE_DASH is not set) ──────────────────────
if _DASH_ENABLED:
    app.mount("/dash", WSGIMiddleware(dash_app.server))
else:
    # When Dash is disabled (e.g. Render free tier), return a friendly HTML page
    # instead of FastAPI's raw {"detail":"Not Found"} JSON inside iframes.
    from fastapi.responses import HTMLResponse

    @app.get("/dash/{path:path}")
    async def dash_disabled(path: str):
        return HTMLResponse("""<!DOCTYPE html>
<html><body style="margin:0;display:flex;align-items:center;justify-content:center;
height:100vh;font-family:system-ui,sans-serif;background:#f8fafc;color:#64748b">
<div style="text-align:center;padding:24px">
  <div style="font-size:2.5rem;margin-bottom:12px">📊</div>
  <div style="font-weight:600;font-size:1rem;margin-bottom:6px;color:#334155">
    Analytics unavailable on free tier</div>
  <div style="font-size:.82rem">Plotly/Dash is disabled to stay within 512 MB RAM.<br>
  Run locally or set <code>DISABLE_DASH=</code> (empty) to enable.</div>
</div></body></html>""")

# ── Static files (must be last) ──────────────────────────────────────────────
app.mount("/static", StaticFiles(directory="static"), name="static")


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
