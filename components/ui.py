import json
import os
from datetime import datetime

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from core.config import CUISINE_MAP

_DATA_DIR                = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
_USER_RECIPES_FILE       = os.path.join(_DATA_DIR, "user_recipes.json")
_RATING_ADJUSTMENTS_FILE = os.path.join(_DATA_DIR, "rating_adjustments.json")


def _save_user_recipes():
    try:
        with open(_USER_RECIPES_FILE, "w", encoding="utf-8") as f:
            json.dump(st.session_state.get("user_recipes", []), f, ensure_ascii=False, indent=2)
    except Exception as e:
        st.warning(f"Could not save recipe to disk: {e}")


def _save_rating_adjustments():
    try:
        with open(_RATING_ADJUSTMENTS_FILE, "w", encoding="utf-8") as f:
            json.dump(st.session_state.get("rating_adjustments", {}), f, ensure_ascii=False, indent=2)
    except Exception as e:
        st.warning(f"Could not save ratings to disk: {e}")
from core.optimizer import optimize_meal_plan
from core.shopping import optimize_shopping_list_groq
from services.rag import is_valid_key, parse_basket_intent, rag_answer, search_products


# ── Sidebar ──────────────────────────────────────────────────────────────────

def render_sidebar(_df_recipes):
    with st.sidebar:

        # ── Mercadona Assistant ────────────────────────────────────────────
        st.header("🤖 App Assistant")
        st.caption("Ask about recipes, Mercadona products, YouTube videos, or anything food-related.")

        if "rag_unlocked" not in st.session_state:
            st.session_state.rag_unlocked = False
        if "rag_messages" not in st.session_state:
            st.session_state.rag_messages = []

        with st.expander("🔑 API Setup", expanded=not st.session_state.rag_unlocked):
            from services.rag import DEFAULT_MODELS
            provider = st.selectbox(
                "LLM Provider",
                ["OpenRouter", "Gemini", "OpenAI", "Groq", "Anthropic", "Mistral", "Cohere", "Ollama"],
                key="rag_provider_select",
            )
            if provider == "Ollama":
                api_key_input = "ollama"
                st.info("Ollama runs locally — no key needed.")
            elif provider == "OpenRouter":
                st.info("Free models available — get a key at [openrouter.ai](https://openrouter.ai). Default model: `meta-llama/llama-3.3-70b-instruct:free`")
                api_key_input = st.text_input(
                    "API Key", type="password",
                    placeholder="sk-or-v1-...",
                    key="rag_api_key_input",
                )
            elif provider == "Gemini":
                st.info("Free tier available — get a key at [aistudio.google.com](https://aistudio.google.com).")
                api_key_input = st.text_input(
                    "API Key", type="password",
                    placeholder="AIza...",
                    key="rag_api_key_input",
                )
            else:
                _ph = {
                    "OpenAI": "sk-...", "Groq": "gsk_...", "Anthropic": "sk-ant-...",
                    "Mistral": "your Mistral key", "Cohere": "your Cohere key",
                }
                api_key_input = st.text_input(
                    "API Key", type="password",
                    placeholder=_ph.get(provider, "your key"),
                    key="rag_api_key_input",
                )
            model_input = st.text_input(
                "Model override (optional)",
                placeholder=DEFAULT_MODELS.get(provider, ""),
                key="rag_model_input",
            )
            if st.button("Unlock Chat", key="rag_unlock_btn"):
                if is_valid_key(api_key_input, provider):
                    st.session_state.rag_unlocked = True
                    st.session_state.rag_api_key  = api_key_input
                    st.session_state.rag_provider = provider
                    st.session_state.rag_model    = model_input.strip() or None
                    st.rerun()
                else:
                    st.error("Key format looks wrong.")

        if not st.session_state.rag_unlocked:
            st.info("Enter a valid API key above to start chatting.")
            return

        shopping_list = st.session_state.get("shopping_list")
        if shopping_list is not None and not shopping_list.empty:
            if st.button("🛒 Check my shopping list", key="rag_check_list_btn"):
                items = shopping_list["Ingredient"].dropna().tolist()
                question = f"Do you carry these products? Check each and give price: {', '.join(items)}"
                st.session_state.rag_messages.append({"role": "user", "content": question})
                _basket = st.session_state.get('basket', [])
                _basket_ctx = ""
                if _basket:
                    _names = [it.get('Ingredient', '') for it in _basket[:8] if it.get('Ingredient')]
                    _basket_total = sum(float(it.get('Total Price', 0) or 0) for it in _basket)
                    _basket_ctx = (
                        f"\n\n[User's current basket — {len(_basket)} items, €{_basket_total:.2f} total: "
                        + ", ".join(_names)
                        + (f"... and {len(_basket) - 8} more" if len(_basket) > 8 else "")
                        + "]"
                    )
                with st.spinner("Checking..."):
                    reply = rag_answer(
                        question=question + _basket_ctx,
                        messages_history=st.session_state.rag_messages[:-1],
                        api_key=st.session_state.rag_api_key,
                        provider=st.session_state.rag_provider,
                        model=st.session_state.get("rag_model"),
                    )
                clean_text, basket_items = parse_basket_intent(reply)
                msg = {"role": "assistant", "content": clean_text}
                if basket_items:
                    msg["basket_items"] = basket_items
                st.session_state.rag_messages.append(msg)
                st.rerun()

        # Chat history in a scrollable container
        with st.container(height=400):
            for i, msg in enumerate(st.session_state.rag_messages):
                with st.chat_message(msg["role"]):
                    st.markdown(msg["content"])
                    pending = msg.get("basket_items")
                    if pending:
                        names = ", ".join(it.get("name", "?") for it in pending)
                        if st.button(
                            f"✅ Add to basket: {names}",
                            key=f"rag_add_basket_{i}",
                        ):
                            if 'basket' not in st.session_state:
                                st.session_state.basket = []
                            for it in pending:
                                price = float(it.get("price", 0) or 0)
                                st.session_state.basket.append({
                                    "source":      "Assistant",
                                    "Ingredient":  it.get("name", ""),
                                    "Qty Needed":  it.get("qty", "1 unit"),
                                    "Unit Price":  price,
                                    "Count":       1,
                                    "Total Price": price,
                                    "Link":        it.get("url", ""),
                                })
                            msg["basket_items"] = []  # dismiss button after adding
                            st.rerun()

        user_input = st.chat_input("Ask about a product...")
        if user_input:
            st.session_state.rag_messages.append({"role": "user", "content": user_input})

            # Build fresh basket context so the LLM knows what's already in the basket
            _basket = st.session_state.get('basket', [])
            _basket_ctx = ""
            if _basket:
                _names = [it.get('Ingredient', '') for it in _basket[:8] if it.get('Ingredient')]
                _basket_total = sum(float(it.get('Total Price', 0) or 0) for it in _basket)
                _basket_ctx = (
                    f"\n\n[User's current basket — {len(_basket)} items, €{_basket_total:.2f} total: "
                    + ", ".join(_names)
                    + (f"... and {len(_basket) - 8} more" if len(_basket) > 8 else "")
                    + "]"
                )

            with st.spinner("Thinking..."):
                reply = rag_answer(
                    question=user_input + _basket_ctx,
                    messages_history=st.session_state.rag_messages[:-1],
                    api_key=st.session_state.rag_api_key,
                    provider=st.session_state.rag_provider,
                    model=st.session_state.get("rag_model"),
                )
            clean_text, basket_items = parse_basket_intent(reply)
            msg = {"role": "assistant", "content": clean_text}
            if basket_items:
                msg["basket_items"] = basket_items
            st.session_state.rag_messages.append(msg)
            st.rerun()

        if st.session_state.rag_messages:
            if st.button("🗑️ Clear chat", key="rag_clear_btn"):
                st.session_state.rag_messages = []
                st.rerun()


# ── Tab: Meal Planner ────────────────────────────────────────────────────────

def render_tab_meal_plan(df_recipes):
    st.header("📅 Meal Planner")

    if 'validation_step' not in st.session_state:
        st.session_state.validation_step = 0

    # ── Step 1: Parameters ────────────────────────────────────────────────
    with st.expander("⚙️ Planning Parameters", expanded=(st.session_state.meal_plan is None)):
        col_a, col_b = st.columns(2)
        days         = col_a.slider("Time Horizon (Days)", 1, 14, 7, key="mp_days")
        people_count = col_b.number_input("Household Size", 1, 10, 1, key="mp_people")

        available_slots = [
            "Breakfast",
            "Morning Snack",
            "Lunch",
            "Afternoon Snack",
            "Dinner",
            "Dessert",
            "Non-Alcoholic Beverage",
        ]
        selected_slots = st.multiselect(
            "Meals per Day", available_slots,
            default=["Breakfast", "Lunch", "Dinner"], key="mp_slots",
        )
        cuisine_prefs = st.multiselect(
            "Preferred Cuisines", list(CUISINE_MAP.keys()),
            default=[], placeholder="Leave empty for any cuisine", key="mp_cuisines",
        )

        st.markdown("**Daily Nutritional Targets**")
        nc1, nc2, nc3, nc4 = st.columns(4)
        target_calories = nc1.number_input("Calories (kcal)", 1000, 5000, 2000, key="mp_cal")
        target_protein  = nc2.number_input("Protein (g)", 10, 300, 150, key="mp_prot")
        target_carbs    = nc3.number_input("Carbs (g)", 10, 500, 200, key="mp_carbs")
        target_fat      = nc4.number_input("Fat (g)", 10, 200, 65, key="mp_fat")

        st.markdown("**Constraints**")
        cc1, cc2, cc3 = st.columns(3)
        max_budget  = cc1.number_input("Max Daily Budget (€)", 5.0, 100.0, 20.0, key="mp_budget")
        max_time    = cc2.number_input("Max Cook Time (mins)", 5, 120, 30, key="mp_time")
        variability = cc3.select_slider(
            "Meal Variety",
            options=["Low (Batch Cooking)", "Medium", "High (New Meal Every Day)"],
            value="High (New Meal Every Day)", key="mp_var",
        )
        dislikes = st.text_input(
            "Dislikes / Allergies (comma separated)", "Mushrooms, Eggplant", key="mp_dislikes",
        )


    # ── Step 2: Generate ──────────────────────────────────────────────────
    if st.button("🚀 Generate Plan", type="primary"):
        if not selected_slots:
            st.error("Please select at least one meal slot.")
        else:
            with st.spinner("Optimising your meals..."):
                combined_df = df_recipes.copy()
                if st.session_state.user_recipes:
                    combined_df = pd.concat(
                        [combined_df, pd.DataFrame(st.session_state.user_recipes)],
                        ignore_index=True,
                    )
                plan_df, msg = optimize_meal_plan(
                    combined_df, target_calories, target_protein, target_carbs, target_fat,
                    max_budget, max_time, dislikes, days, selected_slots, cuisine_prefs,
                    cuisine_map=CUISINE_MAP, people_count=people_count, variability=variability,
                    rating_adjustments=st.session_state.get('rating_adjustments', {}),
                )
            if plan_df is not None:
                st.session_state.meal_plan = plan_df
                st.session_state.validation_step = 1
                st.session_state.shopping_list = None
                st.session_state.shopping_list_display = pd.DataFrame()
                st.session_state.last_plan_params = dict(
                    days=days, target_calories=target_calories,
                    target_protein=target_protein, target_carbs=target_carbs,
                    target_fat=target_fat, max_budget=max_budget,
                    people_count=people_count,
                )
            else:
                st.error(msg)

    # ── Step 3: Schedule ──────────────────────────────────────────────────
    if st.session_state.meal_plan is not None:
        p = st.session_state.get('last_plan_params', {})
        _display_meal_schedule(
            df_recipes,
            p.get('days', 7),
            p.get('target_calories', 2000),
            p.get('target_protein', 150),
            p.get('target_carbs', 200),
            p.get('target_fat', 65),
            p.get('max_budget', 20.0),
        )

        st.divider()
        if st.button("📋 Finalize & Generate Shopping List", type="primary"):
            _generate_shopping_list(df_recipes, p.get('people_count', 1))

    # ── Step 4: Shopping list ─────────────────────────────────────────────
    if st.session_state.validation_step >= 2:
        _display_shopping_list()


def _generate_shopping_list(df_recipes, people_count):
    plan_df = st.session_state.meal_plan
    all_items = []
    has_json = 'ingredients_json' in plan_df.columns

    for _, row in plan_df.iterrows():
        people_n = int(row.get('People', 1))
        item_list = []

        if has_json and isinstance(row.get('ingredients_json'), str):
            try:
                for x in json.loads(row['ingredients_json']):
                    item_list.append((x.get('q', ""), x.get('i', "")))
            except Exception:
                pass

        if not item_list:
            raw = row.get('ingredients', "")
            if pd.isna(raw):
                raw = ""
            for ing in [i.strip() for i in str(raw).split(',') if i.strip()]:
                item_list.append(("", ing))

        for q_val, ing_name in item_list:
            if not ing_name:
                continue
            for _ in range(people_n):
                all_items.append({
                    'Quantity':   q_val,
                    'Ingredient': ing_name,
                    'RefKey':     ing_name.lower().strip(),
                })

    df_shop = pd.DataFrame(all_items)

    if df_shop.empty:
        st.session_state.shopping_list = pd.DataFrame()
        st.session_state.shopping_list_display = pd.DataFrame()
        return

    # Group by ingredient and sum counts
    grouped = df_shop.groupby('Ingredient').agg({
        'Quantity': lambda x: ", ".join([str(v) for v in x if v]),
        'RefKey':   'count',
    }).rename(columns={'RefKey': 'Count'}).reset_index()

    # Look up best Mercadona match for every ingredient via TF-IDF
    try:
        from ingredient_translations import ENGLISH_TO_SPANISH as _E2S
    except ImportError:
        _E2S = {}

    def _merc_lookup(ing_name):
        top = search_products(ing_name, top_k=5)
        # Bilingual fallback: try Spanish if English search returned nothing
        if top.empty:
            ing_lower = ing_name.lower().strip()
            es_name = _E2S.get(ing_lower)
            if not es_name:
                # partial match: find longest key that is a substring of the ingredient
                es_name = next(
                    (v for k, v in sorted(_E2S.items(), key=lambda x: -len(x[0])) if k in ing_lower),
                    None,
                )
            if es_name:
                top = search_products(es_name, top_k=5)
        if top.empty:
            return 0.0, '', '', []
        best = top.iloc[0]
        candidates = [
            {"name": str(r.get('name', '')), "price": float(r.get('price', 0) or 0), "url": str(r.get('url', '') or '')}
            for _, r in top.iterrows()
        ]
        return (
            float(best.get('price', 0) or 0),
            str(best.get('url', '') or ''),
            str(best.get('name', '') or ''),
            candidates,
        )

    with st.spinner("Matching ingredients to Mercadona products..."):
        lookup_results = [_merc_lookup(ing) for ing in grouped['Ingredient']] \
            if not grouped.empty else []

    # Build SKU lookup dict (sku_name → {price, url}) for change detection in display
    sku_lookup = {}
    sku_options = []
    for price, url, sku_name, candidates in lookup_results:
        for c in candidates:
            n = c['name']
            if n and n not in sku_lookup:
                sku_lookup[n] = {'price': c['price'], 'url': c['url']}
                sku_options.append(n)
    st.session_state['sku_lookup']  = sku_lookup
    st.session_state['sku_options'] = sku_options

    grouped['Unit Price']  = [r[0] for r in lookup_results]
    grouped['Link']        = [r[1] for r in lookup_results]
    grouped['SKU']         = [r[2] for r in lookup_results]
    grouped['Total Price'] = grouped['Count'] * grouped['Unit Price']

    def clean_qty(val):
        import re
        from fractions import Fraction
        from collections import defaultdict

        tokens = [t.strip().strip('"') for t in str(val).split(',')]
        clean  = [t for t in tokens if t and t.upper() != 'NA']
        if not clean:
            return ""

        unit_totals = defaultdict(float)
        unparsed = []

        for token in clean:
            token = token.strip()
            # Match: optional whole number, optional fraction, optional unit
            # e.g. "1 1/2 cup", "4 cups", "1/2 tsp", "2", "3 tbsp"
            m = re.match(r'^(\d+\s+\d+/\d+|\d+/\d+|\d+\.?\d*)\s*(.*)$', token)
            if m:
                num_str = m.group(1).strip()
                unit    = m.group(2).strip().lower().rstrip('s')  # normalise plural
                try:
                    # Handle mixed numbers like "1 1/2"
                    parts_n = num_str.split()
                    if len(parts_n) == 2:
                        num = float(Fraction(parts_n[0])) + float(Fraction(parts_n[1]))
                    else:
                        num = float(Fraction(parts_n[0]))
                    unit_totals[unit] += num
                except Exception:
                    unparsed.append(token)
            else:
                unparsed.append(token)

        result_parts = []
        for unit, total in unit_totals.items():
            # Format number: drop trailing .0 for whole numbers
            num_str = str(int(total)) if total == int(total) else f"{total:.2g}"
            if unit:
                # Restore plural for amounts > 1
                unit_disp = unit + ('s' if total > 1 and not unit.endswith('s') else '')
                result_parts.append(f"{num_str} {unit_disp}")
            else:
                result_parts.append(num_str)

        result_parts.extend(unparsed)
        return ", ".join(result_parts) if result_parts else ", ".join(clean)

    grouped['Qty Needed'] = grouped['Quantity'].apply(clean_qty)

    st.session_state.shopping_list = grouped

    # AI refinement: Groq improves unit/qty/pack-size calculations on top of TF-IDF prices
    g_client = st.session_state.get('groq_client')
    final_display = pd.DataFrame()

    if g_client:
        with st.spinner("AI is refining quantities and pack sizes..."):
            optimized = optimize_shopping_list_groq(grouped, g_client)
            if not optimized.empty:
                final_display = optimized

    if final_display.empty:
        final_display = grouped[['Ingredient', 'Qty Needed', 'SKU', 'Unit Price', 'Count', 'Total Price', 'Link']]

    st.session_state.shopping_list_display = final_display
    st.session_state.validation_step = 2


def _find_comparable_recipes(target_row, df, n=20):
    """Return up to n recipes where ALL macros are within ±30% of the target,
    sorted by overall macro closeness (closest first)."""
    cal  = float(target_row.get('calories', 0) or 0)
    prot = float(target_row.get('protein',  0) or 0)
    carbs= float(target_row.get('carbs',    0) or 0)
    fat  = float(target_row.get('fat',      0) or 0)

    d = df.copy()
    for col in ['calories', 'protein', 'carbs', 'fat']:
        d[col] = pd.to_numeric(d[col], errors='coerce').fillna(0)

    # Hard filter: every macro must be within ±30% of target
    THRESHOLD = 0.30
    mask = pd.Series(True, index=d.index)
    for val, col in [(cal, 'calories'), (prot, 'protein'), (carbs, 'carbs'), (fat, 'fat')]:
        ref = max(val, 1)
        lo, hi = ref * (1 - THRESHOLD), ref * (1 + THRESHOLD)
        mask &= d[col].between(lo, hi)

    d = d[mask]
    current_name = str(target_row.get('name', ''))
    d = d[d['name'] != current_name]

    if d.empty:
        return []

    # Sort survivors by sum of relative deviations (smallest = closest)
    d['_dev'] = sum(
        ((d[col] - ref).abs() / max(ref, 1))
        for ref, col in [(cal, 'calories'), (prot, 'protein'), (carbs, 'carbs'), (fat, 'fat')]
    )
    return d.nsmallest(n, '_dev')['name'].tolist()


def _display_meal_schedule(df_recipes, days, target_calories, target_protein,
                            target_carbs, target_fat, max_budget):
    plan_df = st.session_state.meal_plan


    # Combine base recipes + user recipes for all lookups
    _all_recipes = df_recipes.copy()
    if st.session_state.get('user_recipes'):
        _all_recipes = pd.concat(
            [_all_recipes, pd.DataFrame(st.session_state.user_recipes)],
            ignore_index=True,
        )

    # Build recipe name list for the override dropdown (sorted for easier browsing)
    all_recipe_names = (
        sorted(_all_recipes['name'].dropna().unique().tolist()) if not _all_recipes.empty else []
    )

    st.subheader("Your Meal Schedule")
    days_list = sorted(set(plan_df['Day'].values), key=lambda x: int(x.split(' ')[1]))

    for day_str in days_list:
        _ra = st.session_state.setdefault('rating_adjustments', {})
        day_data = plan_df.loc[plan_df['Day'] == day_str].copy()
        day_data['Remove']    = False
        day_data['More Info'] = False
        day_num = int(day_str.split(' ')[1])

        with st.expander(
            f"{day_str} — {day_data['calories'].sum():.0f} kcal | €{day_data['cost'].sum():.2f}",
            expanded=(day_num == 1),
        ):
            display_cols = ['Remove', 'Meal', 'name',
                            'calories', 'protein', 'carbs', 'fat', 'prep_time', 'cost',
                            'More Info']
            col_cfg = {
                "Remove":     st.column_config.CheckboxColumn("Remove 🗑️"),
                "Meal":       st.column_config.TextColumn("Slot", disabled=True),
                "name":       st.column_config.SelectboxColumn(
                                  "Recipe Name", options=all_recipe_names, width="large",
                              ),
                "calories":   st.column_config.NumberColumn("Cals", disabled=True),
                "protein":    st.column_config.NumberColumn("Protein", disabled=True),
                "carbs":      st.column_config.NumberColumn("Carbs", disabled=True),
                "fat":        st.column_config.NumberColumn("Fat", disabled=True),
                "prep_time":  st.column_config.NumberColumn("Time (min)", disabled=True),
                "cost":       st.column_config.NumberColumn("Cost", format="€%.2f", disabled=True),
                "More Info":  st.column_config.CheckboxColumn("More Info 📖"),
            }
            # ── Table ──────────────────────────────────────────────────────
            edited_day = st.data_editor(
                day_data[display_cols],
                column_config=col_cfg,
                use_container_width=True,
                hide_index=True,
                key=f"editor_{day_str.replace(' ', '_')}",
            )

            # ── Rating strip — always-visible ▲/▼ per meal ─────────────────
            st.markdown(
                "<div style='font-size:11px;font-weight:600;color:#888;"
                "margin:10px 0 4px;letter-spacing:.03em'>⭐ MEAL RATINGS</div>",
                unsafe_allow_html=True,
            )
            for idx, row in day_data.iterrows():
                recipe_name   = str(row.get('name', ''))
                meal_label    = str(row.get('Meal', ''))
                current_steps = int(_ra.get(recipe_name) or 0)
                display_val   = current_steps * 0.25
                val_color     = "#2ecc71" if display_val > 0 else ("#e74c3c" if display_val < 0 else "#999")
                sign          = "+" if display_val > 0 else ""
                short_name    = recipe_name if len(recipe_name) <= 30 else recipe_name[:28] + "…"

                c_meal, c_name, c_up, c_score, c_dn = st.columns([1, 5, 1, 1, 1])
                c_meal.markdown(
                    f"<div style='font-size:12px;color:#888;padding-top:6px'>{meal_label}</div>",
                    unsafe_allow_html=True,
                )
                c_name.markdown(
                    f"<div style='font-size:12px;font-weight:500;padding-top:6px;"
                    f"white-space:nowrap;overflow:hidden;text-overflow:ellipsis'>{short_name}</div>",
                    unsafe_allow_html=True,
                )
                if c_up.button("▲", key=f"rup_{day_str}_{idx}",
                               help="Increase rating by 0.25",
                               disabled=(current_steps >= 16)):
                    _ra[recipe_name] = current_steps + 1
                    _save_rating_adjustments()
                    st.rerun()
                c_score.markdown(
                    f"<div style='text-align:center;color:{val_color};font-weight:700;"
                    f"font-size:13px;padding-top:6px'>{sign}{display_val:.2f}</div>",
                    unsafe_allow_html=True,
                )
                if c_dn.button("▼", key=f"rdn_{day_str}_{idx}",
                               help="Decrease rating by 0.25",
                               disabled=(current_steps <= -16)):
                    new_steps = current_steps - 1
                    if new_steps == 0:
                        _ra.pop(recipe_name, None)
                    else:
                        _ra[recipe_name] = new_steps
                    _save_rating_adjustments()
                    st.rerun()

            # ── Handle Remove ──────────────────────────────────────────────
            to_remove = edited_day[edited_day['Remove'] == True].index.tolist()
            if to_remove:
                st.session_state.meal_plan = st.session_state.meal_plan.drop(index=to_remove)
                st.session_state.shopping_list = None
                st.session_state.shopping_list_display = pd.DataFrame()
                st.session_state.validation_step = 1
                st.rerun()

            # ── Handle recipe override & sub toggle ────────────────────────
            recipe_changed = False
            for idx, row in edited_day.iterrows():
                if idx not in st.session_state.meal_plan.index:
                    continue
                original_name = day_data.at[idx, 'name']
                new_name = row['name']

                if new_name and new_name != original_name:
                    match = _all_recipes[_all_recipes['name'] == new_name]
                    if not match.empty:
                        nr = match.iloc[0]
                        for col in ['calories', 'protein', 'carbs', 'fat', 'cost',
                                    'prep_time', 'ingredients', 'ingredients_json']:
                            if col in nr.index and col in st.session_state.meal_plan.columns:
                                st.session_state.meal_plan.at[idx, col] = nr[col]
                        st.session_state.meal_plan.at[idx, 'name'] = new_name
                        recipe_changed = True


            if recipe_changed:
                st.session_state.shopping_list = None
                st.session_state.shopping_list_display = pd.DataFrame()
                st.session_state.validation_step = 1
                st.rerun()


            # ── More Info panels ───────────────────────────────────────────
            for idx, row in edited_day.iterrows():
                if row.get('More Info'):
                    recipe_name = row.get('name', '')
                    full = _all_recipes[_all_recipes['name'] == recipe_name]
                    rec = full.iloc[0] if not full.empty else (
                        st.session_state.meal_plan.loc[idx]
                        if idx in st.session_state.meal_plan.index else None
                    )
                    if rec is not None:
                        with st.container(border=True):
                            st.markdown(f"### 📖 {recipe_name}")
                            m1, m2, m3, m4, m5 = st.columns(5)
                            m1.metric("Calories",   f"{float(rec.get('calories', 0) or 0):.0f} kcal")
                            m2.metric("Protein",    f"{float(rec.get('protein',  0) or 0):.1f} g")
                            m3.metric("Carbs",      f"{float(rec.get('carbs',    0) or 0):.1f} g")
                            m4.metric("Fat",        f"{float(rec.get('fat',      0) or 0):.1f} g")
                            m5.metric("Prep Time",  f"{float(rec.get('prep_time',0) or 0):.0f} min")

                            i1, i2, i3 = st.columns(3)
                            i1.markdown(f"**Category:** {rec.get('RecipeCategory', '—')}")
                            i2.markdown(f"**Rating:** {float(rec.get('AggregatedRating', 0) or 0):.1f} / 5")
                            i3.markdown(f"**Est. Cost:** €{float(rec.get('cost', 0) or 0):.2f}")

                            kw = rec.get('Keywords', '')
                            if kw and str(kw) not in ('nan', ''):
                                st.markdown(f"**Keywords:** {kw}")

                            ing = rec.get('ingredients', '')
                            if ing and str(ing) not in ('nan', ''):
                                st.markdown("**Ingredients:**")
                                st.write(ing)

                            instructions = rec.get('instructions', '')
                            if instructions and str(instructions) not in ('nan', ''):
                                st.markdown("**Preparation Steps:**")
                                st.markdown(str(instructions))

                            src = rec.get('source_url', '')
                            if src and str(src) not in ('nan', ''):
                                st.markdown(f"**Source:** [{src}]({src})")

            # ── Comparable recipes finder ──────────────────────────────────
            with st.expander("🔍 Find comparable recipe for a slot", expanded=False):
                slot_options = day_data['Meal'].tolist()
                comp_slot = st.selectbox(
                    "Which slot?", slot_options,
                    key=f"comp_slot_{day_str}",
                )
                if st.button("Find Comparable Recipes", key=f"comp_find_{day_str}"):
                    target_row = day_data[day_data['Meal'] == comp_slot].iloc[0]
                    comparables = _find_comparable_recipes(target_row, _all_recipes, n=20)
                    st.session_state[f'comp_results_{day_str}'] = comparables

                comparables = st.session_state.get(f'comp_results_{day_str}', None)
                if comparables is not None and len(comparables) == 0:
                    st.info("No recipes found within ±30% of all macros. Try a broader search or check the dataset.")
                if comparables:
                    chosen = st.selectbox(
                        "Pick a comparable recipe",
                        [""] + comparables,
                        key=f"comp_pick_{day_str}",
                    )
                    if chosen and st.button("✅ Apply", key=f"comp_apply_{day_str}"):
                        target_idx = day_data[day_data['Meal'] == comp_slot].index[0]
                        match = _all_recipes[_all_recipes['name'] == chosen]
                        if not match.empty:
                            nr = match.iloc[0]
                            for col in ['calories', 'protein', 'carbs', 'fat', 'cost',
                                        'prep_time', 'ingredients', 'ingredients_json']:
                                if col in nr.index and col in st.session_state.meal_plan.columns:
                                    st.session_state.meal_plan.at[target_idx, col] = nr[col]
                            st.session_state.meal_plan.at[target_idx, 'name'] = chosen
                            st.session_state.pop(f'comp_results_{day_str}', None)
                            st.session_state.shopping_list = None
                            st.session_state.shopping_list_display = pd.DataFrame()
                            st.session_state.validation_step = 1
                            st.rerun()


    # Nutrition summary
    st.subheader("Average Daily Nutrition vs Targets")
    avg_cal  = plan_df['calories'].sum() / days
    avg_prot = plan_df['protein'].sum() / days
    avg_carb = plan_df['carbs'].sum() / days
    avg_fat  = plan_df['fat'].sum() / days
    avg_cost = plan_df['cost'].sum() / days

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Calories",    f"{avg_cal:.0f}",  f"{avg_cal - target_calories:.0f} from target", delta_color="inverse")
    c2.metric("Protein (g)", f"{avg_prot:.0f}", f"{avg_prot - target_protein:.0f} from target")
    c3.metric("Carbs (g)",   f"{avg_carb:.0f}", f"{avg_carb - target_carbs:.0f} from target")
    c4.metric("Fat (g)",     f"{avg_fat:.0f}",  f"{avg_fat - target_fat:.0f} from target")
    c5.metric("Daily Cost",  f"€{avg_cost:.2f}", f"€{avg_cost - max_budget:.2f} from budget", delta_color="inverse")

    fig = go.Figure(data=[
        go.Bar(name='Actual (Avg)', x=['Protein', 'Carbs', 'Fat'], y=[avg_prot, avg_carb, avg_fat]),
        go.Bar(name='Target',       x=['Protein', 'Carbs', 'Fat'], y=[target_protein, target_carbs, target_fat]),
    ])
    fig.update_layout(barmode='group', title="Macronutrient Comparison")
    st.plotly_chart(fig, use_container_width=True)



def _display_shopping_list():
    disp = st.session_state.get('shopping_list_display', pd.DataFrame())

    if not disp.empty:
        total = pd.to_numeric(disp.get('Total Price', pd.Series(dtype=float)), errors='coerce').sum()
        st.subheader(f"🛒 Shopping List — Total: €{total:.2f}")
    else:
        st.subheader("🛒 Shopping List")
        st.info("Shopping list is empty. Try finalizing your meal plan above.")
        return

    # Ensure required columns exist
    if 'Remove' not in disp.columns:
        disp['Remove'] = False
    if 'SKU' not in disp.columns:
        disp['SKU'] = ''
    if 'Image' in disp.columns:
        disp = disp.drop(columns=['Image'])

    sku_options = st.session_state.get('sku_options', [])
    sku_lookup  = st.session_state.get('sku_lookup', {})

    # Ensure every current SKU value is in the options list so the selectbox doesn't error
    existing_skus = disp['SKU'].dropna().unique().tolist()
    all_sku_options = list(dict.fromkeys(existing_skus + sku_options))  # preserve order, dedupe

    # Column order: Ingredient | Qty Needed | SKU | Unit Price | Count | Total Price | Link | Remove
    show_cols = ['Ingredient', 'Qty Needed', 'SKU', 'Unit Price', 'Count', 'Total Price', 'Link', 'Remove']
    show_cols = [c for c in show_cols if c in disp.columns]

    col_config = {
        "Ingredient":  st.column_config.TextColumn("Ingredient", disabled=True, width="medium"),
        "Qty Needed":  st.column_config.TextColumn("Qty Needed", disabled=True),
        "SKU":         st.column_config.SelectboxColumn(
                           "Product (SKU)",
                           options=all_sku_options,
                           width="large",
                           help="Click to pick a different Mercadona product. Price and link update automatically.",
                       ),
        "Unit Price":  st.column_config.NumberColumn("Unit Price", format="€%.2f", disabled=True),
        "Count":       st.column_config.NumberColumn("Count", disabled=True),
        "Total Price": st.column_config.NumberColumn("Total Price", format="€%.2f", disabled=True),
        "Link":        st.column_config.LinkColumn("Buy Link", display_text="Open Link"),
        "Remove":      st.column_config.CheckboxColumn("Remove 🗑️"),
    }

    edited_df = st.data_editor(
        disp[show_cols],
        column_config=col_config,
        use_container_width=True,
        hide_index=True,
        key="shopping_list_editor",
    )

    # Detect SKU changes and update price / link / total automatically
    sku_changed = False
    for i, (idx, row) in enumerate(edited_df.iterrows()):
        new_sku = str(row.get('SKU', '') or '')
        if new_sku and new_sku in sku_lookup:
            orig_sku = str(disp.iloc[i].get('SKU', '') if i < len(disp) else '')
            if new_sku != orig_sku:
                prod = sku_lookup[new_sku]
                count = float(row.get('Count', 1) or 1)
                st.session_state.shopping_list_display.at[idx, 'SKU']         = new_sku
                st.session_state.shopping_list_display.at[idx, 'Unit Price']  = prod['price']
                st.session_state.shopping_list_display.at[idx, 'Link']        = prod['url']
                st.session_state.shopping_list_display.at[idx, 'Total Price'] = prod['price'] * count
                sku_changed = True
    if sku_changed:
        st.rerun()

    purchase_list = edited_df[~edited_df['Remove']].copy() if 'Remove' in edited_df.columns else edited_df.copy()

    if st.button("🛒 Add to Basket", type="primary", key="add_to_basket_btn"):
        if not purchase_list.empty:
            rows_to_add = purchase_list.copy()
            rows_to_add['source'] = 'Meal Plan'
            st.session_state.basket.extend(rows_to_add.to_dict('records'))
            st.success(f"Added {len(rows_to_add)} items to basket! Switch to the 🛒 Basket tab.")
        else:
            st.warning("All items removed or list empty.")


# ── Tab: Meal Calendar ────────────────────────────────────────────────────────

def _build_ics(meal_plan_df: pd.DataFrame, start_date) -> bytes:
    """Build an ICS file bytes from the meal plan DataFrame."""
    import uuid
    from datetime import timedelta

    MEAL_TIMES = {"Breakfast": (8, 0), "Lunch": (13, 0), "Dinner": (19, 0)}
    MEAL_DURATION = {"Breakfast": 30, "Lunch": 45, "Dinner": 60}

    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Grocery Trip Optimizer//Meal Plan//EN",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
    ]

    for _, row in meal_plan_df.iterrows():
        try:
            day_num = int(str(row.get("Day", "Day 1")).split(" ")[1])
        except (ValueError, IndexError):
            day_num = 1
        meal = str(row.get("Meal", "Breakfast"))
        name = str(row.get("name", "Meal"))
        cals = row.get("calories", "")
        cost = row.get("cost", "")

        h, m = MEAL_TIMES.get(meal, (12, 0))
        duration = MEAL_DURATION.get(meal, 30)
        event_date = start_date + timedelta(days=day_num - 1)
        dtstart = event_date.strftime("%Y%m%d") + f"T{h:02d}{m:02d}00"
        end_dt = event_date + timedelta(hours=h, minutes=m + duration)
        dtend = event_date.strftime("%Y%m%d") + f"T{end_dt.strftime('%H%M00')}"

        desc_parts = []
        if cals:
            desc_parts.append(f"Calories: {float(cals):.0f} kcal")
        if cost:
            desc_parts.append(f"Est. cost: €{float(cost):.2f}")
        description = " | ".join(desc_parts)

        lines += [
            "BEGIN:VEVENT",
            f"UID:{uuid.uuid4()}@grocery-optimizer",
            f"DTSTAMP:{__import__('datetime').datetime.utcnow().strftime('%Y%m%dT%H%M%SZ')}",
            f"DTSTART:{dtstart}",
            f"DTEND:{dtend}",
            f"SUMMARY:{meal}: {name}",
            f"DESCRIPTION:{description}",
            "END:VEVENT",
        ]

    lines.append("END:VCALENDAR")
    return "\r\n".join(lines).encode("utf-8")


def _render_calendar_grid(meal_plan_df: pd.DataFrame, start_date):
    """Render a simple weekly calendar grid using Streamlit columns."""
    from datetime import timedelta

    SLOT_ORDER = ["Breakfast", "Lunch", "Dinner"]
    SLOT_EMOJI = {"Breakfast": "🌅", "Lunch": "☀️", "Dinner": "🌙"}

    # Collect days
    try:
        days_list = sorted(
            set(meal_plan_df["Day"].values),
            key=lambda x: int(x.split(" ")[1]),
        )
    except Exception:
        days_list = list(set(meal_plan_df["Day"].values))

    # Split into weeks of 7
    chunks = [days_list[i:i+7] for i in range(0, len(days_list), 7)]

    for week_idx, week_days in enumerate(chunks):
        week_start = start_date + __import__('datetime').timedelta(
            days=7 * week_idx
        )
        week_end = week_start + __import__('datetime').timedelta(days=len(week_days) - 1)
        st.markdown(
            f"<div style='font-size:13px;font-weight:600;color:#555;"
            f"margin:12px 0 4px'>Week {week_idx+1} &nbsp; "
            f"<span style='font-weight:400'>{week_start.strftime('%b %d')} – "
            f"{week_end.strftime('%b %d, %Y')}</span></div>",
            unsafe_allow_html=True,
        )
        cols = st.columns(len(week_days))
        for col, day_str in zip(cols, week_days):
            try:
                day_num = int(day_str.split(" ")[1])
            except (ValueError, IndexError):
                day_num = 1
            date_label = (start_date + __import__('datetime').timedelta(days=day_num - 1)).strftime("%a %d %b")
            day_meals = meal_plan_df[meal_plan_df["Day"] == day_str]

            # Build card HTML
            card_rows = ""
            for slot in SLOT_ORDER:
                slot_row = day_meals[day_meals["Meal"] == slot]
                if slot_row.empty:
                    continue
                recipe = str(slot_row.iloc[0].get("name", "—"))
                cals   = slot_row.iloc[0].get("calories", "")
                cal_str = f"<span style='color:#aaa;font-size:10px'> {float(cals):.0f} kcal</span>" if cals else ""
                emoji  = SLOT_EMOJI.get(slot, "🍽️")
                # Truncate long names
                display = recipe if len(recipe) <= 22 else recipe[:20] + "…"
                card_rows += (
                    f"<div style='margin-bottom:6px;border-left:3px solid #4e8cff;"
                    f"padding-left:6px'>"
                    f"<div style='font-size:10px;color:#888'>{emoji} {slot}</div>"
                    f"<div style='font-size:11px;font-weight:500;line-height:1.3'>{display}</div>"
                    f"{cal_str}"
                    f"</div>"
                )
            if not card_rows:
                card_rows = "<div style='font-size:11px;color:#bbb;font-style:italic'>No meals</div>"

            col.markdown(
                f"<div style='background:#f8f9fc;border-radius:8px;padding:10px 8px;"
                f"min-height:140px;border:1px solid #e3e6ed'>"
                f"<div style='font-size:11px;font-weight:700;color:#333;"
                f"margin-bottom:8px;border-bottom:1px solid #e3e6ed;padding-bottom:4px'>"
                f"{date_label}</div>"
                f"{card_rows}"
                f"</div>",
                unsafe_allow_html=True,
            )


def render_tab_calendar():
    import datetime
    st.subheader("📅 Meal Calendar")

    meal_plan = st.session_state.get("meal_plan")
    if meal_plan is None or (hasattr(meal_plan, "empty") and meal_plan.empty):
        st.info("No meal plan yet. Generate one in the sidebar to see your calendar.")
        return

    # Date picker: which Monday to start from
    today = datetime.date.today()
    monday = today - datetime.timedelta(days=today.weekday())
    start_date = st.date_input(
        "Plan start date",
        value=monday,
        help="Day 1 of your plan will be placed on this date.",
    )

    st.divider()
    _render_calendar_grid(meal_plan, start_date)
    st.divider()

    # ICS download
    ics_bytes = _build_ics(meal_plan, start_date)
    st.download_button(
        label="⬇️ Download calendar (.ics)",
        data=ics_bytes,
        file_name="meal_plan.ics",
        mime="text/calendar",
        help="Opens in Google Calendar, Outlook, Apple Calendar, and any app that supports the iCalendar format.",
    )
    st.caption(
        "To import: in Google Calendar click **+** → *Import* and select the file. "
        "In Outlook go to *File → Open & Export → Import/Export*."
    )


# ── Tab 2: History ────────────────────────────────────────────────────────────

def render_tab_history():
    st.subheader("📚 Order History")
    history = st.session_state.get('run_history', [])
    if history:
        for i, entry in enumerate(reversed(history)):
            sl_df = pd.DataFrame(entry['shopping_list'])
            order_total = pd.to_numeric(
                sl_df.get('Total Price', pd.Series(dtype=float)), errors='coerce'
            ).sum() if not sl_df.empty else 0
            with st.expander(f"Order {len(history) - i} — {entry['date']} — €{order_total:.2f}"):
                st.write("**Meals:**")
                st.dataframe(pd.DataFrame(entry['meal_plan']))
                st.write("**Shopping List:**")
                st.dataframe(sl_df)
    else:
        st.info("No order history yet. Generate and confirm a meal plan to record your first order.")


# ── Tab 3: Recipe Forum ───────────────────────────────────────────────────────

_KW_MAP = {
    "Main Dish":    "main dinner lunch entree casserole stew chicken beef pork pasta",
    "Breakfast":    "breakfast brunch egg oatmeal cereal granola toast waffle pancake",
    "Lunch/Snacks": "lunch snack appetizer bites salad sandwich wrap",
    "Dessert":      "dessert cake cookie sweet pie",
    "Salad":        "salad lunch main dinner",
    "Soup":         "soup stew chili lunch dinner main",
    "Pasta":        "pasta dinner lunch main",
    "Vegetable":    "vegetable dinner lunch main salad",
    "Other":        "main dinner lunch",
}
_RF_CATS = list(_KW_MAP.keys())


def _rf_apply_prefill():
    """Copy rf_prefill_* keys into the widget state keys, then remove them.
    Must be called before the form renders so Streamlit picks up the values."""
    mapping = {
        "rf_prefill_name":         "rf_w_name",
        "rf_prefill_ingredients":  "rf_w_ingredients",
        "rf_prefill_instructions": "rf_w_instructions",
        "rf_prefill_source_url":   "rf_w_source_url",
        "rf_prefill_calories":     "rf_w_calories",
        "rf_prefill_protein":      "rf_w_protein",
        "rf_prefill_carbs":        "rf_w_carbs",
        "rf_prefill_fat":          "rf_w_fat",
        "rf_prefill_prep_time":    "rf_w_prep_time",
        "rf_prefill_category":     "rf_w_category",
    }
    for src, dst in mapping.items():
        if src in st.session_state:
            val = st.session_state.pop(src)
            if val is not None:
                # Clamp numerics
                if dst in ("rf_w_calories",):
                    val = max(0, min(int(val or 0), 3000))
                elif dst in ("rf_w_protein", "rf_w_fat"):
                    val = max(0, min(int(val or 0), 200))
                elif dst == "rf_w_carbs":
                    val = max(0, min(int(val or 0), 500))
                elif dst == "rf_w_prep_time":
                    val = max(1, min(int(val or 30), 300))
                st.session_state[dst] = val


def _rf_clear_widgets():
    """Clear all form widget keys so the form resets after a successful submit."""
    for key in ["rf_w_name", "rf_w_ingredients", "rf_w_instructions", "rf_w_source_url",
                "rf_w_calories", "rf_w_protein", "rf_w_carbs", "rf_w_fat",
                "rf_w_prep_time", "rf_w_category"]:
        st.session_state.pop(key, None)


def render_tab_forum():
    st.subheader("🍽️ Recipe Forum")
    st.markdown(
        "Add your own recipes to the dataset. "
        "Your recipes will always be **prioritised** in the meal plan. "
        "All fields marked \\* are required."
    )

    groq_client = st.session_state.get("groq_client")

    # ── Import helpers (outside form so they can set prefill state) ──────────
    with st.expander("📥 Import from URL or YouTube", expanded=False):
        imp_tab_url, imp_tab_yt = st.tabs(["🔗 Import from URL", "▶️ Import from YouTube"])

        with imp_tab_url:
            imp_url = st.text_input(
                "Recipe page URL",
                placeholder="https://www.allrecipes.com/recipe/...",
                key="rf_import_url_input",
            )
            if st.button("Import", key="rf_import_url_btn"):
                if not imp_url.strip():
                    st.warning("Please enter a URL.")
                elif not groq_client:
                    st.warning("Groq API key required. Set your provider to Groq and unlock the sidebar assistant first.")
                else:
                    with st.spinner("Fetching recipe…"):
                        try:
                            from services.recipe_import import import_from_url
                            data = import_from_url(imp_url.strip(), groq_client)
                            st.session_state["rf_prefill_name"]         = data.get("name", "")
                            st.session_state["rf_prefill_category"]     = data.get("category", "Main Dish")
                            st.session_state["rf_prefill_ingredients"]  = "\n".join(data.get("ingredients", []))
                            st.session_state["rf_prefill_instructions"] = data.get("instructions", "")
                            st.session_state["rf_prefill_calories"]     = int(data.get("calories") or 0)
                            st.session_state["rf_prefill_protein"]      = int(data.get("protein") or 0)
                            st.session_state["rf_prefill_carbs"]        = int(data.get("carbs") or 0)
                            st.session_state["rf_prefill_fat"]          = int(data.get("fat") or 0)
                            st.session_state["rf_prefill_prep_time"]    = int(data.get("prep_time") or 30)
                            st.session_state["rf_prefill_source_url"]   = imp_url.strip()
                            st.success("Recipe imported! Scroll down to review and submit.")
                            st.rerun()
                        except Exception as exc:
                            st.error(f"Import failed: {exc}")

        with imp_tab_yt:
            imp_yt = st.text_input(
                "YouTube video URL",
                placeholder="https://www.youtube.com/watch?v=...",
                key="rf_import_yt_input",
            )
            if st.button("Import", key="rf_import_yt_btn"):
                if not imp_yt.strip():
                    st.warning("Please enter a YouTube URL.")
                elif not groq_client:
                    st.warning("Groq API key required. Set your provider to Groq and unlock the sidebar assistant first.")
                else:
                    with st.spinner("Fetching transcript and extracting recipe…"):
                        try:
                            from services.recipe_import import import_from_youtube
                            data = import_from_youtube(imp_yt.strip(), groq_client)
                            st.session_state["rf_prefill_name"]         = data.get("name", "")
                            st.session_state["rf_prefill_category"]     = data.get("category", "Main Dish")
                            st.session_state["rf_prefill_ingredients"]  = "\n".join(data.get("ingredients", []))
                            st.session_state["rf_prefill_instructions"] = data.get("instructions", "")
                            st.session_state["rf_prefill_calories"]     = int(data.get("calories") or 0)
                            st.session_state["rf_prefill_protein"]      = int(data.get("protein") or 0)
                            st.session_state["rf_prefill_carbs"]        = int(data.get("carbs") or 0)
                            st.session_state["rf_prefill_fat"]          = int(data.get("fat") or 0)
                            st.session_state["rf_prefill_prep_time"]    = int(data.get("prep_time") or 30)
                            st.session_state["rf_prefill_source_url"]   = imp_yt.strip()
                            st.success("Recipe extracted! Scroll down to review and submit.")
                            st.rerun()
                        except Exception as exc:
                            st.error(f"Import failed: {exc}")

    st.markdown("---")

    # Apply any pending import prefill into widget state keys before the form renders
    _rf_apply_prefill()

    # Resolve category index from widget state (for selectbox)
    _cat_val = st.session_state.get("rf_w_category", "Main Dish")
    _cat_idx = _RF_CATS.index(_cat_val) if _cat_val in _RF_CATS else 0

    with st.form("recipe_forum_form", clear_on_submit=False):
        st.markdown("#### Add a New Recipe")

        col_r1, col_r2 = st.columns(2)
        rf_name     = col_r1.text_input("Recipe Name *", key="rf_w_name",
                                         placeholder="e.g. Grilled Chicken Salad")
        rf_category = col_r2.selectbox("Category *", _RF_CATS, index=_cat_idx)

        rf_ingredients = st.text_area(
            "Ingredients * (one per line, include quantity — e.g. '2 chicken breasts')",
            key="rf_w_ingredients",
            height=130,
            placeholder="2 chicken breasts\n1 cup lettuce\n1 tbsp olive oil",
        )
        rf_instructions = st.text_area(
            "Preparation Steps *",
            key="rf_w_instructions",
            height=150,
            placeholder="Step 1: Preheat oven to 200°C.\nStep 2: Season chicken with salt and pepper.\n...",
        )

        col_r3, col_r4, col_r5, col_r6, col_r7 = st.columns(5)
        rf_cal  = col_r3.number_input("Calories *",        0, 3000, key="rf_w_calories")
        rf_prot = col_r4.number_input("Protein (g) *",     0, 200,  key="rf_w_protein")
        rf_carb = col_r5.number_input("Carbs (g) *",       0, 500,  key="rf_w_carbs")
        rf_fat  = col_r6.number_input("Fat (g) *",         0, 200,  key="rf_w_fat")
        rf_time = col_r7.number_input("Prep Time (min) *", 1, 300,  key="rf_w_prep_time")

        rf_rating     = st.slider("Your Rating *", 1, 5, 4, help="1 = poor, 5 = excellent")
        rf_source_url = st.text_input(
            "Source URL (optional)",
            key="rf_w_source_url",
            placeholder="https://www.allrecipes.com/... or https://youtube.com/...",
        )

        rf_submit = st.form_submit_button("Submit Recipe ✅")

    if rf_submit:
        errors = []
        if not rf_name.strip():
            errors.append("Recipe Name is required.")
        if not rf_ingredients.strip():
            errors.append("Ingredients are required.")
        if not rf_instructions.strip():
            errors.append("Preparation Steps are required.")
        if rf_cal == 0:
            errors.append("Calories must be greater than 0.")
        if rf_prot == 0:
            errors.append("Protein must be greater than 0.")
        if rf_carb == 0:
            errors.append("Carbs must be greater than 0.")
        if rf_fat == 0:
            errors.append("Fat must be greater than 0.")

        if errors:
            for e in errors:
                st.error(e)
        else:
            lines = [l.strip() for l in rf_ingredients.strip().split('\n') if l.strip()]
            display_name = f"👤 {rf_name.strip()}"
            st.session_state.user_recipes.append({
                "name":             display_name,
                "RecipeCategory":   rf_category,
                "Keywords":         _KW_MAP.get(rf_category, "main dinner lunch"),
                "calories":         float(rf_cal),
                "protein":          float(rf_prot),
                "carbs":            float(rf_carb),
                "fat":              float(rf_fat),
                "prep_time":        float(rf_time),
                "cost":             5.0,
                "AggregatedRating": float(rf_rating) * 2.0,
                "ingredients":      ", ".join(lines),
                "ingredients_json": json.dumps([{"q": "", "i": l} for l in lines]),
                "instructions":     rf_instructions.strip(),
                "source_url":       rf_source_url.strip(),
                "is_user_recipe":   True,
            })
            _save_user_recipes()
            _rf_clear_widgets()
            st.success(f"'{display_name}' added! It will be prioritised in your next meal plan.")
            st.rerun()

    # ── Submitted recipes list ───────────────────────────────────────────────
    if st.session_state.user_recipes:
        st.markdown("#### Your Submitted Recipes")
        display_cols = ['name', 'RecipeCategory', 'calories', 'protein', 'carbs', 'fat', 'prep_time']
        user_df = pd.DataFrame(st.session_state.user_recipes)[display_cols].copy()
        user_df.columns = ['Name', 'Category', 'Calories', 'Protein (g)', 'Carbs (g)', 'Fat (g)', 'Prep Time (min)']
        st.dataframe(user_df, use_container_width=True, hide_index=True)

        col_del1, col_del2 = st.columns([1, 5])
        if col_del1.button("🗑️ Clear All My Recipes"):
            st.session_state.user_recipes = []
            _save_user_recipes()
            st.rerun()
    else:
        st.info("No recipes submitted yet. Use the import tools or the form above to add your first recipe.")


# ── Tab 4: Mercadona Assistant (RAG) ─────────────────────────────────────────

def render_tab_rag():
    st.subheader("🤖 Mercadona Assistant")
    st.caption(
        "Ask anything about Mercadona product availability and pricing. "
        "Powered by TF-IDF retrieval over the Mercadona catalogue."
    )

    if "rag_unlocked" not in st.session_state:
        st.session_state.rag_unlocked = False
    if "rag_messages" not in st.session_state:
        st.session_state.rag_messages = []

    with st.expander("🔑 API Configuration", expanded=not st.session_state.rag_unlocked):
        from services.rag import DEFAULT_MODELS
        provider = st.selectbox(
            "LLM Provider",
            ["OpenRouter", "OpenAI", "Groq", "Anthropic", "Mistral", "Cohere", "Ollama"],
            key="rag_provider_select",
        )

        if provider == "Ollama":
            api_key_input = "ollama"
            st.info("Ollama runs locally — no API key needed. Make sure Ollama is running at `http://localhost:11434`.")
        elif provider == "OpenRouter":
            st.info("Free models available — get a key at [openrouter.ai](https://openrouter.ai). Default model: `meta-llama/llama-3.3-70b-instruct:free`")
            api_key_input = st.text_input("API Key", type="password", placeholder="sk-or-v1-...", key="rag_api_key_input2")
        else:
            _placeholders = {
                "OpenAI":    "sk-...",
                "Groq":      "gsk_...",
                "Anthropic": "sk-ant-...",
                "Mistral":   "your Mistral API key",
                "Cohere":    "your Cohere API key",
            }
            api_key_input = st.text_input(
                "API Key",
                type="password",
                placeholder=_placeholders.get(provider, "your API key"),
                key="rag_api_key_input",
            )

        model_input = st.text_input(
            "Model (optional — leave blank for default)",
            placeholder=DEFAULT_MODELS.get(provider, ""),
            key="rag_model_input",
        )

        if st.button("Unlock Chat", key="rag_unlock_btn"):
            if is_valid_key(api_key_input, provider):
                st.session_state.rag_unlocked = True
                st.session_state.rag_api_key  = api_key_input
                st.session_state.rag_provider = provider
                st.session_state.rag_model    = model_input.strip() or None
                st.rerun()
            else:
                st.error("Key format looks wrong — check the placeholder for the expected format.")

    if not st.session_state.rag_unlocked:
        st.info("Enter a valid API key above to start chatting.")
        return

    shopping_list = st.session_state.get("shopping_list")
    if shopping_list is not None and not shopping_list.empty:
        if st.button("🛒 Check my shopping list availability", key="rag_check_list_btn"):
            items = shopping_list["Ingredient"].dropna().tolist()
            question = f"Do you carry these products? Check each one and give availability and price: {', '.join(items)}"
            st.session_state.rag_messages.append({"role": "user", "content": question})
            with st.spinner("Checking availability for all items..."):
                reply = rag_answer(
                    question=question,
                    messages_history=st.session_state.rag_messages[:-1],
                    api_key=st.session_state.rag_api_key,
                    provider=st.session_state.rag_provider,
                    model=st.session_state.get("rag_model"),
                )
            st.session_state.rag_messages.append({"role": "assistant", "content": reply})
            st.rerun()

    for msg in st.session_state.rag_messages:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    user_input = st.chat_input("Ask about a product, e.g. 'Do you have oat milk?'")
    if user_input:
        st.session_state.rag_messages.append({"role": "user", "content": user_input})
        with st.chat_message("user"):
            st.markdown(user_input)
        with st.chat_message("assistant"):
            with st.spinner("Thinking..."):
                reply = rag_answer(
                    question=user_input,
                    messages_history=st.session_state.rag_messages[:-1],
                    api_key=st.session_state.rag_api_key,
                    provider=st.session_state.rag_provider,
                    model=st.session_state.get("rag_model"),
                )
            st.markdown(reply)
        st.session_state.rag_messages.append({"role": "assistant", "content": reply})
        st.rerun()

    if st.session_state.rag_messages:
        if st.button("🗑️ Clear conversation", key="rag_clear_btn"):
            st.session_state.rag_messages = []
            st.rerun()


# ── PDF generator ─────────────────────────────────────────────────────────────

def _generate_basket_pdf(basket_df: pd.DataFrame, total: float) -> bytes:
    """Generate a branded PDF shopping list. Falls back to plain text if reportlab is missing."""
    try:
        import io
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.units import cm
        from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

        buf = io.BytesIO()
        doc = SimpleDocTemplate(buf, pagesize=A4,
                                rightMargin=2*cm, leftMargin=2*cm,
                                topMargin=2*cm, bottomMargin=2*cm)
        styles = getSampleStyleSheet()
        green = colors.HexColor('#00904A')
        title_style = ParagraphStyle('CustomTitle', parent=styles['Title'],
                                     textColor=green, fontSize=18, spaceAfter=6)
        elements = [
            Paragraph("Shopping List", title_style),
            Paragraph(f"Generated: {datetime.now().strftime('%d %B %Y, %H:%M')}", styles['Normal']),
            Spacer(1, 0.5*cm),
        ]

        header = [['Item', 'Qty', 'Unit €', 'Count', 'Total €']]
        rows = []
        for _, row in basket_df.iterrows():
            rows.append([
                str(row.get('Ingredient', '')),
                str(row.get('Qty Needed', '')),
                f"€{float(row.get('Unit Price', 0) or 0):.2f}",
                str(int(row.get('Count', 1) or 1)),
                f"€{float(row.get('Total Price', 0) or 0):.2f}",
            ])
        data = header + rows + [['', '', '', 'TOTAL', f"€{total:.2f}"]]

        col_widths = [7*cm, 3*cm, 2.5*cm, 2*cm, 2.5*cm]
        tbl = Table(data, colWidths=col_widths, repeatRows=1)
        style_cmds = [
            ('BACKGROUND',    (0, 0),  (-1, 0),  green),
            ('TEXTCOLOR',     (0, 0),  (-1, 0),  colors.white),
            ('FONTNAME',      (0, 0),  (-1, 0),  'Helvetica-Bold'),
            ('FONTSIZE',      (0, 0),  (-1, 0),  10),
            ('FONTSIZE',      (0, 1),  (-1, -1), 9),
            ('BACKGROUND',    (0, -1), (-1, -1), colors.HexColor('#E8F5EE')),
            ('FONTNAME',      (0, -1), (-1, -1), 'Helvetica-Bold'),
            ('GRID',          (0, 0),  (-1, -1), 0.5, colors.HexColor('#cccccc')),
            ('VALIGN',        (0, 0),  (-1, -1), 'MIDDLE'),
            ('TOPPADDING',    (0, 0),  (-1, -1), 4),
            ('BOTTOMPADDING', (0, 0),  (-1, -1), 4),
            ('LEFTPADDING',   (0, 0),  (-1, -1), 6),
            ('RIGHTPADDING',  (0, 0),  (-1, -1), 6),
        ]
        for i in range(1, len(data) - 1):
            if i % 2 == 0:
                style_cmds.append(('BACKGROUND', (0, i), (-1, i), colors.HexColor('#f0f9f4')))
        tbl.setStyle(TableStyle(style_cmds))
        elements.append(tbl)
        doc.build(elements)
        return buf.getvalue()

    except ImportError:
        lines = [f"Shopping List — {datetime.now().strftime('%d %B %Y')}\n", "=" * 50 + "\n\n"]
        for _, row in basket_df.iterrows():
            lines.append(
                f"{str(row.get('Ingredient','')):<30}  {str(row.get('Qty Needed','')):<12}  "
                f"€{float(row.get('Total Price', 0) or 0):.2f}\n"
            )
        lines.append(f"\n{'─' * 50}\nTOTAL: €{total:.2f}\n")
        return "".join(lines).encode('utf-8')


# ── Tab: Basket ───────────────────────────────────────────────────────────────

def render_tab_basket():
    st.header("🛒 Your Basket")
    st.caption("Everything you plan to buy — from your meal plan and manual additions.")

    if 'basket' not in st.session_state:
        st.session_state.basket = []

    # ── Add items ─────────────────────────────────────────────────────────────
    with st.expander("➕ Add Items", expanded=False):
        st.markdown("**Search Mercadona catalogue**")
        bs1, bs2 = st.columns([4, 1])
        search_q = bs1.text_input(
            "Search", placeholder="e.g. olive oil, eggs, yogurt",
            key="basket_search_input", label_visibility="collapsed",
        )
        if bs2.button("Search", key="basket_search_btn") and search_q.strip():
            st.session_state['basket_search_results'] = search_products(search_q.strip(), top_k=8)

        results_df = st.session_state.get('basket_search_results')
        if results_df is not None and not results_df.empty:
            st.caption("Pick a product to add:")
            for r_i, prod_row in results_df.iterrows():
                rc1, rc2, rc3, rc4 = st.columns([3, 1, 1, 1])
                price_val = float(prod_row.get('price', 0) or 0)
                rc1.write(f"**{prod_row.get('name', '')}**")
                rc2.write(f"€{price_val:.2f}/{prod_row.get('unit', '')}")
                qty = rc3.text_input("Qty", value="1", key=f"basket_qty_{r_i}", label_visibility="collapsed")
                if rc4.button("Add", key=f"basket_add_{r_i}"):
                    st.session_state.basket.append({
                        'source':      'Manual',
                        'Ingredient':  prod_row.get('name', ''),
                        'Qty Needed':  qty,
                        'Unit Price':  price_val,
                        'Count':       1,
                        'Total Price': price_val,
                        'Link':        str(prod_row.get('url', '')),
                    })
                    st.rerun()

        st.divider()
        st.markdown("**Or add a custom item**")
        with st.form("manual_basket_form", clear_on_submit=True):
            mc1, mc2, mc3 = st.columns(3)
            m_name  = mc1.text_input("Item name", placeholder="e.g. Paper plates")
            m_qty   = mc2.text_input("Quantity",  placeholder="e.g. 2 packs")
            m_price = mc3.number_input("Price (€)", min_value=0.0, value=0.0, step=0.10)
            if st.form_submit_button("Add to Basket"):
                if m_name.strip():
                    st.session_state.basket.append({
                        'source':      'Manual',
                        'Ingredient':  m_name.strip(),
                        'Qty Needed':  m_qty.strip(),
                        'Unit Price':  m_price,
                        'Count':       1,
                        'Total Price': m_price,
                        'Link':        '',
                    })
                    st.rerun()

    if not st.session_state.basket:
        st.info("Your basket is empty. Add items from the 📅 Meal Planner or manually above.")
        return

    basket_df = pd.DataFrame(st.session_state.basket)

    for col in ['source', 'Ingredient', 'Qty Needed', 'Unit Price', 'Count', 'Total Price', 'Link']:
        if col not in basket_df.columns:
            basket_df[col] = '' if col in ('source', 'Ingredient', 'Qty Needed', 'Link') else 0.0

    total = pd.to_numeric(basket_df['Total Price'], errors='coerce').fillna(0).sum()
    n_items      = len(basket_df)
    n_from_plan  = int((basket_df['source'] == 'Meal Plan').sum())
    n_from_asst  = int((basket_df['source'] == 'Assistant').sum())
    n_manual     = n_items - n_from_plan - n_from_asst

    # ── KPI metrics bar ───────────────────────────────────────────────────────
    k1, k2, k3, k4 = st.columns(4)
    k1.metric("💰 Total Cost",      f"€{total:.2f}")
    k2.metric("🛒 Items",           n_items)
    k3.metric("📅 From Meal Plan",  n_from_plan)
    k4.metric("✋ Manual / Chat",   n_manual + n_from_asst)

    st.divider()

    # ── Basket table: AgGrid with data_editor fallback ────────────────────────
    display_cols = [c for c in
                    ['source', 'Ingredient', 'Qty Needed', 'Unit Price', 'Count', 'Total Price', 'Link']
                    if c in basket_df.columns]

    try:
        from st_aggrid import AgGrid, GridOptionsBuilder, GridUpdateMode

        gb = GridOptionsBuilder.from_dataframe(basket_df[display_cols])
        gb.configure_default_column(editable=True, resizable=True)
        gb.configure_column("source",      editable=False, headerName="Source",  width=110)
        gb.configure_column("Ingredient",  headerName="Item",    rowDrag=True,   width=200)
        gb.configure_column("Qty Needed",  headerName="Qty",                     width=100)
        gb.configure_column("Unit Price",  headerName="Unit €",  width=90,
                            type=["numericColumn"],
                            valueFormatter="'€' + Number(value).toFixed(2)")
        gb.configure_column("Count",       width=80, type=["numericColumn"])
        gb.configure_column("Total Price", headerName="Total €", width=90, editable=False,
                            type=["numericColumn"],
                            valueFormatter="'€' + Number(value).toFixed(2)")
        gb.configure_column("Link", headerName="Link", editable=False, width=70,
                            cellRenderer="function(p){return p.value"
                                         "?'<a href=\"'+p.value+'\" target=\"_blank\">Open</a>':''}")
        gb.configure_selection("multiple", use_checkbox=True, header_checkbox=True)
        gb.configure_grid_options(rowDragManaged=True, animateRows=True)

        grid_resp = AgGrid(
            basket_df[display_cols],
            gridOptions=gb.build(),
            update_mode=GridUpdateMode.MODEL_CHANGED,
            allow_unsafe_jscode=True,
            fit_columns_on_grid_load=True,
            height=400,
            theme="streamlit",
            key="basket_aggrid",
        )

        purchase_list = pd.DataFrame(grid_resp["data"])
        selected = grid_resp.get("selected_rows") or []
        # selected_rows may be a DataFrame in newer versions
        sel_records = selected.to_dict("records") if hasattr(selected, "to_dict") else list(selected)
        if sel_records:
            if st.button("🗑️ Remove Selected", key="aggrid_remove_btn"):
                sel_set = {r.get("Ingredient") for r in sel_records}
                st.session_state.basket = [
                    it for it in st.session_state.basket
                    if it.get("Ingredient") not in sel_set
                ]
                st.rerun()

    except ImportError:
        basket_df['Remove'] = False
        col_cfg = {
            "source":      st.column_config.TextColumn("Source", disabled=True),
            "Ingredient":  st.column_config.TextColumn("Item", width="medium"),
            "Qty Needed":  st.column_config.TextColumn("Qty"),
            "Unit Price":  st.column_config.NumberColumn("Unit €", format="€%.2f"),
            "Count":       st.column_config.NumberColumn("Count"),
            "Total Price": st.column_config.NumberColumn("Total €", format="€%.2f"),
            "Link":        st.column_config.LinkColumn("Buy Link", display_text="Open"),
            "Remove":      st.column_config.CheckboxColumn("Remove 🗑️"),
        }
        edited = st.data_editor(
            basket_df[display_cols + ['Remove']],
            column_config=col_cfg,
            use_container_width=True,
            hide_index=True,
            num_rows="dynamic",
            key="basket_editor",
        )
        purchase_list = edited[~edited['Remove']].drop(columns=['Remove'])

    st.divider()

    # ── Action buttons ────────────────────────────────────────────────────────
    bc1, bc2, bc3 = st.columns(3)

    pdf_bytes = _generate_basket_pdf(purchase_list, total)
    bc1.download_button(
        "📄 Download PDF",
        data=pdf_bytes,
        file_name=f"shopping_list_{datetime.now().strftime('%Y%m%d')}.pdf",
        mime="application/pdf",
        key="basket_pdf_btn",
    )

    if bc2.button("✅ Confirm Purchase", key="basket_confirm_btn"):
        if not purchase_list.empty:
            if 'pantry_leftovers' not in st.session_state:
                st.session_state.pantry_leftovers = pd.DataFrame(columns=['Ingredient', 'Leftover', 'Link'])
            if 'run_history' not in st.session_state:
                st.session_state.run_history = []
            st.session_state.run_history.append({
                "date":          datetime.now().strftime("%Y-%m-%d %H:%M"),
                "meal_plan":     st.session_state.meal_plan.to_dict() if st.session_state.meal_plan is not None else {},
                "shopping_list": purchase_list.to_dict(),
            })
            st.session_state.basket = []
            st.toast("Purchase confirmed & saved to History!", icon="💾")
            st.rerun()
        else:
            st.warning("All items removed or basket empty.")

    if bc3.button("🗑️ Clear Basket", key="basket_clear_btn"):
        st.session_state.basket = []
        st.rerun()




# ── CSS Theme ─────────────────────────────────────────────────────────────────

def apply_theme():
    st.markdown("""
<style>
#MainMenu {visibility: hidden;}
footer {visibility: hidden;}

:root {
    --mg: #00904A;
    --mg-dark: #006B38;
    --mg-light: #E8F5EE;
    --mg-border: rgba(0,144,74,0.18);
}
.stApp { background-color: #FFFFFF; }
section[data-testid="stSidebar"] {
    background-color: #F7F9F7;
    border-right: 3px solid var(--mg);
}
section[data-testid="stSidebar"] h1,
section[data-testid="stSidebar"] h2,
section[data-testid="stSidebar"] h3 { color: var(--mg) !important; }
h1 { color: var(--mg) !important; font-weight: 800 !important; }
h2, h3 { color: var(--mg-dark) !important; }
.stButton > button {
    background-color: var(--mg) !important;
    color: #fff !important;
    border: none !important;
    border-radius: 8px !important;
    font-weight: 600 !important;
    transition: background .2s, transform .1s;
}
.stButton > button:hover {
    background-color: var(--mg-dark) !important;
    transform: translateY(-1px);
    box-shadow: 0 4px 12px rgba(0,144,74,.25);
}
.stTabs [data-baseweb="tab-list"] {
    gap: 4px;
    border-bottom: 2px solid var(--mg);
}
.stTabs [data-baseweb="tab"] {
    border-radius: 8px 8px 0 0;
    font-weight: 600;
    color: #555;
    background: #f0f0f0;
    padding: 0.6rem 1.4rem;
}
.stTabs [aria-selected="true"] {
    background-color: var(--mg) !important;
    color: #fff !important;
}
[data-testid="metric-container"] {
    background: var(--mg-light);
    border: 1px solid var(--mg-border);
    border-radius: 10px;
    padding: 0.8rem;
}
.stSuccess { border-left: 4px solid var(--mg); background: var(--mg-light); }
.stInfo    { border-left: 4px solid var(--mg); }
.stForm { border: 1px solid var(--mg-border); border-radius: 10px; padding: 1rem; }
</style>
""", unsafe_allow_html=True)
