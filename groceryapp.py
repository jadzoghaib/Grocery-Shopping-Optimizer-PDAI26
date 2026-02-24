import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime, timedelta
import json
import pulp
from groq import Groq
import random
import requests
import os

try:
    from ingredient_translations import ENGLISH_TO_SPANISH
except ImportError:
    ENGLISH_TO_SPANISH = {}

# Initialize session state variables
if 'messages' not in st.session_state:
    st.session_state.messages = []
if 'meal_plan' not in st.session_state:
    st.session_state.meal_plan = None
if 'shopping_list' not in st.session_state:
    st.session_state.shopping_list = None
if 'liked_recipe_names' not in st.session_state:
    st.session_state.liked_recipe_names = set()
if 'user_recipes' not in st.session_state:
    st.session_state.user_recipes = []  # list of dicts added via Recipe Forum
if 'pinned_recipes' not in st.session_state:
    st.session_state.pinned_recipes = []  # list of recipe names to force into plan

# Function to get API Keys

# Initialize Clients - Moved to top level to avoid duplicate widget IDs
def init_groq_client():
    # Attempt to load from environment first
    groq_key = os.environ.get("GROQ_API_KEY", None)
    
    # Fallback to hardcoded key (for dev purposes, hidden from UI)
    if not groq_key:
         groq_key = "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"

    if groq_key:
        try:
            return Groq(api_key=groq_key)
        except Exception as e:
            st.error(f"Failed to initialize Groq client: {e}")
            return None
    return None

# Global Client Instance
g_client = init_groq_client()

def get_groq_client():
    return g_client

def get_api_keys():
    # Only returns None for OpenAI as requested to remove it
    return None, None 

# Spoonacular API Configuration
SPOONACULAR_API_KEY = "e3a7ba231e8b430a9e9477fa99640a7f" # Replace with your actual Spoonacular API Key

def fetch_spoonacular_price(ingredient, amount, unit, api_key=SPOONACULAR_API_KEY):
    if not api_key or api_key == "YOUR_API_KEY_HERE":
        return None
        
    # 1. Search for the ingredient to get its ID
    search_url = f"https://api.spoonacular.com/food/ingredients/search?query={ingredient}&apiKey={api_key}"
    try:
        r = requests.get(search_url)
        data = r.json()
        if "results" in data and len(data["results"]) > 0:
            ing_id = data["results"][0]["id"]
            
            # 2. Get price information
            img_url = f"https://api.spoonacular.com/food/ingredients/{ing_id}/information?amount={amount}&unit={unit}&apiKey={api_key}"
            r_price = requests.get(img_url)
            price_data = r_price.json()
            
            # Price is usually returned in US cents
            if "estimatedCost" in price_data:
                cost_value = price_data["estimatedCost"]["value"]
                # Display in USD as per instruction
                return f"{cost_value} {price_data['estimatedCost']['unit']} (approx ${(cost_value/100):.2f})"
    except Exception as e:
        return f"Error: {str(e)}"
    
    return "Price not found"

# Initialize Clients
def get_clients(groq_key):
    g_client = None
    if groq_key:
        try: g_client = Groq(api_key=groq_key)
        except: pass
    return g_client


# Function to optimize shopping list with Groq
def optimize_shopping_list_groq(df_shop, groq_client):
    if df_shop.empty or not groq_client:
        return df_shop
        
    try:
        m_db = load_mercadona_db()
        candidates_context = []
        
        # Multi-strategy Mercadona search helper
        def search_mercadona_candidates(ing_name, m_db):
            """Try translations (longest-key-first), then individual English words, then raw name."""
            if m_db.empty:
                return "No direct match found in DB."

            ing_lower = ing_name.lower().strip()

            # Build ordered list of search terms to try
            search_attempts = []

            # 1. Spanish translations — longest key first (most specific wins)
            sorted_trans = sorted(ENGLISH_TO_SPANISH.items(), key=lambda x: len(x[0]), reverse=True)
            for k, v in sorted_trans:
                # Match exact key OR depluralized form (blueberries → blueberry)
                k_stem = k.rstrip('s')
                ing_stem = ing_lower.rstrip('s')
                if k in ing_lower or (len(k_stem) > 3 and k_stem in ing_stem):
                    if v not in search_attempts:
                        search_attempts.append(v)

            # 2. Individual English words from ingredient name (skip stop-words)
            stop = {'with', 'and', 'or', 'the', 'a', 'an', 'of', 'in', 'to',
                    'fresh', 'dried', 'ground', 'frozen', 'whole', 'chopped',
                    'sliced', 'diced', 'minced', 'cooked', 'raw', 'large',
                    'small', 'medium', 'can', 'jar', 'cup', 'tbsp', 'tsp'}
            words = [w for w in ing_lower.split() if len(w) > 3 and w not in stop]
            for w in words:
                if w not in search_attempts:
                    search_attempts.append(w)

            # 3. Full original name as last resort
            if ing_lower not in search_attempts:
                search_attempts.append(ing_lower)

            for term in search_attempts:
                try:
                    mask = m_db['name'].str.contains(re.escape(term), case=False, na=False)
                    if mask.any():
                        results = m_db[mask].head(5)
                        cand_str = ""
                        for _, r in results.iterrows():
                            cand_str += f"- Option: {r['name']} | Price: {r['price']} | URL: {r.get('url', '')}\n"
                        return cand_str
                except Exception:
                    continue

            return "No direct match found in DB."

        # Prepare context for LLM
        for i, row in df_shop.iterrows():
            ing_name = row['Ingredient']
            qty_str = str(row['Quantity']) # "1, 1, 0.5"
            count_val = row['Count']

            cand_str = search_mercadona_candidates(ing_name, m_db)

            candidates_context.append(f"Item: {ing_name} | Qty Inputs: {qty_str} | Count: {count_val}\nCandidates:\n{cand_str}\n---\n")

        prompt_template = """You are a smart shopping assistant for Mercadona (Spanish supermarket).
        For each ingredient, select the best matching product from the candidates provided.

        CRITICAL RULES:
        1. UNITS ARE MANDATORY — NEVER output a bare number without a unit.
           - Qty Inputs may be bare numbers (e.g. "2", "750", "1 1/2") or include units (e.g. "2 tbsp", "1 cup", "300g").
           - Sum all quantities for the same ingredient.
           - ALWAYS attach the correct unit to total_quantity_needed:
               * Countable items (apples, eggs, cloves, potatoes): append "units"   → "2" → "2 units"
               * Spices/dried herbs with no unit: use "tsp"                          → "2" rosemary → "2 tsp"
               * Butter, oil, liquid without unit: use "tbsp"                        → "1 1/2" butter → "1.5 tbsp"
               * Ginger, root vegetables with bare weight: use "g"                   → "750" ginger → "750 g"
               * Any other solid ingredient with bare number: estimate sensible unit  → g, ml, or units
           - If qty is "NA" or missing: ESTIMATE typical culinary quantity (spices → "1 tsp", meat → "200 g", liquids → "100 ml").
           - Convert fractions: "1/2" → "0.5", "1 1/2" → "1.5".
        2. Select the best matching candidate from the list. If no direct match, choose the CLOSEST substitute available.
        3. quantity_bought = the actual pack size sold by the store (e.g. "500 g", "1 L", "12 units"). Estimate realistically if unknown.
        4. leftover = quantity_bought minus total_quantity_needed (include unit). If none left, write "0".
        5. unit_price = the price shown in the candidate. total_price = unit_price × number of packs needed.
        6. URL: COPY the exact URL from the selected candidate. If no candidate or no URL, leave url as empty string "".

        Input Data:
        {batch_data}

        Output JSON Format (one entry per ingredient):
        {{"products": [{{"original_ingredient": "...", "product_name": "...", "total_quantity_needed": "...", "quantity_bought": "...", "leftover": "...", "unit_price": 1.50, "total_price": 1.50, "url": "..."}}]}}
        """

        # Process in batches of 20 to stay within token limits
        batch_size = 20
        new_rows = []
        for batch_start in range(0, len(candidates_context), batch_size):
            batch = candidates_context[batch_start:batch_start + batch_size]
            full_prompt = prompt_template.replace("{batch_data}", "\n".join(batch))
            try:
                completion = groq_client.chat.completions.create(
                    messages=[
                        {"role": "system", "content": "Return ONLY a JSON object with key 'products'."},
                        {"role": "user", "content": full_prompt}
                    ],
                    model="llama-3.3-70b-versatile",
                    temperature=0,
                    response_format={"type": "json_object"}
                )
                result = json.loads(completion.choices[0].message.content)
                products = result.get('products', [])
                for p in products:
                    # Build fallback search URL from Spanish translation if LLM left URL empty
                    link = p.get('url', '').strip()
                    if not link:
                        orig = p.get('original_ingredient', p.get('product_name', '')).lower().strip()
                        # Try to find best Spanish term for the URL
                        sorted_trans = sorted(ENGLISH_TO_SPANISH.items(), key=lambda x: len(x[0]), reverse=True)
                        spanish_term = None
                        for k, v in sorted_trans:
                            if k in orig or k.rstrip('s') in orig.rstrip('s'):
                                spanish_term = v
                                break
                        query = (spanish_term or orig).replace(' ', '+')
                        link = f"https://tienda.mercadona.es/search-results/?query={query}"
                    new_rows.append({
                        'Ingredient': p.get('product_name', 'Unknown'),
                        'Original': p.get('original_ingredient', ''),
                        'Qty Needed': p.get('total_quantity_needed', ''),
                        'Bought': p.get('quantity_bought', ''),
                        'Leftover': p.get('leftover', ''),
                        'Unit Price': float(p.get('unit_price', 0) or 0),
                        'Total Price': float(p.get('total_price', 0) or 0),
                        'Link': link
                    })
            except Exception as batch_err:
                print(f"Batch {batch_start} error: {batch_err}")
                continue

        if new_rows:
            return pd.DataFrame(new_rows)
        return pd.DataFrame()  # Empty triggers fallback display
    except Exception as e:
        print(f"Optimization Error: {e}")
        import traceback; traceback.print_exc()
        return pd.DataFrame()  # Empty triggers fallback display

# Load Mercadona Data separately for search tool
@st.cache_data
def load_mercadona_db():
    try:
        if os.path.exists("mercadona_prices.csv"):
            return pd.read_csv("mercadona_prices.csv")
    except:
        pass
    return pd.DataFrame()

# Generate dummy recipe dataset or load from CSV if available
@st.cache_data
def load_recipe_data():
    # Use relative path so it works on any machine (Git friendly)
    script_dir = os.path.dirname(os.path.abspath(__file__))
    
    # Path to the new Food.com dataset logic
    # Looking for 'Food.com - Recipes/recipes.csv' (Real dataset)
    csv_path = os.path.join(script_dir, "Food.com - Recipes", "recipes.csv")
    prices_path = os.path.join(script_dir, "Food.com - Recipes", "ingredient_prices_synthetic.csv")
    
    mercadona_path = os.path.join(script_dir, "mercadona_prices.csv")
    price_map = {}
    url_map = {}
    
    try:
        # Load Mercadona (REAL DATA)
        if os.path.exists(mercadona_path):
            try:
                m_df = pd.read_csv(mercadona_path)
                m_df = m_df[m_df['price'] > 0]
                
                # Check each English ingredient for Spanish term match
                for eng_key, span_term in ENGLISH_TO_SPANISH.items():
                    matches = m_df[m_df['name'].str.contains(span_term, case=False, na=False)]
                    if not matches.empty:
                        # Average price
                        avg_p = matches['price'].mean()
                        
                        # Get a logical URL (e.g. the first match or cheapest)
                        # Let's save the first one for direct linking
                        product_url = matches.iloc[0]['url'] if 'url' in matches.columns else ""
                        if not product_url and 'id' in matches.columns:
                             product_url = f"https://tienda.mercadona.es/product/{matches.iloc[0]['id']}/"

                        # Apply naive unit normalization
                        if any(x in eng_key for x in ['chicken', 'beef', 'pork', 'rice', 'pasta', 'beans', 'lentils', 'flour', 'sugar']):
                            avg_p = avg_p / 4.0
                        elif 'egg' in eng_key:
                             avg_p = avg_p / 12.0
                        elif 'milk' in eng_key:
                             avg_p = avg_p / 4.0
                             
                        price_map[eng_key] = avg_p
                        
                        # Use dict for metadata
                        url_map[eng_key] = {
                            'url': product_url,
                            'price': avg_p,
                            'original_price': matches['price'].mean(),
                            'image': matches.iloc[0]['thumbnail'] if 'thumbnail' in matches.columns else ""
                        }
                        
                # Removed st.toast from inside cached function to avoid replay errors
            except Exception as e:
                print(f"Error processing Mercadona prices: {e}")
        
        # Fallback if map empty
        if not price_map and os.path.exists(prices_path):
             # Try synthetic/old file as fallback
             try:
                p_df = pd.read_csv(prices_path)
                for _, row in p_df.iterrows():
                    p = row['price']
                    if p <= 0: p = 0.05
                    price_map[row['ingredient'].lower().strip()] = p
             except: pass


        # Load the raw dataset (Limit to 5000 rows for performance)
        # Increased load to capture more variety after filtering
        df = pd.read_csv(csv_path, nrows=20000)
        
        # --- Strict Category/Keyword Filter (User Request) ---
        # Exclude obvious "non-real-food" categories unless specifically asked
        # Terms to KEEP (Wholesome / Real Meals)
        allowed_terms = [
            "yams", "sweet potato", "winter", "whole turkey", "whole duck", "whole chicken", "white fish", 
            "white rice", "wheat bread", "vietnamese", "weeknight", "very low carbs", "venezuelan", "vegan", 
            "vegetable", "veal", "turkish", "turkey breast", "tuna", "trout", "tropical fruits", "thai", 
            "swiss", "szechuan", "summer", "summer dip", "steak", "steamed", "stew", "squid", "spread", 
            "spinach", "spanish", "spaghetti sauce", "south american", "southwest asia", "middle east", 
            "southwestern u.s.", "south americans", "south african", "shakes", "short grain rice", 
            "small appliances", "scandinavian", "roast beef", "crockpot", "rabbit", "rice", "roast", 
            "poultry", "potato", "pot roast", "pot pie", "polynesian", "portuguese", "pineapple", "plums", 
            "peruvian", "pheasant", "peppers", "penne", "peanut butter", "peanut butter pie", "pasta", 
            "pasta shells", "palestinians", "oatmeal", "nuts", "norwegian", "no shellfish", "new zealand", 
            "native american", "meatloaf", "lebanese", "low cholesterol", "kiwi fruit", "japanese", 
            "inexpensive", "indonesian", "ice cream", "high protein", "high fiber", "healthy", "creams", 
            "greek", "grains", "grape", "gluten-free appetizers", "gelatin", "fruit", "from scratch", 
            "freezer", "european", "egyptian", "duck", "duck breasts", "cuban", "creole", 
            "chicken thigh and leg", "chicken crockpot", "chicken breast", "chicken", 
            "cherries", "cheese", "chard", "broccoli soup", "broiled grill", "brown rice", "breakfast eggs", 
            "breakfast casseroles", "beverages", "beef liver", "beef organ meats", "beginner cook", "apple", 
            "asian", "under 60 minutes", "under 4 hours", "under 30 minutes", "under 15 minutes"
        ]
        
        # Terms to explicitly BLOCK (Candy, pure sugar, etc)
        # Even if they match "vegan", we don't want them unless user asks for Junk Food specifically in the app
        # But for now, we Clean the Base Dataset.
        blocked_terms = [
             "candy", "candies", "lollipop", "fudge", "taffy", "marshmallow", "gummy", "gummi", "caramel popcorn",
             "cotton candy", "hard candy", "chewing gum", "toffee", "brittle", "praline", "truffle"
        ]
        
        # Normalize terms for matching
        allowed_set = set(t.lower() for t in allowed_terms)
        blocked_set = set(t.lower() for t in blocked_terms)
        
        def is_allowed(row):
            # Check Category
            cat = str(row.get('RecipeCategory', '')).lower()
            keywords = str(row.get('Keywords', '')).lower()
            
            # BLOCK First
            if any(b in cat for b in blocked_set) or any(b in keywords for b in blocked_set):
                 return False
                 
            # PERMIT Second
            if cat in allowed_set: return True
            
            # Keyword Check
            for term in allowed_set:
                if term in cat or term in keywords:
                    return True
            return False

        # Apply Filter
        mask = df.apply(is_allowed, axis=1)
        df = df[mask].reset_index(drop=True)
        
        if df.empty:
            # Fallback if filter killed everything (e.g. strict naming mismatch)
            # Reload basic set without filter to avoid crash
            df = pd.read_csv(csv_path, nrows=500)
        
        df.rename(columns={
            'Name': 'name',
            'Calories': 'calories',
            'ProteinContent': 'protein',
            'CarbohydrateContent': 'carbs',
            'FatContent': 'fat'
        }, inplace=True)
        
        # Ensure 'AggregatedRating' exists for optimization (default to 0 if missing)
        if 'AggregatedRating' not in df.columns:
            df['AggregatedRating'] = 0.0
        else:
             df['AggregatedRating'] = df['AggregatedRating'].fillna(0.0)
        
        # 1. Parse Prep Time (Format PT45M or PT24H45M)
        def parse_iso_duration(duration_str):
            if pd.isna(duration_str) or not isinstance(duration_str, str):
                return 30 # Default
            try:
                # Simple parser for minutes
                import re
                minutes = 0
                hours = 0
                
                h_match = re.search(r'(\d+)H', duration_str)
                if h_match:
                    hours = int(h_match.group(1))
                    
                m_match = re.search(r'(\d+)M', duration_str)
                if m_match:
                    minutes = int(m_match.group(1))
                    
                return (hours * 60) + minutes
            except:
                return 30
                
        # Use TotalTime if available, else PrepTime, else CookTime
        if 'TotalTime' in df.columns:
            df['prep_time'] = df['TotalTime'].apply(parse_iso_duration)
        elif 'PrepTime' in df.columns:
             df['prep_time'] = df['PrepTime'].apply(parse_iso_duration)
        else:
             df['prep_time'] = 30
             
        # 2. Combine Ingredients & Calculate Cost
        def process_ingredients_and_cost(row):
            parts_str = row['RecipeIngredientParts']
            quant_str = row['RecipeIngredientQuantities']
            
            # Helper to parse R vector string to list
            def parse_r_vector(s):
                if not isinstance(s, str): return []
                s = s.strip()
                if s.startswith('c(') and s.endswith(')'):
                    s = s[2:-1]
                # Improved split that ignores comma inside quotes?
                # For now simple split is okay for 90% cases
                items = [x.strip().strip('"') for x in s.split('",')]
                return items

            parts = []
            quants = []
            try:
                parts = parse_r_vector(parts_str)
                quants = parse_r_vector(quant_str)
            except:
                pass
            
            combined_list = []
            detailed_items = []
            total_recipe_cost = 0.0
            
            for i in range(len(parts)):
                p_name = parts[i]
                q_val = quants[i] if i < len(quants) else ""
                combined_list.append(f"{q_val} {p_name}".strip())
                
                # Store structured data for shopping list
                detailed_items.append({"q": q_val, "i": p_name})
                
                # Check price map
                p_lower = p_name.lower().strip()
                item_price = 0.20 # Default fallback
                
                if p_lower in price_map:
                    item_price = price_map[p_lower]
                else:
                    # Try partial match logic if not exact
                    for key in price_map:
                        if key in p_lower:
                            item_price = price_map[key]
                            break
                            
                total_recipe_cost += item_price

            # Ensure minimum cost for a meal
            if total_recipe_cost < 2.50: total_recipe_cost = 2.50 + (len(parts) * 0.15)
            
            ingredients_display = ", ".join(combined_list) if combined_list else "Assorted Ingredients"
            import json
            ingredients_json = json.dumps(detailed_items)
            return pd.Series([ingredients_display, ingredients_json, total_recipe_cost])

        # Apply logic
        result_df = df.apply(process_ingredients_and_cost, axis=1, result_type='expand')
        df['ingredients'] = result_df[0]
        df['ingredients_json'] = result_df[1]
        df['cost'] = result_df[2]
        
        # Save URL map to dataframe attributes
        # We need to access this later outside the cached function
        # A common trick is to return it or attach it. 
        # Attaching to df.attrs persists through cache in recent Pandas/Streamlit versions.
        df.attrs['url_map'] = url_map
        
        # Clean NaNs in numeric columns and ensure correct dtype
        df['calories'] = pd.to_numeric(df['calories'], errors='coerce').fillna(500).astype(float)
        df['protein'] = pd.to_numeric(df['protein'], errors='coerce').fillna(20).astype(float)
        df['carbs'] = pd.to_numeric(df['carbs'], errors='coerce').fillna(50).astype(float)
        df['fat'] = pd.to_numeric(df['fat'], errors='coerce').fillna(20).astype(float)
        df['cost'] = pd.to_numeric(df['cost'], errors='coerce').fillna(8.0).astype(float)
        
        return df
        
    except FileNotFoundError:
        print(f"Food.com dataset not found at {csv_path}. Using mock data.")
    except Exception as e:
        print(f"Error loading dataset: {e}. Using mock data.")
    
    # Mocking RecipeNLG dataset with nutritional info, cost, and time
    np.random.seed(42)
    num_recipes = 100
    
    recipe_names = [
        "Chicken Salad", "Beef Stir Fry", "Vegetable Curry", "Salmon with Asparagus",
        "Quinoa Bowl", "Turkey Meatballs", "Lentil Soup", "Shrimp Tacos",
        "Tofu Scramble", "Pork Chops", "Eggplant Parmesan", "Chicken Fajitas",
        "Beef Stew", "Mushroom Risotto", "Tuna Salad", "Chickpea Salad",
        "Chicken Parmesan", "Beef Tacos", "Vegetable Stir Fry", "Salmon Salad"
    ]
    
    ingredients_pool = [
        "Chicken", "Beef", "Pork", "Salmon", "Tuna", "Shrimp", "Turkey", "Tofu",
        "Lentils", "Chickpeas", "Quinoa", "Rice", "Pasta", "Potatoes", "Sweet Potatoes",
        "Broccoli", "Asparagus", "Spinach", "Kale", "Carrots", "Bell Peppers", "Onions",
        "Garlic", "Tomatoes", "Mushrooms", "Zucchini", "Eggplant", "Avocado", "Cheese",
        "Milk", "Eggs", "Butter", "Olive Oil", "Soy Sauce", "Salt", "Pepper"
    ]
    
    recipes = []
    for i in range(num_recipes):
        name = random.choice(recipe_names) + f" {i}"
        calories = np.random.randint(300, 800)
        protein = np.random.randint(15, 60)
        carbs = np.random.randint(20, 80)
        fat = np.random.randint(10, 40)
        
        # Adjust calories to roughly match macros (Protein: 4, Carbs: 4, Fat: 9)
        calories = (protein * 4) + (carbs * 4) + (fat * 9)
        
        prep_time = np.random.randint(10, 60)
        cost = round(np.random.uniform(3.0, 15.0), 2)
        
        num_ingredients = np.random.randint(4, 10)
        recipe_ingredients = random.sample(ingredients_pool, num_ingredients)
        
        recipes.append({
            "id": i,
            "name": name,
            "calories": calories,
            "protein": protein,
            "carbs": carbs,
            "fat": fat,
            "prep_time": prep_time,
            "cost": cost,
            "ingredients": ", ".join(recipe_ingredients)
        })
        
    return pd.DataFrame(recipes)

# Optimization function
def optimize_meal_plan(df, target_calories, target_protein, target_carbs, target_fat,
                       max_budget, max_time, dislikes, days, selected_slots, cuisine_prefs, cuisine_map=None, people_count=1, variability="High", liked_names=None):

    
    # Filter out dislikes
    if dislikes:
        dislike_list = [d.strip().lower() for d in dislikes.split(',')]
        mask = df['ingredients'].apply(lambda x: not any(d in x.lower() for d in dislike_list))
        filtered_df = df[mask].copy()
    else:
        filtered_df = df.copy()
        
    # Filter by max time
    filtered_df = filtered_df[filtered_df['prep_time'] <= max_time]
    
    # Filter by Cuisine Preferences
    if cuisine_prefs:
        # Determine strictness of "Healthy" filter
        # If "Healthy" is selected, force exclusion of junk terms
        # If "Junk Food" is NOT selected, force exclusion of obvious desserts
        
        is_healthy_selected = "Healthy" in cuisine_prefs
        is_junk_selected = "Junk Food" in cuisine_prefs
        
        # Terms that clearly indicate a dessert/sweet/junk item
        # We only apply this filter if the user *didn't* ask for Junk Food.
        junk_indicators = ["dessert", "cookie", "cake", "brownie", "cupcake", "pie", "tart", "pudding", "ice cream", "chocolate", "sweet", "candy"]
        
        if not is_junk_selected:
             # Exclude these
             def is_not_junk(row):
                 text = (str(row.get('Keywords', '')) + " " + str(row.get('name', ''))).lower()
                 for j in junk_indicators:
                     if j in text: return False
                 return True
             filtered_df = filtered_df[filtered_df.apply(is_not_junk, axis=1)]
        
        # User Logic: If "Any" is selected from the UI multiselect, we treat it as "No positive filter".
        # But if they selected specific cuisines (e.g. "Italian", "Healthy"), we filter FOR those.
        
        selected_real_cuisines = [c for c in cuisine_prefs if c != "Any"]
        
        if selected_real_cuisines: 
             # Use the map if available, otherwise fallback to simple match
             def match_cuisine(keywords_str):
                if not isinstance(keywords_str, str): return False
                k_lower = keywords_str.lower()
                
                for selected in selected_real_cuisines:
                    # Check if selected is a key in the map
                    if cuisine_map and selected in cuisine_map:
                        # Check if ANY of the mapped keywords are present
                        aliases = cuisine_map[selected]
                        if any(alias in k_lower for alias in aliases):
                            return True
                    else:
                        # Fallback: Check exact match of title
                        if selected.lower() in k_lower:
                            return True
                return False
            
             # Bug Fix: Ensure 'Keywords' column exists before accessing it
             if 'Keywords' not in filtered_df.columns:
                 # It might have been dropped or the mock data doesn't have it.
                 # Mock data has lowercase 'keywords' but Food.com has 'Keywords'.
                 # Let's try to normalize or check.
                 if 'keywords' in filtered_df.columns:
                     filtered_df['Keywords'] = filtered_df['keywords']
                 else:
                     # Create empty if missing so filter doesn't crash
                     filtered_df['Keywords'] = ""
                     
             filtered_df = filtered_df[filtered_df['Keywords'].apply(match_cuisine)]
    
    if len(filtered_df) < len(selected_slots):
        return None, "Not enough recipes match your criteria (Time/Cuisine). Try relaxing constraints."
        
    # Pre-classify recipes for slots to avoid doing it inside the loop
    # Breakfast: Category 'Breakfast' or Keyword 'breakfast', exluding Alcohol
    # Snack: Category 'Beverages', 'Dessert', 'Lunch/Snacks', 'Vegetable', 'Fruit', Keyword 'snack'
    # Main (Lunch/Dinner): Category 'Main Dish', 'Meat', 'Chicken', 'Vegetable', NOT 'Dessert', NOT 'Beverages'
    
    # Helper to check keywords
    def has_keyword(text, key):
        if not isinstance(text, str): return False
        return key in text.lower()
    
    # Helper to check category
    def check_cat(val, valid_cats):
        if not isinstance(val, str): return False
        return val in valid_cats
        
    # Create masks with improved logic
    # Ensure columns exist
    if 'RecipeCategory' not in filtered_df.columns: filtered_df['RecipeCategory'] = ""
    if 'Keywords' not in filtered_df.columns:
         if 'keywords' in filtered_df.columns:
             filtered_df['Keywords'] = filtered_df['keywords']
         else:
             filtered_df['Keywords'] = ""
             
    cats = filtered_df['RecipeCategory'].fillna("").astype(str)
    keys = filtered_df['Keywords'].fillna("").astype(str)
    names = filtered_df['name'].fillna("").astype(str)

    # Helper for broader keyword search
    def check_keywords(series, keywords):
        return series.apply(lambda x: any(k in x.lower() for k in keywords))

    # 1. Breakfast Mask
    # Must explicitly be breakfast-like
    # Exclude desserts, soups, main dishes unless specifically marked breakfast
    breakfast_keywords = ['breakfast', 'brunch', 'oatmeal', 'pancake', 'waffle', 'toast', 'omelet', 'egg', 'cereal', 'granola', 'yogurt']
    is_breakfast = (
        cats.isin(['Breakfast', 'Breads', 'Quick Breads', 'Grains', 'Yeast Breads']) | 
        check_keywords(keys, breakfast_keywords) |
        check_keywords(names, breakfast_keywords)
    ) & ~cats.isin(['Beverages', 'Alcoholic Beverages', 'Soup', 'Stew', 'Chili']) & \
      ~check_keywords(names, ['whiskey', 'cocktail', 'margarita', 'martini', 'bomb', 'shot', 'liqueur'])
    
    # 2. Snack Mask
    # Can be almost anything light, but typically desserts, beverages, fruits, veggies
    snack_keywords = ['snack', 'appetizer', 'dip', 'smoothie', 'shake', 'bites', 'bar', 'muffin', 'cookie']
    is_snack = (
        cats.isin(['Lunch/Snacks', 'Beverages', 'Dessert', 'Vegetable', 'Fruit', 'Berries', 'Pie', 'Bar Cookie', 'Candy', 'Drop Cookies', 'Cheesecake', 'Quick Breads']) |
        check_keywords(keys, snack_keywords) |
        check_keywords(names, snack_keywords)
    ) & ~cats.isin(['Alcoholic Beverages', 'Main Dish', 'Meat', 'Chicken', 'Pork', 'Beef', 'Stew'])
    
    # 3. Main Meal Mask (Lunch/Dinner)
    # Substantial food. Exclude desserts and tiny snacks.
    main_keywords = ['dinner', 'lunch', 'main', 'entree', 'casserole', 'pasta', 'pizza', 'sandwich', 'burger', 'steak', 'curry', 'roast', 'stew', 'soup', 'chili', 'salad']
    
    # User Request: "French toast isn't a meal that we eat on during lunch"
    # We need to exclude strict breakfast items from "Main" if they aren't also lunch items.
    # We defines strict breakfast categories to exclude from Lunch/Dinner
    strict_breakfast_cats = ['Breakfast', 'Pancakes', 'Waffles', 'French Toast']
    strict_breakfast_kws = ['pancake', 'waffle', 'french toast', 'cereal', 'oatmeal']

    is_main = (
        ~cats.isin(['Beverages', 'Alcoholic Beverages', 'Dessert', 'Frozen Desserts', 'Candy', 'Pie', 'Bar Cookie', 'Cheesecake', 'Drop Cookies']) &
        ~cats.isin(strict_breakfast_cats) & 
        ~check_keywords(keys, strict_breakfast_kws) &
        ~check_keywords(names, strict_breakfast_kws) &
        (
            cats.isin(['Chicken', 'Chicken Breast', 'Poultry', 'Meat', 'Vegetable', 'Pork', 'Beef', 'Main Dish', 'Lunch/Snacks', 'One Dish Meal', 'Potato', 'Stew', 'Chili', 'Soup', 'Pasta', 'Rice', 'Beans']) |
            check_keywords(keys, main_keywords) |
            (pd.to_numeric(filtered_df['protein'], errors='coerce').fillna(0) > 15) | # High protein usually main
            (pd.to_numeric(filtered_df['calories'], errors='coerce').fillna(0) > 300) # Substantial calories
        )
    ) & ~check_keywords(names, ['whiskey', 'cocktail', 'margarita']) # Double check no alcohol

    valid_indices = filtered_df.index.tolist()
    
    weekly_plan = []
    
    # Variability Logic
    # Start fresh each day unless Low Variability
    
    # Identify valid indices once
    valid_map = {}
    for s_idx, slot in enumerate(selected_slots):
        slot_lower = slot.lower()
        if 'breakfast' in slot_lower:
            valid_map[s_idx] = [i for i in valid_indices if is_breakfast[i]]
        elif 'snack' in slot_lower:
             valid_map[s_idx] = [i for i in valid_indices if is_snack[i]]
        else:
             valid_map[s_idx] = [i for i in valid_indices if is_main[i]]

    # If variability is LOW, solve for 1 day and reuse plan.
    # If variability is MEDIUM, reuse some days (e.g. solve for Day 1, use for Day 1-3, Solve Day 4, use for 4-7)
    # If variability is HIGH, solve everyday.
    
    days_to_solve = list(range(days))
    day_mapping = {d: d for d in range(days)} # Map display_day -> solved_day_index
    
    is_low_var = "Low" in variability
    is_med_var = "Medium" in variability
    
    if is_low_var:
        # Solve only Day 0, map all others to Day 0
        days_to_solve = [0]
        for d in range(days): day_mapping[d] = 0
    elif is_med_var:
        # Solve Day 0 (for 0,1,2), Day 3 (for 3,4), Day 5 (for 5,6) - specific pattern or simple repeats
        # Let's say we cook every 2 days
        days_to_solve = [d for d in range(days) if d % 2 == 0]
        for d in range(days): day_mapping[d] = d - (d % 2) # 0->0, 1->0, 2->2, 3->2
    
    # Store solved plans
    solved_plans = {}
    
    for day in days_to_solve:
        prob = pulp.LpProblem(f"Meal_Optimization_Day_{day}", pulp.LpMaximize)
        
        # Variables: x[slot_index][recipe_id]
        x = {}
        
        # Identify valid recipes for each slot dynamically to reduce search space
        slot_indices_map = {}
        
        # We limit sample size to keep LP fast but allow variety if High mode
        limit = 300
        if is_low_var: limit = 500 # Search deeper for the ONE perfect plan
        
        for s_idx, slot in enumerate(selected_slots):
            cands = valid_map[s_idx]
            if not cands:
                return None, f"No suitable recipes found for '{slot}'."
            
            # Shuffle annually to ensure different result on re-run
            import random
            if len(cands) > limit:
                cands = random.sample(cands, limit)
            slot_indices_map[s_idx] = cands

        # --- Linear Programming (PuLP) ---
        # Guarantees optimal solution for complex constraints.
        
        # Helper to avoid stale prob variable from loop start
        # prob is already defined above: prob = pulp.LpProblem(...)
        
        # 1. Variables
        # Flatten candidates to create binary vars x_s_r
        # We need to map (slot_idx, recipe_idx) -> LpVariable
        
        lp_vars = {} # key: (s_idx, r_idx), value: LpVariable
        vars_for_slot = {s_idx: [] for s_idx in range(len(selected_slots))}
        
        # Objectives components
        obj_rating = []
        
        # Constraint components
        total_cals = []
        total_prot = []
        total_carb = []
        total_fat = []
        total_cost = []
        
        slot_cal_exprs = {s_idx: [] for s_idx in range(len(selected_slots))}
        
        for s_idx in range(len(selected_slots)):
            candidates = slot_indices_map[s_idx]
            
            # If no candidates, we fail immediately (safeguard)
            if not candidates: 
                 return None, f"No recipes found for {selected_slots[s_idx]}."

            for r_idx in candidates:
                # Unique name
                v_name = f"x_{day}_{s_idx}_{r_idx}"
                v = pulp.LpVariable(v_name, cat=pulp.LpBinary)
                
                lp_vars[(s_idx, r_idx)] = v
                vars_for_slot[s_idx].append(v)
                
                # Get Stats
                # Use .at for speed? or loc
                # filtered_df might be fragmented, better to access once? 
                # Actually, filtered_df.loc[r_idx] is fine for typical sizes.
                # To speed up, we can extract arrays first, but let's trust PuLP build speed for <1000 vars.
                
                cal = float(filtered_df.at[r_idx, 'calories'] or 0)
                prot = float(filtered_df.at[r_idx, 'protein'] or 0)
                carb = float(filtered_df.at[r_idx, 'carbs'] or 0)
                fat = float(filtered_df.at[r_idx, 'fat'] or 0)
                cost = float(filtered_df.at[r_idx, 'cost'] or 0)
                rating = filtered_df.at[r_idx, 'AggregatedRating']
                if pd.isna(rating): rating = 0
                rating = float(rating)

                # Boost rating for previously liked recipes so LP strongly prefers them
                recipe_name = str(filtered_df.at[r_idx, 'name']) if 'name' in filtered_df.columns else ''
                if liked_names and recipe_name in liked_names:
                    rating += 10.0

                # Add to expressions
                total_cals.append(v * cal)
                total_prot.append(v * prot)
                total_carb.append(v * carb)
                total_fat.append(v * fat)
                total_cost.append(v * cost)
                obj_rating.append(v * rating)
                
                slot_cal_exprs[s_idx].append(v * cal)
                
            # Constraint: Exactly one recipe per slot
            prob += pulp.lpSum(vars_for_slot[s_idx]) == 1

        # 2. Constraints
        
        # Budget
        prob += pulp.lpSum(total_cost) <= max_budget
        
        # Nutrition (Relaxed +/- 15%)
        c_sum = pulp.lpSum(total_cals)
        prob += c_sum >= target_calories * 0.85
        prob += c_sum <= target_calories * 1.15
        
        p_sum = pulp.lpSum(total_prot)
        # Relax protein a bit more +/- 20%
        prob += p_sum >= target_protein * 0.8
        prob += p_sum <= target_protein * 1.2
        
        # 3. Distribution Rules (Lunch > Breakfast > Dinner)
        # Find which index corresponds to which slot type
        lunch_idx = -1
        break_idx = -1
        dinner_idx = -1
        
        for idx, s_name in enumerate(selected_slots):
            sl = s_name.lower()
            if 'lunch' in sl: lunch_idx = idx
            elif 'breakfast' in sl: break_idx = idx
            elif 'dinner' in sl: dinner_idx = idx
            
        if lunch_idx != -1 and break_idx != -1:
            # Lunch Calories >= Breakfast Calories + 10
            prob += pulp.lpSum(slot_cal_exprs[lunch_idx]) >= pulp.lpSum(slot_cal_exprs[break_idx]) + 10
            
        if lunch_idx != -1 and dinner_idx != -1:
            prob += pulp.lpSum(slot_cal_exprs[lunch_idx]) >= pulp.lpSum(slot_cal_exprs[dinner_idx]) + 10
            
        if break_idx != -1 and dinner_idx != -1:
             prob += pulp.lpSum(slot_cal_exprs[break_idx]) >= pulp.lpSum(slot_cal_exprs[dinner_idx]) + 10

        # 4. Objective
        # Maximize Rating
        prob += pulp.lpSum(obj_rating)
        
        # Solve
        # 5 second timeout is generous for this size
        prob.solve(pulp.PULP_CBC_CMD(msg=0, timeLimit=5))
        
        if pulp.LpStatus[prob.status] == 'Optimal':
            best_plan = []
            # Extract chosen indices
            for s_idx in range(len(selected_slots)):
                # Find the var that is 1
                found = False
                candidates = slot_indices_map[s_idx]
                for r_idx in candidates:
                    v = lp_vars.get((s_idx, r_idx))
                    if v and v.varValue and v.varValue > 0.5:
                        best_plan.append(r_idx)
                        found = True
                        break
                if not found:
                    # Should not happen if optimal
                    best_plan = None
                    break
            solved_plans[day] = best_plan
        else:
             # If LP Fails, fallback to random valid choice if possible or break
             # Let's skip to ensure the loop continues? No, day by day.
             best_plan = None

        if best_plan is None:
            # If no valid plan found (e.g. budget too low), just pick the last valid logic
            # Or return error. Let's try to return error to notify user.
            return None, f"Could not find a meal combination for Day {day+1} within Budget/Constraints. (Status: {pulp.LpStatus[prob.status]})"

    # Construct Full Plan
    for real_day in range(days):
        mapped_day = day_mapping[real_day]
        best_plan = solved_plans.get(mapped_day)
        
        if not best_plan:
             return None, "Optimization Failed."
             
        # Extract Selection
        day_records = []
        for s_idx, r_idx in enumerate(best_plan):
            rec = filtered_df.loc[r_idx].copy()
            rec['Day'] = f"Day {real_day+1}"
            rec['Meal'] = selected_slots[s_idx]
            
            # Apply Household Size Scaling to Cost (for display)
            rec['People'] = people_count
            
            day_records.append(rec)
                 
        # start_idx = len(weekly_plan) * len(selected_slots) # unused
        df_day = pd.DataFrame(day_records)
        weekly_plan.append(df_day)
        
    full_plan = pd.concat(weekly_plan, ignore_index=True)
    return full_plan, "Success"

# UI Setup
st.set_page_config(page_title="Grocery Trip Optimizer", layout="wide")
st.title("🛒 Grocery Trip Optimizer")

# Load Data
try:
    df_recipes = load_recipe_data()
    # Extract url_map if available
    if hasattr(df_recipes, 'attrs') and 'url_map' in df_recipes.attrs:
        st.session_state['ingredient_url_map'] = df_recipes.attrs['url_map']
        st.toast("Loaded Mercadona prices!", icon="🛒")

except Exception as e:
    st.error(f"Error loading recipes: {e}")
    df_recipes = pd.DataFrame()

# Sidebar Inputs
st.sidebar.header("Your Preferences")
days = st.sidebar.slider("Time Horizon (Days)", 1, 14, 7)

st.sidebar.subheader("Meals & Cuisines")
# Multi-select for meal slots
available_slots = ["Breakfast", "Morning Snack", "Lunch", "Afternoon Snack", "Dinner"]
selected_slots = st.sidebar.multiselect(
    "Select Meals per Day",
    available_slots,
    default=["Breakfast", "Lunch", "Dinner"]
)

# Cuisine Preference
# Mapping Display Title -> List of Keywords/Categories
cuisine_map = {
    "American": ["american", "burger", "sandwich", "steak", "casserole", "comfort food", "soul", "southern", "southwestern u.s.", "cajun"],
    "Italian": ["italian", "pasta", "pizza", "risotto", "spaghetti", "lasagna", "tuscan", "sicilian", "roman"],
    "Mexican/Latin": ["mexican", "taco", "burrito", "enchilada", "salsa", "guacamole", "quesadilla", "fajita", "south american", "brazilian", "argentinian", "cuban", "peruvian", "venezuelan"],
    "Asian": ["asian", "chinese", "japanese", "thai", "vietnamese", "indian", "korean", "filipino", "indonesian", "sushi", "stir fry", "curry", "ramen", "teriyaki", "szechuan"],
    "Mediterranean": ["mediterranean", "greek", "turkish", "lebanese", "middle eastern", "egyptian", "spanish", "portuguese", "hummus", "falafel", "couscous"],
    "French": ["french", "quiche", "souffle", "crepe", "provencal"],
    "European": ["european", "german", "polish", "scandinavian", "swiss", "austrian", "english", "uk", "irish", "scottish"],
    "Healthy": ["healthy", "low carb", "low fat", "high protein", "keto", "paleo", "vegan", "vegetarian", "gluten free", "salad", "sugar free"],
    "Junk Food": ["deep fried", "fried", "junk food", "fast food", "processed", "candy", "chips", "fries", "onion rings", "greasy", "cheese sauce", "battered"]
}

available_cuisines = ["Any"] + list(cuisine_map.keys())
cuisine_prefs = st.sidebar.multiselect(
    "Preferred Cuisines",
    available_cuisines,
    default=["Any"]
)

st.sidebar.subheader("Daily Nutritional Targets")
target_calories = st.sidebar.number_input("Calories (kcal)", 1000, 5000, 2000)
target_protein = st.sidebar.number_input("Protein (g)", 10, 300, 150)
target_carbs = st.sidebar.number_input("Carbs (g)", 10, 500, 200)
target_fat = st.sidebar.number_input("Fat (g)", 10, 200, 65)

st.sidebar.subheader("Constraints")
max_budget = st.sidebar.number_input("Max Daily Budget (€)", 5.0, 100.0, 20.0)
max_time = st.sidebar.number_input("Max Cooking Time per Meal (mins)", 5, 120, 30)
people_count = st.sidebar.number_input("Household Size (People)", 1, 10, 1)
variability = st.sidebar.select_slider("Meal Variety", options=["Low (Batch Cooking)", "Medium", "High (New Meal Every Day)"], value="High (New Meal Every Day)")
dislikes = st.sidebar.text_input("Dislikes/Allergies (comma separated)", "Mushrooms, Eggplant")

st.sidebar.markdown("---")
st.sidebar.subheader("📌 Pin Specific Recipes")
_pin_search = st.sidebar.text_input("Search recipe to pin", "", key="pin_search_input")
if _pin_search and len(_pin_search) >= 2:
    _matches = df_recipes[df_recipes['name'].str.contains(_pin_search, case=False, na=False)]['name'].head(8).tolist() if not df_recipes.empty else []
    if _matches:
        _to_pin = st.sidebar.selectbox("Select to pin", [""] + _matches, key="pin_selectbox")
        if _to_pin and _to_pin not in st.session_state.pinned_recipes:
            if st.sidebar.button("➕ Add to Plan", key="pin_add_btn"):
                st.session_state.pinned_recipes.append(_to_pin)
                st.rerun()
    else:
        st.sidebar.caption("No matches found.")
if st.session_state.pinned_recipes:
    st.sidebar.markdown("**Pinned meals:**")
    for _pr in list(st.session_state.pinned_recipes):
        c1, c2 = st.sidebar.columns([4, 1])
        c1.caption(f"📌 {_pr[:30]}")
        if c2.button("✕", key=f"unpin_{_pr}"):
            st.session_state.pinned_recipes.remove(_pr)
            st.rerun()

# Tabs
tabs = st.tabs(["Meal Plan Optimizer", "Leftover Pantry", "History", "Recipe Forum"])

with tabs[0]:
    st.header("Generate Your Optimized Meal Plan")
    
    col_opt, col_val = st.columns(2)
    
    # Validation Logic State
    if 'validation_step' not in st.session_state:
        st.session_state.validation_step = 0 # 0=None, 1=PlanGenerated, 2=ListGenerated

    # Explicit button for including pinned recipes

    if col_opt.button("Validate Meal Plan"):
        plan_df = None
        msg = ""

        if not selected_slots:
            st.error("Please select at least one meal slot.")
        else:
            with st.spinner("Optimizing your meals..."):
                # Merge user-added recipes (from Recipe Forum) with main dataset
                combined_df = df_recipes.copy()
                if st.session_state.user_recipes:
                    user_df = pd.DataFrame(st.session_state.user_recipes)
                    combined_df = pd.concat([combined_df, user_df], ignore_index=True)

                plan_df, msg = optimize_meal_plan(
                    combined_df, target_calories, target_protein, target_carbs, target_fat,
                    max_budget, max_time, dislikes, days, selected_slots, cuisine_prefs,
                    cuisine_map=cuisine_map, people_count=people_count, variability=variability,
                    liked_names=st.session_state.get('liked_recipe_names', set())
                )


            if plan_df is not None:
                st.session_state.meal_plan = plan_df
                st.session_state.validation_step = 1 # Plan Ready

                # Clear previous shopping list until validated
                st.session_state.shopping_list = None
                st.session_state.shopping_list_display = pd.DataFrame()

            else:
                st.error(msg)
    
    # "Validate Grocery List" Button - Only show if Plan is ready
    if st.session_state.meal_plan is not None:
         if st.button("Validate Grocery List"):
                plan_df = st.session_state.meal_plan
                # Generate Shopping List Logic (Moved here)
                url_map = df_recipes.attrs.get('url_map', {})
                all_items = []
                
                # Check if we have structured JSON in the plan
                has_json = 'ingredients_json' in plan_df.columns
                
                for idx, row in plan_df.iterrows():
                    # Parse ingredients
                    item_list = []
                    people_n = int(row.get('People', 1))
                    
                    if has_json and isinstance(row['ingredients_json'], str):
                        try:
                            import json
                            # JSON structure: [{"q": "2", "i": "garlic"}, ...]
                            loaded = json.loads(row['ingredients_json'])
                            for x in loaded:
                                # Multiply logic later or repeat rows
                                item_list.append((x.get('q',""), x.get('i',"")))
                        except:
                            # Fallback
                            pass
                            
                    if not item_list:
                        pass # Fallback check below

                    if not item_list:
                        # Fallback to string split
                        raw_ings_str = row.get('ingredients', "")
                        if pd.isna(raw_ings_str): raw_ings_str = ""
                        raw_ings = [i.strip() for i in raw_ings_str.split(',')]
                        for ing in raw_ings:
                            if ing:
                                item_list.append(("", ing))

                    for q_val, ing_name in item_list:
                        if not ing_name: continue
                        
                        ing_lower = ing_name.lower().strip()
                        item_meta = None
                        
                        # exact match
                        if ing_lower in url_map:
                            item_meta = url_map[ing_lower]
                        else:
                            # fuzzy
                            for k, v in url_map.items():
                                if k in ing_lower:
                                    item_meta = v
                                    break
                        
                        price = 0.0
                        img = ""
                        url = ""
                        
                        # Only add if NOT in Pantry? Or we handle logic later?
                        # For now, generate full list. User validates removal.
                        
                        if item_meta:
                            if isinstance(item_meta, dict):
                                price = item_meta.get('price', 0.0)
                                img = item_meta.get('image', "")
                                url = item_meta.get('url', "")
                            else:
                                # Legacy string format
                                pass
                        
                        # Add item repetitively for household size to ensure correct pricing/count
                        # We will aggregate later.
                        for _ in range(people_n):
                            all_items.append({
                                'Quantity': q_val,
                                'Ingredient': ing_name,
                                'RefKey': ing_lower, # Used for grouping
                                'Price': price,
                                'Image': img,
                                'Link': url
                            })

                # Create Shop DF
                df_shop = pd.DataFrame(all_items)

                # --- Debug Output ---
                st.expander("🛠️ Debug: All Items Before Grouping", expanded=False).dataframe(df_shop, use_container_width=True)

                if df_shop.empty:
                    st.session_state.shopping_list = pd.DataFrame()
                    st.session_state.shopping_list_display = pd.DataFrame()
                else:
                    # Grouping Logic
                    grouped = df_shop.groupby('Ingredient').agg({
                        'Quantity': lambda x: ", ".join([str(v) for v in x if v]),
                        'Price': 'max',
                        'Image': 'first',
                        'Link': 'first',
                        'RefKey': 'count' # Use to count occurrences
                    }).rename(columns={'RefKey': 'Count'}).reset_index()

                    grouped['Total Price'] = grouped['Count'] * grouped['Price']

                    # --- Debug Output ---
                    st.expander("🛠️ Debug: Grouped Shopping Cart", expanded=False).dataframe(grouped, use_container_width=True)

                    # Find dropped/skipped ingredients
                    before_set = set(df_shop['Ingredient'])
                    after_set = set(grouped['Ingredient'])
                    dropped = before_set - after_set
                    if dropped:
                        st.warning(f"Dropped/Skipped Ingredients: {', '.join(dropped)}")

                    # Store raw grouped data
                    st.session_state.shopping_list = grouped

                    # --- AI Optimization (Groq) ---
                    g_client = get_groq_client()

                    final_display = pd.DataFrame()

                    if g_client:
                        with st.spinner("AI is optimizing your shopping list (calculating totals & finding best deals)..."):
                            optimized_df = optimize_shopping_list_groq(grouped, g_client)
                            if not optimized_df.empty:
                                final_display = optimized_df

                    # Fallback if AI fails or no key
                    if final_display.empty:
                        # Keep as floats — NumberColumn handles € formatting
                        grouped['Unit Price'] = pd.to_numeric(grouped['Price'], errors='coerce').fillna(0.0)
                        grouped['Total Price'] = pd.to_numeric(grouped['Total Price'], errors='coerce').fillna(0.0)
                        # Fill missing buy links with Mercadona search URL
                        grouped['Link'] = grouped.apply(
                            lambda r: r['Link'] if r['Link'] else
                            f"https://tienda.mercadona.es/search-results/?query={r['Ingredient'].replace(' ', '+')}",
                            axis=1
                        )
                        # Clean NA/empty tokens from quantity strings
                        def clean_qty(val):
                            if pd.isna(val): return ""
                            tokens = [t.strip().strip('"') for t in str(val).split(',')]
                            clean = [t for t in tokens if t and t.upper() != 'NA']
                            return ", ".join(clean) if clean else ""
                        grouped['Qty Needed'] = grouped['Quantity'].apply(clean_qty)
                        final_display = grouped[['Ingredient', 'Qty Needed', 'Unit Price', 'Count', 'Total Price', 'Link']]

                    st.session_state.shopping_list_display = final_display
                    st.session_state.validation_step = 2
                
         if st.session_state.validation_step >= 2:
             st.success("Meal plan & Shopping List Generated! Review below.")

    if st.session_state.meal_plan is not None:
        plan_df = st.session_state.meal_plan
        
        # Ensure interactive columns exist
        if 'Liked' not in plan_df.columns:
            plan_df['Liked'] = False
        if 'Substitute' not in plan_df.columns:
            plan_df['Substitute'] = False
            
        # Display Weekly Schedule
        st.subheader(" Your Meal Schedule")
        
        # Group by Day
        days_list = sorted(list(set(plan_df['Day'].values)), key=lambda x: int(x.split(' ')[1]))
        
        for day_str in days_list:
            # Filter safely
            day_mask = plan_df['Day'] == day_str
            day_data = plan_df.loc[day_mask].copy()
            
            day_num = int(day_str.split(' ')[1])
            is_expanded = (day_num == 1)
            
            with st.expander(f"{day_str} - {day_data['calories'].sum()} kcal | €{day_data['cost'].sum():.2f}", expanded=is_expanded):
                
                # Config for Editor
                # We want Liked and Substitute to be editable checkboxes
                # We want others to be read-only text
                
                display_cols = ['Liked', 'Substitute', 'Meal', 'name', 'calories', 'protein', 'carbs', 'fat', 'prep_time', 'cost', 'ingredients']
                
                col_cfg = {
                    "Liked": st.column_config.CheckboxColumn("Like ❤️", help="Mark favorites to keep"),
                    "Substitute": st.column_config.CheckboxColumn("Sub 🔄", help="Mark to replace"),
                    "name": st.column_config.TextColumn("Recipe Name", width="medium"),
                    "calories": st.column_config.NumberColumn("Cals"),
                    "cost": st.column_config.NumberColumn("Cost", format="€%.2f"),
                    "Meal": st.column_config.TextColumn("Slot", disabled=True),
                }
                
                # Make all other columns disabled by default? Streamlit doesn't support "all others disabled" easily yet.
                # But typically non-editable columns act as text.
                
                edited_day = st.data_editor(
                    day_data[display_cols],
                    column_config=col_cfg,
                    use_container_width=True,
                    hide_index=True,
                    key=f"editor_{day_str.replace(' ', '_')}"
                )
                
                # Check for changes and update main state
                # We rely on indices matching to update the master DF
                if not edited_day.equals(day_data[display_cols]):
                    # Update the specific columns in the master plan
                    # We need to map back the changes. 
                    # Note: edited_day has reset index if we hid it? 
                    # No, hide_index just hides display. Index is preserved in the returned DF data.
                    # Wait, day_data.loc[mask] preserves index. 
                    
                    # Update the global plan with the new Checkbox values
                    # We iterate to be safe
                    for idx, row in edited_day.iterrows():
                        if idx in st.session_state.meal_plan.index:
                            st.session_state.meal_plan.at[idx, 'Liked'] = row['Liked']
                            st.session_state.meal_plan.at[idx, 'Substitute'] = row['Substitute']
                            # Persist liked recipe names across future optimization runs
                            recipe_name = str(row.get('name', ''))
                            if recipe_name:
                                if row['Liked']:
                                    st.session_state.liked_recipe_names.add(recipe_name)
                                else:
                                    st.session_state.liked_recipe_names.discard(recipe_name)
                    
                    # Trigger rerun to save state if needed? 
                    # Streamlit handles widget state, but we need to persist it to our variable.
                    # We just did that above.
        
        # Action Buttons
        col_sub, col_save = st.columns([1, 3])
        if col_sub.button("🔄 Regenerate Marked 'Sub' Meals"):
             # Logic to swap out meals
             # Identify rows to swap
             mask_sub = st.session_state.meal_plan['Substitute'] == True
             to_swap_indices = st.session_state.meal_plan[mask_sub].index
             
             if len(to_swap_indices) > 0:
                 with st.spinner(f"Swapping {len(to_swap_indices)} meals..."):
                     # Simple Swap Logic: Pick a random recipe for that Slot that ISN'T the current one
                     # We need access to df_recipes
                     if not df_recipes.empty:
                         for idx in to_swap_indices:
                             current_row = st.session_state.meal_plan.loc[idx]
                             slot = current_row['Meal']
                             
                             # Filter candidates (naive)
                             # In a real app, we'd reuse the complex filtering logic (is_breakfast, etc.)
                             # For now, just pick a random recipe
                             # But let's try to match the Category roughly
                             
                             # Get a random replacement
                             candidates = df_recipes.sample(10) # pick 10 random
                             replacement = candidates.iloc[0] # fallback
                             
                             # Try to find a better one
                             for _, cand in candidates.iterrows():
                                 if cand['name'] != current_row['name']:
                                     replacement = cand
                                     break
                            
                             # Valid replacement found, update row
                             # We must preserve the 'Day', 'Meal', 'People' columns
                             for col in df_recipes.columns:
                                 if col in st.session_state.meal_plan.columns:
                                      st.session_state.meal_plan.at[idx, col] = replacement[col]
                             
                             # Reset Flags
                             st.session_state.meal_plan.at[idx, 'Substitute'] = False
                             st.session_state.meal_plan.at[idx, 'Liked'] = False # New meal, reset like
                     
                     st.session_state.shopping_list = None # Invalidate Shopping List
                     st.session_state.shopping_list_display = pd.DataFrame()
                     st.rerun()
             else:
                 st.info("Mark some meals with 'Sub' checkbox first!")

        # Nutritional Breakdown vs Targets
        st.subheader(" Average Daily Nutrition vs Targets")
        
        avg_cal = plan_df['calories'].sum() / days
        avg_prot = plan_df['protein'].sum() / days
        avg_carb = plan_df['carbs'].sum() / days
        avg_fat = plan_df['fat'].sum() / days
        avg_cost = plan_df['cost'].sum() / days
        
        col1, col2, col3, col4, col5 = st.columns(5)
        col1.metric("Calories", f"{avg_cal:.0f}", f"{avg_cal - target_calories:.0f} from target", delta_color="inverse")
        col2.metric("Protein (g)", f"{avg_prot:.0f}", f"{avg_prot - target_protein:.0f} from target")
        col3.metric("Carbs (g)", f"{avg_carb:.0f}", f"{avg_carb - target_carbs:.0f} from target")
        col4.metric("Fat (g)", f"{avg_fat:.0f}", f"{avg_fat - target_fat:.0f} from target")
        col5.metric("Daily Cost", f"€{avg_cost:.2f}", f"€{avg_cost - max_budget:.2f} from budget", delta_color="inverse")
        
        # Charts
        fig_macros = go.Figure(data=[
            go.Bar(name='Actual (Avg)', x=['Protein', 'Carbs', 'Fat'], y=[avg_prot, avg_carb, avg_fat]),
            go.Bar(name='Target', x=['Protein', 'Carbs', 'Fat'], y=[target_protein, target_carbs, target_fat])
        ])
        fig_macros.update_layout(barmode='group', title="Macronutrient Comparison")
        st.plotly_chart(fig_macros, use_container_width=True)
        
        # Shopping List
        if st.session_state.validation_step >= 2:
            st.divider()
            if 'shopping_list_display' in st.session_state and not st.session_state.shopping_list_display.empty:
                _total = pd.to_numeric(st.session_state.shopping_list_display.get('Total Price', pd.Series(dtype=float)), errors='coerce').sum()
                st.subheader(f"🛒 Shopping List — Total: €{_total:.2f}")
            else:
                st.subheader("🛒 Shopping List")
            if 'shopping_list_display' in st.session_state and not st.session_state.shopping_list_display.empty:
                df_shop = st.session_state.shopping_list_display

                # Configure Columns
                # Ensure 'Remove' exists
                if 'Remove' not in df_shop.columns:
                    df_shop['Remove'] = False

                # Drop Image column if present — not needed in display
                if 'Image' in df_shop.columns:
                    df_shop = df_shop.drop(columns=['Image'])

                col_config = {
                    "Link": st.column_config.LinkColumn("Buy Link", display_text="Open Link"),
                    "Ingredient": st.column_config.TextColumn("Ingredient", help="Hover for details", width="medium"),
                    "Qty Needed": st.column_config.TextColumn("Qty Needed"),
                    "Bought": st.column_config.TextColumn("Bought"),
                    "Leftover": st.column_config.TextColumn("Leftover"),
                    "Unit Price": st.column_config.NumberColumn("Unit Price", format="€%.2f"),
                    "Total Price": st.column_config.NumberColumn("Total Price", format="€%.2f"),
                    "Remove": st.column_config.CheckboxColumn("Remove 🗑️", help="Mark to exclude from purchase")
                }

                # Use Data Editor for interactivity (Remove items)
                edited_df = st.data_editor(
                    df_shop,
                    column_config=col_config,
                    use_container_width=True,
                    num_rows="dynamic",
                    key="shopping_list_editor",
                    hide_index=True
                )

                # Filter deleted/removed items
                purchase_list = edited_df[~edited_df['Remove']].copy()

                col_act1, col_act2, col_act3 = st.columns([1, 1, 2])
                if col_act1.button("✅ Confirm Purchase"):
                    # Logic: Add leftovers from remaining items to Pantry
                    if not purchase_list.empty:
                        # Calculate leftovers to add
                        new_leftovers = pd.DataFrame()
                        if 'Leftover' in purchase_list.columns:
                            # Filter rows with actual leftovers
                            valid_lo = purchase_list[purchase_list['Leftover'].astype(str).str.strip() != ""]
                            if not valid_lo.empty:
                                new_leftovers = valid_lo[['Ingredient', 'Leftover', 'Link']]

                        if 'pantry_leftovers' not in st.session_state:
                            st.session_state.pantry_leftovers = pd.DataFrame(columns=['Ingredient', 'Leftover', 'Link'])

                        # Concat
                        if not new_leftovers.empty:
                            st.session_state.pantry_leftovers = pd.concat([st.session_state.pantry_leftovers, new_leftovers], ignore_index=True)
                            st.success(f"Added {len(new_leftovers)} items to Pantry!")
                        else:
                            st.info("No specific leftovers detected to add.")

                        # Save Run to History
                        if 'run_history' not in st.session_state: st.session_state.run_history = []
                        hist_entry = {
                            "date": datetime.now().strftime("%Y-%m-%d %H:%M"),
                            "meal_plan": st.session_state.meal_plan.to_dict(),
                            "shopping_list": purchase_list.to_dict()
                        }
                        st.session_state.run_history.append(hist_entry)
                        st.toast("Run saved to History!", icon="💾")

                    else:
                        st.warning("All items removed or list empty.")

            else:
                st.info("Shopping list is empty or not generated. Generate a meal plan first!")

with tabs[1]:
    st.subheader("🏠 Leftover Pantry")

    # Initialize if missing
    if 'pantry_leftovers' not in st.session_state:
        st.session_state.pantry_leftovers = pd.DataFrame(columns=['Ingredient', 'Leftover', 'Link'])

    if not st.session_state.pantry_leftovers.empty:
        # Allow editing pantry too
        pantry_df = st.data_editor(
            st.session_state.pantry_leftovers,
            num_rows="dynamic",
            use_container_width=True,
            key="pantry_editor"
        )

        # Update state on edit
        st.session_state.pantry_leftovers = pantry_df

        if st.button("Clear Pantry"):
            st.session_state.pantry_leftovers = pd.DataFrame(columns=['Ingredient', 'Leftover', 'Link'])
            st.rerun()
    else:
        st.info("Pantry is empty. Generate a shopping list and click 'Confirm Purchase' to fill it.")

with tabs[2]:
    st.subheader("📚 Order History")
    if 'run_history' in st.session_state and st.session_state.run_history:
        for i, entry in enumerate(reversed(st.session_state.run_history)):
            sl_df = pd.DataFrame(entry['shopping_list'])
            order_total = pd.to_numeric(sl_df.get('Total Price', pd.Series(dtype=float)), errors='coerce').sum() if not sl_df.empty else 0
            with st.expander(f"Order {len(st.session_state.run_history) - i} — {entry['date']} — €{order_total:.2f}"):
                st.write("**Meals:**")
                st.dataframe(pd.DataFrame(entry['meal_plan']))
                st.write("**Shopping List:**")
                st.dataframe(sl_df)
    else:
        st.info("No order history yet. Generate and confirm a meal plan to record your first order.")

with tabs[3]:
    st.subheader("🍽️ Recipe Forum")
    st.markdown("Add your own recipes to the dataset. Your recipes will always be **prioritised** in the meal plan (high rating).")

    with st.form("recipe_forum_form", clear_on_submit=True):
        st.markdown("#### Add a New Recipe")
        col_r1, col_r2 = st.columns(2)
        rf_name = col_r1.text_input("Recipe Name *", placeholder="e.g. Grilled Chicken Salad")
        rf_category = col_r2.selectbox("Category", ["Main Dish", "Breakfast", "Lunch/Snacks", "Dessert", "Salad", "Soup", "Pasta", "Vegetable", "Other"])
        rf_ingredients = st.text_area("Ingredients (one per line, include quantity e.g. '2 chicken breasts')", height=120, placeholder="2 chicken breasts\n1 cup lettuce\n1 tbsp olive oil")
        col_r3, col_r4, col_r5, col_r6, col_r7 = st.columns(5)
        rf_cal  = col_r3.number_input("Calories", 50, 3000, 500)
        rf_prot = col_r4.number_input("Protein (g)", 0, 200, 30)
        rf_carb = col_r5.number_input("Carbs (g)", 0, 500, 40)
        rf_fat  = col_r6.number_input("Fat (g)", 0, 200, 15)
        rf_time = col_r7.number_input("Prep Time (min)", 1, 180, 30)
        rf_submit = st.form_submit_button("Submit Recipe")

    if rf_submit and rf_name.strip():
        # Build ingredients_json from the text area
        lines = [l.strip() for l in rf_ingredients.strip().split('\n') if l.strip()]
        ing_json = json.dumps([{"q": "", "i": l} for l in lines])
        ing_str  = ", ".join(lines)

        # Map category → keywords that match the LP slot-detection logic
        _kw_map = {
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
        kw_str = _kw_map.get(rf_category, "main dinner lunch")

        new_recipe = {
            "name": rf_name.strip(),
            "RecipeCategory": rf_category,
            "Keywords": kw_str,
            "calories": float(rf_cal),
            "protein": float(rf_prot),
            "carbs": float(rf_carb),
            "fat": float(rf_fat),
            "prep_time": float(rf_time),
            "cost": 5.0,
            "AggregatedRating": 10.0,   # Always prioritised
            "ingredients": ing_str,
            "ingredients_json": ing_json,
        }
        st.session_state.user_recipes.append(new_recipe)
        st.success(f"'{rf_name}' added! It will be prioritised in your next meal plan.")

    if st.session_state.user_recipes:
        st.markdown("#### Your Submitted Recipes")
        user_df_display = pd.DataFrame(st.session_state.user_recipes)[['name', 'RecipeCategory', 'calories', 'protein', 'carbs', 'fat', 'prep_time']]
        user_df_display.columns = ['Name', 'Category', 'Calories', 'Protein (g)', 'Carbs (g)', 'Fat (g)', 'Prep Time (min)']
        st.dataframe(user_df_display, use_container_width=True, hide_index=True)
        if st.button("Clear All My Recipes"):
            st.session_state.user_recipes = []
            st.rerun()
    else:
        st.info("No recipes submitted yet. Use the form above to add your first recipe.")

# Hide Streamlit default chrome + apply Mercadona theme
hide_streamlit_style = """
<style>
#MainMenu {visibility: hidden;}
footer {visibility: hidden;}

/* ── Mercadona colour palette ── */
:root {
    --mg: #00904A;
    --mg-dark: #006B38;
    --mg-light: #E8F5EE;
    --mg-border: rgba(0,144,74,0.18);
}

/* App background */
.stApp { background-color: #FFFFFF; }

/* Sidebar */
section[data-testid="stSidebar"] {
    background-color: #F7F9F7;
    border-right: 3px solid var(--mg);
}
section[data-testid="stSidebar"] h1,
section[data-testid="stSidebar"] h2,
section[data-testid="stSidebar"] h3 { color: var(--mg) !important; }

/* Main headings */
h1 { color: var(--mg) !important; font-weight: 800 !important; }
h2, h3 { color: var(--mg-dark) !important; }

/* Buttons */
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

/* Tab bar */
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

/* Metric cards */
[data-testid="metric-container"] {
    background: var(--mg-light);
    border: 1px solid var(--mg-border);
    border-radius: 10px;
    padding: 0.8rem;
}

/* Info / success banners */
.stSuccess { border-left: 4px solid var(--mg); background: var(--mg-light); }
.stInfo    { border-left: 4px solid var(--mg); }

/* Form */
.stForm { border: 1px solid var(--mg-border); border-radius: 10px; padding: 1rem; }
</style>
"""
st.markdown(hide_streamlit_style, unsafe_allow_html=True)
