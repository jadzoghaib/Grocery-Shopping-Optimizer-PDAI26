import os
import re
import json
import random as _random
import time as _time
from datetime import datetime

import numpy as np
import pandas as pd
import requests
import streamlit as st

try:
    from core.ingredient_translations import ENGLISH_TO_SPANISH
except ImportError:
    ENGLISH_TO_SPANISH = {}

from core.config import ALLOWED_RECIPE_TERMS, BLOCKED_RECIPE_TERMS


# ── Mercadona API constants ───────────────────────────────────────────────────

_MERC_API      = "https://tienda.mercadona.es/api/categories/"
_MERC_HEADS    = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "application/json",
}
_DATA_DIR      = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
_CACHE_FILE    = "mercadona_cache.csv"   # persistent weekly cache
_CACHE_MAX_AGE = 7                        # days


def _cache_path():
    return os.path.join(_DATA_DIR, _CACHE_FILE)


def _cache_is_stale():
    p = _cache_path()
    if not os.path.exists(p):
        return True
    age = datetime.now() - datetime.fromtimestamp(os.path.getmtime(p))
    return age.days >= _CACHE_MAX_AGE


def _extract_products(cat_data, cat_name=""):
    rows = []
    for sub in cat_data.get("categories", []):
        rows.extend(_extract_products(sub, sub.get("name", cat_name)))
    for p in cat_data.get("products", []):
        try:
            pi = p.get("price_instructions", {})
            price = pi.get("unit_price") or pi.get("bulk_price") or 0
            rows.append({
                "id":       p.get("id"),
                "name":     p.get("display_name", ""),
                "price":    float(price),
                "unit":     pi.get("reference_format", "unit"),
                "category": cat_name,
                "url":      p.get("share_url", f"https://tienda.mercadona.es/product/{p.get('id')}/"),
            })
        except Exception:
            continue
    return rows


@st.cache_data(ttl=604800)   # 7-day Streamlit-level cache (backs up the file cache)
def load_mercadona_db(lang="en", wh="bcn1"):
    """
    Returns the full Mercadona catalogue in English.
    Strategy:
      1. If the on-disk cache is <7 days old, load it (fast).
      2. Otherwise fetch live from the Mercadona API and save a fresh cache.
      3. If the API fails, fall back to whatever cache/CSV exists.
    The @st.cache_data TTL avoids redundant file reads within a session.
    """
    # 1. Fresh file cache → return immediately
    if not _cache_is_stale():
        try:
            return pd.read_csv(_cache_path())
        except Exception:
            pass

    # 2. Fetch live
    params = {"lang": lang, "wh": wh}
    try:
        resp = requests.get(_MERC_API, params=params, headers=_MERC_HEADS, timeout=10)
        resp.raise_for_status()
        top_cats = resp.json().get("results", [])

        all_rows = []
        for cat in top_cats:
            subcats = cat.get("categories") or [cat]
            for sub in subcats:
                sub_id = sub.get("id")
                if not sub_id:
                    continue
                try:
                    r = requests.get(
                        f"{_MERC_API}{sub_id}/", params=params,
                        headers=_MERC_HEADS, timeout=8,
                    )
                    r.raise_for_status()
                    all_rows.extend(_extract_products(r.json(), sub.get("name", "")))
                    _time.sleep(0.15)
                except Exception:
                    continue

        if all_rows:
            df = pd.DataFrame(all_rows)
            df.to_csv(_cache_path(), index=False)   # persist for next week
            return df

    except Exception as exc:
        print(f"[Mercadona] Live fetch failed ({exc}), using cached data.")

    # 3. Fallback: stale cache → old CSV → empty
    for fallback in [_cache_path(),
                     os.path.join(_DATA_DIR, "mercadona_prices.csv")]:
        try:
            if os.path.exists(fallback):
                return pd.read_csv(fallback)
        except Exception:
            continue
    return pd.DataFrame(columns=["id", "name", "price", "unit", "category", "url"])


@st.cache_data
def load_recipe_data():
    # Prefer the unit-enriched version; fall back to the original
    enriched_csv = os.path.join(_DATA_DIR, "recipes_enriched.csv")
    local_csv    = os.path.join(_DATA_DIR, "recipes.csv")
    csv_path = enriched_csv if os.path.exists(enriched_csv) else local_csv
    prices_path = os.path.join(_DATA_DIR, "ingredient_prices_synthetic.csv")

    price_map = {}
    url_map = {}

    try:
        try:
            m_df = load_mercadona_db()
            m_df = m_df[m_df['price'] > 0]
            # Products are now in English (lang=en) — match directly on English ingredient names
            for eng_key in ENGLISH_TO_SPANISH.keys():
                matches = m_df[m_df['name'].str.contains(eng_key, case=False, na=False)]
                if not matches.empty:
                    avg_p = matches['price'].mean()
                    product_url = matches.iloc[0]['url'] if 'url' in matches.columns else ""
                    if not product_url and 'id' in matches.columns:
                        product_url = f"https://tienda.mercadona.es/product/{matches.iloc[0]['id']}/"
                    if any(x in eng_key for x in ['chicken', 'beef', 'pork', 'rice', 'pasta', 'beans', 'lentils', 'flour', 'sugar']):
                        avg_p = avg_p / 4.0
                    elif 'egg' in eng_key:
                        avg_p = avg_p / 12.0
                    elif 'milk' in eng_key:
                        avg_p = avg_p / 4.0
                    price_map[eng_key] = avg_p
                    url_map[eng_key] = {
                        'url': product_url,
                        'price': avg_p,
                        'original_price': matches['price'].mean(),
                        'image': matches.iloc[0]['thumbnail'] if 'thumbnail' in matches.columns else "",
                    }
        except Exception as e:
            print(f"Error processing Mercadona prices: {e}")

        if not price_map and os.path.exists(prices_path):
            try:
                p_df = pd.read_csv(prices_path)
                for _, row in p_df.iterrows():
                    p = row['price']
                    if p <= 0:
                        p = 0.05
                    price_map[row['ingredient'].lower().strip()] = p
            except Exception:
                pass

        df = pd.read_csv(csv_path, nrows=20000)

        allowed_set = set(t.lower() for t in ALLOWED_RECIPE_TERMS)
        blocked_set = set(t.lower() for t in BLOCKED_RECIPE_TERMS)

        def is_allowed(row):
            cat = str(row.get('RecipeCategory', '')).lower()
            keywords = str(row.get('Keywords', '')).lower()
            if any(b in cat for b in blocked_set) or any(b in keywords for b in blocked_set):
                return False
            if cat in allowed_set:
                return True
            return any(term in cat or term in keywords for term in allowed_set)

        mask = df.apply(is_allowed, axis=1)
        df = df[mask].reset_index(drop=True)
        if df.empty:
            df = pd.read_csv(csv_path, nrows=500)

        df.rename(columns={
            'Name': 'name',
            'Calories': 'calories',
            'ProteinContent': 'protein',
            'CarbohydrateContent': 'carbs',
            'FatContent': 'fat',
        }, inplace=True)

        if 'AggregatedRating' not in df.columns:
            df['AggregatedRating'] = 0.0
        else:
            df['AggregatedRating'] = df['AggregatedRating'].fillna(0.0)

        def parse_iso_duration(duration_str):
            if pd.isna(duration_str) or not isinstance(duration_str, str):
                return 30
            try:
                hours = 0
                minutes = 0
                h_match = re.search(r'(\d+)H', duration_str)
                if h_match:
                    hours = int(h_match.group(1))
                m_match = re.search(r'(\d+)M', duration_str)
                if m_match:
                    minutes = int(m_match.group(1))
                return (hours * 60) + minutes
            except Exception:
                return 30

        if 'TotalTime' in df.columns:
            df['prep_time'] = df['TotalTime'].apply(parse_iso_duration)
        elif 'PrepTime' in df.columns:
            df['prep_time'] = df['PrepTime'].apply(parse_iso_duration)
        else:
            df['prep_time'] = 30

        def process_ingredients_and_cost(row):
            def parse_r_vector(s):
                if not isinstance(s, str):
                    return []
                s = s.strip()
                if s.startswith('c(') and s.endswith(')'):
                    s = s[2:-1]
                return [x.strip().strip('"') for x in s.split('",')]

            parts, quants = [], []
            try:
                parts = parse_r_vector(row['RecipeIngredientParts'])
                quants = parse_r_vector(row['RecipeIngredientQuantities'])
            except Exception:
                pass

            # Strip ingredient names that are clearly wrong (match the recipe name itself)
            recipe_name_lower = str(row.get('name', '')).lower()
            parts  = [p for p in parts  if p.lower().strip() not in ('', 'nan') and p.lower().strip() != recipe_name_lower]
            quants = quants[:len(parts)]  # keep quants aligned after filtering

            combined_list, detailed_items = [], []
            total_cost = 0.0
            for i, p_name in enumerate(parts):
                q_val = quants[i] if i < len(quants) else ""
                combined_list.append(f"{q_val} {p_name}".strip())
                detailed_items.append({"q": q_val, "i": p_name})
                p_lower = p_name.lower().strip()
                item_price = price_map.get(p_lower, 0.20)
                if item_price == 0.20:
                    for key in price_map:
                        if key in p_lower:
                            item_price = price_map[key]
                            break
                total_cost += item_price

            if total_cost < 2.50:
                total_cost = 2.50 + (len(parts) * 0.15)

            ingredients_display = ", ".join(combined_list) if combined_list else "Assorted Ingredients"
            return pd.Series([ingredients_display, json.dumps(detailed_items), total_cost])

        result_df = df.apply(process_ingredients_and_cost, axis=1, result_type='expand')
        df['ingredients'] = result_df[0]
        df['ingredients_json'] = result_df[1]
        df['cost'] = result_df[2]
        df.attrs['url_map'] = url_map

        for col, default in [('calories', 500), ('protein', 20), ('carbs', 50), ('fat', 20), ('cost', 8.0)]:
            df[col] = pd.to_numeric(df[col], errors='coerce').fillna(default).astype(float)

        # Normalize macros to per-serving values
        servings_col = 'RecipeServings' if 'RecipeServings' in df.columns else None
        if servings_col:
            servings = pd.to_numeric(df[servings_col], errors='coerce').fillna(4).clip(lower=1, upper=20)
        else:
            servings = pd.Series(4.0, index=df.index)
        for col in ['calories', 'protein', 'carbs', 'fat']:
            if col in df.columns:
                df[col] = df[col] / servings

        # Drop rows with implausible per-serving macro values (bad data in source CSV)
        if 'protein' in df.columns:
            df = df[df['protein'] <= 120]   # >120g protein per serving is not realistic
        if 'calories' in df.columns:
            df = df[df['calories'] <= 1200] # >1200 kcal per serving filters bulk-batch recipes
        # Protein physically cannot exceed calories÷4 (1g protein = 4 kcal)
        if 'protein' in df.columns and 'calories' in df.columns:
            df = df[df['protein'] <= (df['calories'] / 4) * 1.2]
        df = df.reset_index(drop=True)

        return df

    except FileNotFoundError:
        print(f"Food.com dataset not found. Using mock data.")
    except Exception as e:
        print(f"Error loading dataset: {e}. Using mock data.")

    # Mock data fallback
    np.random.seed(42)
    recipe_names = [
        "Chicken Salad", "Beef Stir Fry", "Vegetable Curry", "Salmon with Asparagus",
        "Quinoa Bowl", "Turkey Meatballs", "Lentil Soup", "Shrimp Tacos",
        "Tofu Scramble", "Pork Chops", "Eggplant Parmesan", "Chicken Fajitas",
        "Beef Stew", "Mushroom Risotto", "Tuna Salad", "Chickpea Salad",
        "Chicken Parmesan", "Beef Tacos", "Vegetable Stir Fry", "Salmon Salad",
    ]
    ingredients_pool = [
        "Chicken", "Beef", "Pork", "Salmon", "Tuna", "Shrimp", "Turkey", "Tofu",
        "Lentils", "Chickpeas", "Quinoa", "Rice", "Pasta", "Potatoes", "Sweet Potatoes",
        "Broccoli", "Asparagus", "Spinach", "Kale", "Carrots", "Bell Peppers", "Onions",
        "Garlic", "Tomatoes", "Mushrooms", "Zucchini", "Eggplant", "Avocado", "Cheese",
        "Milk", "Eggs", "Butter", "Olive Oil", "Soy Sauce", "Salt", "Pepper",
    ]
    recipes = []
    for i in range(100):
        protein = np.random.randint(15, 60)
        carbs = np.random.randint(20, 80)
        fat = np.random.randint(10, 40)
        recipes.append({
            "id": i,
            "name": _random.choice(recipe_names) + f" {i}",
            "calories": float((protein * 4) + (carbs * 4) + (fat * 9)),
            "protein": float(protein),
            "carbs": float(carbs),
            "fat": float(fat),
            "prep_time": np.random.randint(10, 60),
            "cost": round(np.random.uniform(3.0, 15.0), 2),
            "ingredients": ", ".join(_random.sample(ingredients_pool, np.random.randint(4, 10))),
            "AggregatedRating": 0.0,
        })
    return pd.DataFrame(recipes)
