import random

import numpy as np
import pandas as pd
import pulp


def optimize_meal_plan(df, target_calories, target_protein, target_carbs, target_fat,
                       max_budget, max_time, dislikes, days, selected_slots, cuisine_prefs,
                       cuisine_map=None, people_count=1, variability="High",
                       rating_adjustments=None):

    # --- Filter by dislikes ---
    if dislikes:
        dislike_list = [d.strip().lower() for d in dislikes.split(',')]
        mask = df['ingredients'].apply(lambda x: not any(d in x.lower() for d in dislike_list))
        filtered_df = df[mask].copy()
    else:
        filtered_df = df.copy()

    filtered_df = filtered_df[filtered_df['prep_time'] <= max_time]

    # --- Filter by cuisine ---
    if cuisine_prefs:
        is_healthy_selected = "Healthy" in cuisine_prefs
        is_junk_selected = "Junk Food" in cuisine_prefs

        junk_indicators = ["dessert", "cookie", "cake", "brownie", "cupcake", "pie", "tart",
                           "pudding", "ice cream", "chocolate", "sweet", "candy"]

        if not is_junk_selected:
            def is_not_junk(row):
                text = (str(row.get('Keywords', '')) + " " + str(row.get('name', ''))).lower()
                return not any(j in text for j in junk_indicators)
            filtered_df = filtered_df[filtered_df.apply(is_not_junk, axis=1)]

        if cuisine_prefs:
            def match_cuisine(keywords_str):
                if not isinstance(keywords_str, str):
                    return False
                k_lower = keywords_str.lower()
                for selected in cuisine_prefs:
                    if cuisine_map and selected in cuisine_map:
                        if any(alias in k_lower for alias in cuisine_map[selected]):
                            return True
                    elif selected.lower() in k_lower:
                        return True
                return False

            if 'Keywords' not in filtered_df.columns:
                filtered_df['Keywords'] = filtered_df.get('keywords', "")
            filtered_df = filtered_df[filtered_df['Keywords'].apply(match_cuisine)]

    if len(filtered_df) < len(selected_slots):
        return None, "Not enough recipes match your criteria (Time/Cuisine). Try relaxing constraints."

    # --- Ensure required columns exist ---
    for col in ['RecipeCategory', 'Keywords']:
        if col not in filtered_df.columns:
            lower_col = filtered_df.get(col.lower())
            filtered_df[col] = lower_col if lower_col is not None else ""

    cats = filtered_df['RecipeCategory'].fillna("").astype(str)
    keys = filtered_df['Keywords'].fillna("").astype(str)
    names = filtered_df['name'].fillna("").astype(str)

    def check_keywords(series, keywords):
        return series.apply(lambda x: any(k in x.lower() for k in keywords))

    # ── Breakfast mask ────────────────────────────────────────────────────────
    breakfast_kws = [
        'breakfast', 'brunch', 'oatmeal', 'pancake', 'waffle', 'toast', 'omelet',
        'egg', 'cereal', 'granola', 'yogurt', 'frittata', 'quiche', 'bagel',
        'muffin', 'scone', 'crepe', 'hash brown', 'porridge', 'biscuit and gravy',
    ]
    is_breakfast = (
        cats.isin(['Breakfast', 'Breads', 'Quick Breads', 'Grains', 'Yeast Breads',
                   'Oatmeal', 'Pancakes', 'Waffles', 'French Toast', 'Eggs',
                   'Breakfast Eggs', 'Breakfast Casseroles']) |
        check_keywords(keys, breakfast_kws) |
        check_keywords(names, breakfast_kws)
    ) & ~cats.isin(['Beverages', 'Alcoholic Beverages', 'Soup', 'Stew', 'Chili',
                    'Dessert', 'Candy', 'Frozen Desserts'])

    # ── Snack mask ────────────────────────────────────────────────────────────
    snack_kws = [
        'snack', 'appetizer', 'dip', 'bites', 'bar', 'finger food',
        'bruschetta', 'crostini', 'hummus', 'nachos', 'popcorn',
        'trail mix', 'energy ball', 'protein bar',
    ]
    is_snack = (
        cats.isin(['Lunch/Snacks', 'Fruit', 'Berries', 'Nuts',
                   'Spreads', 'Chutneys', 'Sauces']) |
        check_keywords(keys, snack_kws) |
        check_keywords(names, snack_kws)
    ) & ~cats.isin(['Alcoholic Beverages', 'Beverages', 'Main Dish', 'Meat',
                    'Chicken', 'Pork', 'Beef', 'Stew', 'Dessert', 'Frozen Desserts',
                    'Pie', 'Cheesecake'])

    # ── Dessert mask ──────────────────────────────────────────────────────────
    dessert_kws = [
        'dessert', 'cake', 'cookie', 'pie', 'brownie', 'pudding', 'ice cream',
        'chocolate', 'cheesecake', 'cupcake', 'tart', 'mousse', 'fudge',
        'sorbet', 'gelato', 'tiramisu', 'pastry', 'sweet', 'candy', 'biscotti',
        'cobbler', 'crumble', 'parfait', 'panna cotta',
    ]
    is_dessert = (
        cats.isin(['Dessert', 'Frozen Desserts', 'Pie', 'Bar Cookie', 'Cheesecake',
                   'Drop Cookies', 'Cookies', 'Candy', 'Gelatin']) |
        check_keywords(keys, dessert_kws) |
        check_keywords(names, dessert_kws)
    ) & ~cats.isin(['Alcoholic Beverages', 'Beverages', 'Meat', 'Chicken',
                    'Beef', 'Pork', 'Soup', 'Stew'])

    # ── Non-alcoholic beverage mask ───────────────────────────────────────────
    na_bev_kws = [
        'smoothie', 'shake', 'juice', 'tea', 'coffee', 'lemonade', 'punch',
        'hot chocolate', 'cider', 'milkshake', 'frappe', 'mocktail',
        'horchata', 'lassi', 'agua fresca', 'infused water', 'drink', 'beverage',
    ]
    alc_indicators = [
        'alcoholic', 'cocktail', 'wine', 'beer', 'liqueur', 'ale', 'lager',
        'vodka', 'rum', 'gin', 'whiskey', 'tequila', 'brandy', 'mead', 'stout',
    ]
    # Exclude anything that is clearly food (meat, sauce, marinade, baked goods etc.)
    food_exclusion_kws = [
        'steak', 'chicken', 'beef', 'pork', 'lamb', 'fish', 'shrimp', 'salmon',
        'marinade', 'sauce', 'roast', 'baked', 'fried', 'grilled', 'soup',
        'stew', 'curry', 'casserole', 'pasta', 'rice', 'salad', 'sandwich',
        'burger', 'taco', 'pizza', 'meatball', 'meatloaf', 'turkey', 'ham',
    ]
    is_bev_na = (
        cats.isin(['Beverages', 'Shakes', 'Smoothies']) |
        check_keywords(keys, na_bev_kws) |
        check_keywords(names, na_bev_kws)
    ) & ~cats.isin(['Alcoholic Beverages']) \
      & ~check_keywords(keys, alc_indicators) \
      & ~check_keywords(names, alc_indicators) \
      & ~check_keywords(names, food_exclusion_kws)

    # ── Main meal mask ────────────────────────────────────────────────────────
    main_kws = [
        'dinner', 'lunch', 'main', 'entree', 'casserole', 'pasta', 'pizza',
        'sandwich', 'burger', 'steak', 'curry', 'roast', 'stew', 'soup',
        'chili', 'salad', 'stir fry', 'fajita', 'taco', 'burrito', 'wrap',
        'grilled', 'baked', 'braised', 'stuffed', 'skillet', 'pot pie',
    ]
    strict_breakfast_cats = ['Breakfast', 'Pancakes', 'Waffles', 'French Toast',
                              'Oatmeal', 'Breakfast Eggs', 'Breakfast Casseroles']
    strict_breakfast_kws  = ['pancake', 'waffle', 'french toast', 'cereal', 'oatmeal']

    is_main = (
        ~cats.isin(['Dessert', 'Frozen Desserts', 'Pie', 'Bar Cookie',
                    'Cheesecake', 'Drop Cookies', 'Cookies', 'Candy', 'Gelatin',
                    'Beverages', 'Alcoholic Beverages', 'Shakes', 'Smoothies']) &
        ~cats.isin(strict_breakfast_cats) &
        ~check_keywords(keys, strict_breakfast_kws) &
        ~check_keywords(names, strict_breakfast_kws) &
        (
            cats.isin([
                'Chicken', 'Chicken Breast', 'Chicken Thigh & Leg', 'Whole Chicken',
                'Poultry', 'Duck Breasts', 'Turkey Breast', 'Whole Turkey',
                'Meat', 'Beef', 'Pork', 'Lamb/Sheep', 'Veal', 'Rabbit',
                'Wild Game', 'Roast Beef', 'Steak',
                'Seafood', 'Fish', 'Tuna', 'Salmon', 'Crab', 'Shrimp',
                'Mussels', 'Lobster', 'Squid',
                'Vegetable', 'Potato', 'Sweet Potato', 'Corn',
                'Main Dish', 'One Dish Meal', 'Lunch/Snacks',
                'Stew', 'Chili', 'Soup', 'Clear Soup', 'Chowders',
                'Pasta', 'Rice', 'Beans', 'Lentil', 'Soy/Tofu',
                'Salad', 'Salad Dressings', 'Pot Roast', 'Pot Pie',
            ]) |
            check_keywords(keys, main_kws) |
            (pd.to_numeric(filtered_df['protein'], errors='coerce').fillna(0) > 15) |
            (pd.to_numeric(filtered_df['calories'], errors='coerce').fillna(0) > 300)
        )
    ) & ~check_keywords(names, ['whiskey', 'cocktail', 'margarita'])

    valid_indices = filtered_df.index.tolist()

    # ── Build valid recipe pool per slot type ─────────────────────────────────
    valid_map = {}
    for s_idx, slot in enumerate(selected_slots):
        sl = slot.lower()
        if 'breakfast' in sl:
            valid_map[s_idx] = [i for i in valid_indices if is_breakfast[i]]
        elif 'snack' in sl:
            valid_map[s_idx] = [i for i in valid_indices if is_snack[i]]
        elif 'dessert' in sl:
            valid_map[s_idx] = [i for i in valid_indices if is_dessert[i]]
        elif 'beverage' in sl:
            valid_map[s_idx] = [i for i in valid_indices if is_bev_na[i]]
        else:
            valid_map[s_idx] = [i for i in valid_indices if is_main[i]]

    # Variability mapping
    is_low_var = "Low" in variability
    is_med_var = "Medium" in variability

    days_to_solve = list(range(days))
    day_mapping = {d: d for d in range(days)}

    if is_low_var:
        days_to_solve = [0]
        for d in range(days):
            day_mapping[d] = 0
    elif is_med_var:
        days_to_solve = [d for d in range(days) if d % 2 == 0]
        for d in range(days):
            day_mapping[d] = d - (d % 2)

    solved_plans = {}

    for day in days_to_solve:
        limit = 500 if is_low_var else 300

        slot_indices_map = {}
        for s_idx in range(len(selected_slots)):
            cands = valid_map[s_idx]
            if not cands:
                return None, f"No suitable recipes found for '{selected_slots[s_idx]}'."
            if len(cands) > limit:
                cands = random.sample(cands, limit)
            slot_indices_map[s_idx] = cands

        lp_vars = {}
        vars_for_slot = {s_idx: [] for s_idx in range(len(selected_slots))}
        obj_rating = []
        total_cals, total_prot, total_carb, total_fat, total_cost = [], [], [], [], []
        slot_cal_exprs = {s_idx: [] for s_idx in range(len(selected_slots))}

        for s_idx in range(len(selected_slots)):
            candidates = slot_indices_map[s_idx]
            if not candidates:
                return None, f"No recipes found for {selected_slots[s_idx]}."

            for r_idx in candidates:
                v = pulp.LpVariable(f"x_{day}_{s_idx}_{r_idx}", cat=pulp.LpBinary)
                lp_vars[(s_idx, r_idx)] = v
                vars_for_slot[s_idx].append(v)

                cal = float(filtered_df.at[r_idx, 'calories'] or 0)
                prot = float(filtered_df.at[r_idx, 'protein'] or 0)
                carb = float(filtered_df.at[r_idx, 'carbs'] or 0)
                fat = float(filtered_df.at[r_idx, 'fat'] or 0)
                cost = float(filtered_df.at[r_idx, 'cost'] or 0)
                rating = filtered_df.at[r_idx, 'AggregatedRating']
                rating = 0.0 if pd.isna(rating) else float(rating)

                recipe_name = str(filtered_df.at[r_idx, 'name']) if 'name' in filtered_df.columns else ''
                if rating_adjustments and recipe_name in rating_adjustments:
                    rating += rating_adjustments[recipe_name] * 0.5

                total_cals.append(v * cal)
                total_prot.append(v * prot)
                total_carb.append(v * carb)
                total_fat.append(v * fat)
                total_cost.append(v * cost)
                obj_rating.append(v * rating)
                slot_cal_exprs[s_idx].append(v * cal)

        # Retry with progressively relaxed tolerances if infeasible
        best_plan = None
        for tol_cal, tol_prot, tol_macro, use_order in [
            (0.15, 0.15, 0.20, True),   # pass 1: normal
            (0.25, 0.25, 0.30, False),  # pass 2: relaxed, drop calorie ordering
            (0.40, 0.40, 0.45, False),  # pass 3: very relaxed
        ]:
            p = pulp.LpProblem(f"Meal_Day_{day}_tol{int(tol_cal*100)}", pulp.LpMaximize)

            p += pulp.lpSum(total_cost) <= max_budget

            c_sum = pulp.lpSum(total_cals)
            p += c_sum >= target_calories * (1 - tol_cal)
            p += c_sum <= target_calories * (1 + tol_cal)

            p_sum = pulp.lpSum(total_prot)
            p += p_sum >= target_protein * (1 - tol_prot)
            p += p_sum <= target_protein * (1 + tol_prot)

            carb_sum = pulp.lpSum(total_carb)
            p += carb_sum >= target_carbs * (1 - tol_macro)
            p += carb_sum <= target_carbs * (1 + tol_macro)

            fat_sum = pulp.lpSum(total_fat)
            p += fat_sum >= target_fat * (1 - tol_macro)
            p += fat_sum <= target_fat * (1 + tol_macro)

            if use_order:
                lunch_idx = next((i for i, s in enumerate(selected_slots) if 'lunch' in s.lower()), -1)
                break_idx = next((i for i, s in enumerate(selected_slots) if 'breakfast' in s.lower()), -1)
                dinner_idx = next((i for i, s in enumerate(selected_slots) if 'dinner' in s.lower()), -1)
                if lunch_idx != -1 and break_idx != -1:
                    p += pulp.lpSum(slot_cal_exprs[lunch_idx]) >= pulp.lpSum(slot_cal_exprs[break_idx]) + 10
                if lunch_idx != -1 and dinner_idx != -1:
                    p += pulp.lpSum(slot_cal_exprs[lunch_idx]) >= pulp.lpSum(slot_cal_exprs[dinner_idx]) + 10
                if break_idx != -1 and dinner_idx != -1:
                    p += pulp.lpSum(slot_cal_exprs[break_idx]) >= pulp.lpSum(slot_cal_exprs[dinner_idx]) + 10

            for s_idx in range(len(selected_slots)):
                p += pulp.lpSum(vars_for_slot[s_idx]) == 1

            p += pulp.lpSum(obj_rating)
            p.solve(pulp.PULP_CBC_CMD(msg=0, timeLimit=5))

            if pulp.LpStatus[p.status] == 'Optimal':
                plan = []
                for s_idx in range(len(selected_slots)):
                    for r_idx in slot_indices_map[s_idx]:
                        v = lp_vars.get((s_idx, r_idx))
                        if v and v.varValue and v.varValue > 0.5:
                            plan.append(r_idx)
                            break
                if len(plan) == len(selected_slots):
                    best_plan = plan
                    solved_plans[day] = plan
                    break

        if best_plan is None:
            return None, f"Could not find a meal combination for Day {day+1} within Budget/Constraints."

        if solved_plans.get(day) is None:
            return None, f"Could not find a meal combination for Day {day+1} within Budget/Constraints."

    # Assemble full plan
    weekly_plan = []
    for real_day in range(days):
        mapped_day = day_mapping[real_day]
        best_plan = solved_plans.get(mapped_day)
        if not best_plan:
            return None, "Optimization Failed."

        day_records = []
        for s_idx, r_idx in enumerate(best_plan):
            rec = filtered_df.loc[r_idx].copy()
            rec['Day'] = f"Day {real_day+1}"
            rec['Meal'] = selected_slots[s_idx]
            rec['People'] = people_count
            day_records.append(rec)

        weekly_plan.append(pd.DataFrame(day_records))

    return pd.concat(weekly_plan, ignore_index=True), "Success"
