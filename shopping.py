import json

import pandas as pd

from services.rag import search_products


def optimize_shopping_list_groq(df_shop, groq_client):
    if df_shop.empty or not groq_client:
        return df_shop

    try:
        def search_mercadona_candidates(ing_name):
            results = search_products(ing_name, top_k=20)
            if results.empty:
                return "No match found in Mercadona catalogue."
            lines = []
            for _, r in results.iterrows():
                lines.append(
                    f"- Option: {r['name']} | Price: €{r['price']:.2f} | URL: {r.get('url', '')}"
                )
            return "\n".join(lines)

        candidates_context = []
        for _, row in df_shop.iterrows():
            ing_name = row['Ingredient']
            cand_str = search_mercadona_candidates(ing_name)
            candidates_context.append(
                f"Item: {ing_name} | Qty Inputs: {str(row['Quantity'])} | Count: {row['Count']}\nCandidates:\n{cand_str}\n---\n"
            )

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

        new_rows = []
        batch_size = 10  # reduced: each item now carries 20 candidates
        for batch_start in range(0, len(candidates_context), batch_size):
            batch = candidates_context[batch_start:batch_start + batch_size]
            full_prompt = prompt_template.replace("{batch_data}", "\n".join(batch))
            try:
                completion = groq_client.chat.completions.create(
                    messages=[
                        {"role": "system", "content": "Return ONLY a JSON object with key 'products'."},
                        {"role": "user", "content": full_prompt},
                    ],
                    model="llama-3.3-70b-versatile",
                    temperature=0,
                    response_format={"type": "json_object"},
                )
                result = json.loads(completion.choices[0].message.content)
                for p in result.get('products', []):
                    link = p.get('url', '').strip()
                    if not link:
                        # Fallback: take the top TF-IDF result's URL directly
                        orig = p.get('original_ingredient', p.get('product_name', ''))
                        top = search_products(orig, top_k=1)
                        link = str(top.iloc[0].get('url', '')) if not top.empty else ''
                    new_rows.append({
                        'Ingredient': p.get('original_ingredient', 'Unknown'),
                        'SKU':        p.get('product_name', ''),
                        'Qty Needed': p.get('total_quantity_needed', ''),
                        'Bought':     p.get('quantity_bought', ''),
                        'Leftover':   p.get('leftover', ''),
                        'Unit Price': float(p.get('unit_price', 0) or 0),
                        'Count':      1,
                        'Total Price': float(p.get('total_price', 0) or 0),
                        'Link': link,
                    })
            except Exception as batch_err:
                print(f"Batch {batch_start} error: {batch_err}")
                continue

        return pd.DataFrame(new_rows) if new_rows else pd.DataFrame()

    except Exception as e:
        print(f"Optimization Error: {e}")
        import traceback; traceback.print_exc()
        return pd.DataFrame()
