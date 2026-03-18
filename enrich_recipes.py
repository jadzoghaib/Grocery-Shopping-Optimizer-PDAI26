"""
One-time recipe ingredient enrichment script.
Adds proper culinary units to bare-number quantities using a comprehensive
rule-based mapper.

Reads:  Food.com - Recipes/recipes.csv
Writes: Food.com - Recipes/recipes_enriched.csv

Usage:
    python enrich_recipes.py
"""

import re
import ast
import pandas as pd

INPUT_CSV  = r"C:\Users\Jad Zoghaib\OneDrive\Desktop\Grocery-Shopping-Optimizer-PDAI26\Food.com - Recipes\recipes.csv"
OUTPUT_CSV = r"C:\Users\Jad Zoghaib\OneDrive\Desktop\Grocery-Shopping-Optimizer-PDAI26\Food.com - Recipes\recipes_enriched.csv"
MAX_ROWS   = 5000


# ── Comprehensive ingredient → unit mapping ────────────────────────────────────
# Sorted longest-key-first at build time so more-specific keys match before
# shorter ones (e.g. "chocolate chips" before "chocolate").

UNIT_MAP = {
    # ── Liquids → cup ──────────────────────────────────────────────────────
    "buttermilk":           "cup",
    "coconut milk":         "can",
    "evaporated milk":      "can",
    "condensed milk":       "can",
    "almond milk":          "cup",
    "oat milk":             "cup",
    "soy milk":             "cup",
    "heavy cream":          "cup",
    "whipping cream":       "cup",
    "coconut cream":        "cup",
    "half-and-half":        "cup",
    "half and half":        "cup",
    "sour cream":           "cup",
    "brewed coffee":        "cup",
    "espresso":             "cup",
    "milk":                 "cup",
    "water":                "cup",
    "broth":                "cup",
    "stock":                "cup",
    "cream":                "cup",
    "tea":                  "cup",
    "orange juice":         "cup",
    "apple juice":          "cup",
    "tomato juice":         "cup",
    "pineapple juice":      "cup",
    "lemon juice":          "tbsp",
    "lime juice":           "tbsp",
    "juice":                "cup",
    "red wine":             "cup",
    "white wine":           "cup",
    "wine":                 "cup",
    "beer":                 "cup",

    # ── Vinegars / fermented liquids → tbsp ───────────────────────────────
    "apple cider vinegar":  "tbsp",
    "balsamic vinegar":     "tbsp",
    "rice vinegar":         "tbsp",
    "red wine vinegar":     "tbsp",
    "white wine vinegar":   "tbsp",
    "vinegar":              "tbsp",

    # ── Sauces / condiments → tbsp ────────────────────────────────────────
    "worcestershire":       "tbsp",
    "fish sauce":           "tbsp",
    "oyster sauce":         "tbsp",
    "hoisin sauce":         "tbsp",
    "hoisin":               "tbsp",
    "teriyaki sauce":       "tbsp",
    "teriyaki":             "tbsp",
    "soy sauce":            "tbsp",
    "tamari":               "tbsp",
    "coconut aminos":       "tbsp",
    "hot sauce":            "tsp",
    "tabasco":              "tsp",
    "sriracha":             "tsp",
    "bbq sauce":            "tbsp",
    "barbecue sauce":       "tbsp",
    "dijon mustard":        "tbsp",
    "mustard":              "tbsp",
    "ketchup":              "tbsp",
    "mayonnaise":           "tbsp",
    "mayo":                 "tbsp",
    "relish":               "tbsp",
    "capers":               "tbsp",
    "pesto":                "tbsp",
    "miso":                 "tbsp",
    "ranch":                "tbsp",
    "harissa":              "tbsp",

    # ── Sweeteners → tbsp (except cup-scale below) ────────────────────────
    "maple syrup":          "tbsp",
    "corn syrup":           "tbsp",
    "honey":                "tbsp",
    "molasses":             "tbsp",
    "agave":                "tbsp",

    # ── Oils → tbsp ────────────────────────────────────────────────────────
    "olive oil":            "tbsp",
    "vegetable oil":        "tbsp",
    "canola oil":           "tbsp",
    "coconut oil":          "tbsp",
    "sesame oil":           "tsp",
    "peanut oil":           "tbsp",
    "avocado oil":          "tbsp",
    "sunflower oil":        "tbsp",
    "corn oil":             "tbsp",
    "shortening":           "tbsp",
    "lard":                 "tbsp",
    "cooking spray":        "spray",

    # ── Extracts / flavourings → tsp ──────────────────────────────────────
    "vanilla extract":      "tsp",
    "almond extract":       "tsp",
    "peppermint extract":   "tsp",
    "orange extract":       "tsp",
    "extract":              "tsp",

    # ── Spirits / liqueurs → tbsp ─────────────────────────────────────────
    "orange liqueur":       "tbsp",
    "rum":                  "tbsp",
    "bourbon":              "tbsp",
    "whiskey":              "tbsp",
    "vodka":                "tbsp",
    "brandy":               "tbsp",
    "liqueur":              "tbsp",
    "sherry":               "tbsp",

    # ── Butter / fat ──────────────────────────────────────────────────────
    "butter":               "tbsp",
    "margarine":            "tbsp",
    "ghee":                 "tbsp",
    "mascarpone":           "cup",

    # ── Nut butters → tbsp ────────────────────────────────────────────────
    "peanut butter":        "tbsp",
    "almond butter":        "tbsp",
    "nut butter":           "tbsp",
    "tahini":               "tbsp",

    # ── Cream cheese / block cheeses → oz ─────────────────────────────────
    "cream cheese":         "oz",
    "goat cheese":          "oz",
    "brie":                 "oz",
    "camembert":            "oz",
    "velveeta":             "oz",
    "tofu":                 "oz",
    "tempeh":               "oz",

    # ── Shredded / crumbled cheeses → cup ─────────────────────────────────
    "cheddar":              "cup",
    "mozzarella":           "cup",
    "parmesan":             "cup",
    "parmigiano":           "cup",
    "pecorino":             "cup",
    "romano":               "cup",
    "gruyere":              "cup",
    "swiss cheese":         "cup",
    "provolone":            "cup",
    "colby":                "cup",
    "monterey jack":        "cup",
    "pepper jack":          "cup",
    "feta":                 "cup",
    "ricotta":              "cup",
    "cottage cheese":       "cup",
    "american cheese":      "slice",
    "cheese":               "cup",

    # ── Yogurt / dairy semi-solids → cup ──────────────────────────────────
    "greek yogurt":         "cup",
    "yogurt":               "cup",

    # ── Dry staples → cup ─────────────────────────────────────────────────
    "all-purpose flour":    "cup",
    "bread flour":          "cup",
    "cake flour":           "cup",
    "whole wheat flour":    "cup",
    "almond flour":         "cup",
    "coconut flour":        "cup",
    "self-rising flour":    "cup",
    "flour":                "cup",
    "granulated sugar":     "cup",
    "powdered sugar":       "cup",
    "confectioners":        "cup",
    "icing sugar":          "cup",
    "caster sugar":         "cup",
    "brown sugar":          "cup",
    "raw sugar":            "cup",
    "white sugar":          "cup",
    "sugar":                "cup",
    "stevia":               "tsp",
    "splenda":              "tsp",
    "rolled oats":          "cup",
    "quick oats":           "cup",
    "oatmeal":              "cup",
    "oats":                 "cup",
    "brown rice":           "cup",
    "white rice":           "cup",
    "basmati":              "cup",
    "jasmine rice":         "cup",
    "wild rice":            "cup",
    "arborio":              "cup",
    "rice":                 "cup",
    "quinoa":               "cup",
    "couscous":             "cup",
    "bulgur":               "cup",
    "barley":               "cup",
    "cornmeal":             "cup",
    "polenta":              "cup",
    "semolina":             "cup",
    "bread crumbs":         "cup",
    "breadcrumbs":          "cup",
    "panko":                "cup",
    "wheat germ":           "tbsp",

    # ── Leavening → tsp ──────────────────────────────────────────────────
    "baking powder":        "tsp",
    "baking soda":          "tsp",
    "bicarbonate":          "tsp",
    "cream of tartar":      "tsp",
    "active dry yeast":     "tsp",
    "instant yeast":        "tsp",
    "yeast":                "tsp",

    # ── Thickeners → tbsp ────────────────────────────────────────────────
    "cornstarch":           "tbsp",
    "corn starch":          "tbsp",
    "arrowroot":            "tbsp",
    "pectin":               "tbsp",
    "xanthan gum":          "tsp",
    "guar gum":             "tsp",
    "psyllium":             "tbsp",
    "gelatin":              "tsp",

    # ── Small seeds → tbsp ───────────────────────────────────────────────
    "flaxseed":             "tbsp",
    "flax seed":            "tbsp",
    "chia seed":            "tbsp",
    "chia seeds":           "tbsp",
    "sesame seeds":         "tbsp",
    "sesame seed":          "tbsp",
    "poppy seeds":          "tsp",
    "poppy seed":           "tsp",
    "sunflower seeds":      "tbsp",
    "pumpkin seeds":        "tbsp",
    "hemp seeds":           "tbsp",

    # ── Salt → tsp ────────────────────────────────────────────────────────
    "kosher salt":          "tsp",
    "sea salt":             "tsp",
    "table salt":           "tsp",
    "coarse salt":          "tsp",
    "salt":                 "tsp",

    # ── Pepper (spice) → tsp ──────────────────────────────────────────────
    "black pepper":         "tsp",
    "white pepper":         "tsp",
    "red pepper flakes":    "tsp",
    "crushed red pepper":   "tsp",
    "chili flakes":         "tsp",
    "chili powder":         "tsp",
    "cayenne pepper":       "tsp",
    "cayenne":              "tsp",
    "paprika":              "tsp",
    "smoked paprika":       "tsp",

    # ── Spices → tsp ──────────────────────────────────────────────────────
    "ground cumin":         "tsp",
    "ground coriander":     "tsp",
    "ground turmeric":      "tsp",
    "ground cinnamon":      "tsp",
    "ground nutmeg":        "tsp",
    "ground ginger":        "tsp",
    "ginger powder":        "tsp",
    "garlic powder":        "tsp",
    "onion powder":         "tsp",
    "mustard powder":       "tsp",
    "dry mustard":          "tsp",
    "cumin":                "tsp",
    "coriander":            "tsp",
    "turmeric":             "tsp",
    "cinnamon":             "tsp",
    "nutmeg":               "tsp",
    "allspice":             "tsp",
    "cardamom":             "tsp",
    "celery seed":          "tsp",
    "celery seeds":         "tsp",
    "fennel seed":          "tsp",
    "caraway seed":         "tsp",
    "anise seed":           "tsp",
    "anise":                "tsp",
    "star anise":           "piece",
    "saffron":              "pinch",
    "mace":                 "tsp",
    "fenugreek":            "tsp",
    "sumac":                "tsp",
    "za'atar":              "tsp",
    "curry powder":         "tsp",
    "garam masala":         "tsp",
    "five spice":           "tsp",
    "italian seasoning":    "tsp",
    "herbes de provence":   "tsp",
    "herbs de provence":    "tsp",
    "old bay":              "tsp",
    "cajun seasoning":      "tsp",
    "poultry seasoning":    "tsp",
    "mixed spice":          "tsp",
    "seasoning":            "tsp",

    # ── Herbs → tsp (dried) / tbsp (fresh) ──────────────────────────────
    "fresh basil":          "tbsp",
    "fresh oregano":        "tbsp",
    "fresh thyme":          "tbsp",
    "fresh rosemary":       "tbsp",
    "fresh sage":           "tbsp",
    "fresh parsley":        "tbsp",
    "fresh cilantro":       "tbsp",
    "fresh dill":           "tbsp",
    "fresh mint":           "tbsp",
    "fresh chives":         "tbsp",
    "basil":                "tsp",
    "oregano":              "tsp",
    "thyme":                "tsp",
    "rosemary":             "tsp",
    "sage":                 "tsp",
    "tarragon":             "tsp",
    "marjoram":             "tsp",
    "savory":               "tsp",
    "dill":                 "tsp",
    "parsley":              "tbsp",
    "cilantro":             "tbsp",
    "chives":               "tbsp",
    "mint":                 "tbsp",
    "bay leaf":             "piece",
    "bay leaves":           "piece",

    # ── Nuts → cup ────────────────────────────────────────────────────────
    "pine nuts":            "cup",
    "almonds":              "cup",
    "walnuts":              "cup",
    "pecans":               "cup",
    "cashews":              "cup",
    "pistachios":           "cup",
    "peanuts":              "cup",
    "hazelnuts":            "cup",
    "macadamia":            "cup",
    "chestnuts":            "cup",

    # ── Dried fruit → cup ─────────────────────────────────────────────────
    "dried cranberries":    "cup",
    "dried cherries":       "cup",
    "dried apricots":       "cup",
    "raisins":              "cup",
    "currants":             "cup",
    "cranberries":          "cup",
    "cherries":             "cup",
    "apricots":             "cup",
    "dates":                "cup",
    "prunes":               "cup",
    "figs":                 "cup",

    # ── Chocolate / cocoa ─────────────────────────────────────────────────
    "chocolate chips":      "cup",
    "cocoa powder":         "cup",
    "cacao powder":         "cup",
    "dark chocolate":       "oz",
    "white chocolate":      "oz",
    "chocolate bar":        "oz",
    "chocolate block":      "oz",
    "chocolate":            "oz",

    # ── Legumes / beans → cup ─────────────────────────────────────────────
    "canned chickpeas":     "can",
    "canned beans":         "can",
    "canned corn":          "can",
    "chickpeas":            "cup",
    "garbanzo":             "cup",
    "black beans":          "cup",
    "kidney beans":         "cup",
    "pinto beans":          "cup",
    "cannellini":           "cup",
    "navy beans":           "cup",
    "white beans":          "cup",
    "split peas":           "cup",
    "lentils":              "cup",
    "beans":                "cup",
    "edamame":              "cup",

    # ── Pasta / noodles → oz ──────────────────────────────────────────────
    "egg noodles":          "oz",
    "rice noodles":         "oz",
    "spaghetti":            "oz",
    "linguine":             "oz",
    "fettuccine":           "oz",
    "tagliatelle":          "oz",
    "penne":                "oz",
    "rigatoni":             "oz",
    "fusilli":              "oz",
    "farfalle":             "oz",
    "rotini":               "oz",
    "orzo":                 "cup",
    "macaroni":             "cup",
    "lasagna":              "sheet",
    "noodles":              "oz",
    "pasta":                "oz",

    # ── Canned tomato goods ────────────────────────────────────────────────
    "canned tomatoes":      "can",
    "diced tomatoes":       "can",
    "crushed tomatoes":     "can",
    "canned tomato":        "can",
    "diced tomato":         "can",
    "crushed tomato":       "can",
    "tomato paste":         "tbsp",
    "tomato sauce":         "cup",
    "tomato puree":         "cup",
    "canned tuna":          "can",
    "canned salmon":        "can",

    # ── Leafy greens → cup ────────────────────────────────────────────────
    "fresh spinach":        "cup",
    "baby spinach":         "cup",
    "spinach":              "cup",
    "kale":                 "cup",
    "arugula":              "cup",
    "romaine":              "cup",
    "lettuce":              "cup",
    "red cabbage":          "cup",
    "bok choy":             "cup",
    "cabbage":              "cup",
    "collard greens":       "cup",
    "swiss chard":          "cup",
    "microgreens":          "cup",
    "watercress":           "cup",
    "endive":               "cup",
    "escarole":             "cup",

    # ── Other vegetables → cup ────────────────────────────────────────────
    "broccoli":             "cup",
    "cauliflower":          "cup",
    "brussels sprouts":     "cup",
    "green beans":          "cup",
    "snap peas":            "cup",
    "snow peas":            "cup",
    "peas":                 "cup",
    "mushrooms":            "cup",
    "mushroom":             "cup",
    "asparagus":            "oz",

    # ── Salsa / dips → cup ────────────────────────────────────────────────
    "salsa":                "cup",
    "guacamole":            "cup",
    "hummus":               "cup",

    # ── Meat → lb (larger cuts) ───────────────────────────────────────────
    "ground chicken":       "lb",
    "ground turkey":        "lb",
    "ground beef":          "lb",
    "ground pork":          "lb",
    "ground lamb":          "lb",
    "chicken breast":       "lb",
    "chicken thigh":        "lb",
    "chicken leg":          "lb",
    "chicken wing":         "lb",
    "whole chicken":        "lb",
    "turkey breast":        "lb",
    "flank steak":          "lb",
    "skirt steak":          "lb",
    "short ribs":           "lb",
    "pork chop":            "lb",
    "pork loin":            "lb",
    "pork belly":           "lb",
    "pork shoulder":        "lb",
    "lamb chop":            "lb",
    "rack of lamb":         "lb",
    "chicken":              "lb",
    "turkey":               "lb",
    "beef":                 "lb",
    "steak":                "lb",
    "sirloin":              "lb",
    "chuck":                "lb",
    "brisket":              "lb",
    "pork":                 "lb",
    "lamb":                 "lb",
    "veal":                 "lb",
    "venison":              "lb",
    "duck":                 "lb",
    "bison":                "lb",

    # ── Charcuterie → oz ──────────────────────────────────────────────────
    "bacon":                "slice",
    "pancetta":             "oz",
    "prosciutto":           "oz",
    "salami":               "oz",
    "pepperoni":            "oz",
    "chorizo":              "oz",
    "sausage":              "oz",
    "ham":                  "cup",

    # ── Seafood → oz ──────────────────────────────────────────────────────
    "canned tuna":          "can",
    "salmon fillet":        "oz",
    "salmon":               "oz",
    "tuna":                 "oz",
    "cod":                  "oz",
    "tilapia":              "oz",
    "halibut":              "oz",
    "sea bass":             "oz",
    "trout":                "oz",
    "shrimp":               "oz",
    "prawn":                "oz",
    "scallops":             "oz",
    "scallop":              "oz",
    "crab":                 "oz",
    "lobster":              "oz",
    "clams":                "oz",
    "clam":                 "oz",
    "mussels":              "oz",
    "mussel":               "oz",
    "oysters":              "oz",
    "oyster":               "oz",
    "anchovy":              "oz",
    "sardine":              "oz",
    "squid":                "oz",
    "octopus":              "oz",
    "fish":                 "oz",
    "seafood":              "oz",

    # ── Misc ──────────────────────────────────────────────────────────────
    "nutritional yeast":    "tbsp",
    "protein powder":       "scoop",
    "food coloring":        "drop",
    "sprinkles":            "tbsp",
    "collagen":             "tbsp",

    # ── COUNTABLE items — unit = "" means keep bare number ────────────────
    "clove garlic":         "",
    "garlic clove":         "",
    "spring onion":         "",
    "green onion":          "",
    "cherry tomato":        "",
    "plum tomato":          "",
    "roma tomato":          "",
    "sweet potato":         "",
    "celery stalk":         "",
    "celery rib":           "",
    "stalk celery":         "",
    "rib celery":           "",
    "bell pepper":          "",
    "chili pepper":         "",
    "ear of corn":          "",
    "head of garlic":       "",
    "fennel bulb":          "",
    "jalapeño":             "",
    "jalapeno":             "",
    "serrano":              "",
    "habanero":             "",
    "scallion":             "",
    "shallot":              "",
    "leek":                 "",
    "potato":               "",
    "tomato":               "",
    "avocado":              "",
    "zucchini":             "",
    "cucumber":             "",
    "eggplant":             "",
    "artichoke":            "",
    "beet":                 "",
    "turnip":               "",
    "parsnip":              "",
    "radish":               "",
    "onion":                "",
    "carrot":               "",
    "corn":                 "",
    "apple":                "",
    "pear":                 "",
    "peach":                "",
    "plum":                 "",
    "apricot":              "",
    "mango":                "",
    "papaya":               "",
    "pineapple":            "",
    "banana":               "",
    "orange":               "",
    "lemon":                "",
    "lime":                 "",
    "grapefruit":           "",
    "kiwi":                 "",
    "fig":                  "",
    "date":                 "",
    "coconut":              "",
    "egg":                  "",
    "yam":                  "",
}

# Sort longest-key-first so specific entries beat generic ones
_SORTED_KEYS = sorted(UNIT_MAP.keys(), key=len, reverse=True)

# Words that indicate a quantity already carries a unit
_UNIT_WORDS = {
    "cup", "cups", "tsp", "tbsp", "tablespoon", "tablespoons",
    "teaspoon", "teaspoons", "oz", "ounce", "ounces", "lb", "lbs",
    "pound", "pounds", "g", "gram", "grams", "kg", "ml", "liter",
    "liters", "l", "pint", "pints", "quart", "quarts", "gallon", "gallons",
    "piece", "pieces", "clove", "cloves", "slice", "slices", "bunch",
    "head", "stalk", "sprig", "sprigs", "can", "cans", "package", "packages",
    "pkg", "jar", "bottle", "dash", "pinch", "handful", "sheet", "sheets",
    "scoop", "drop", "drops", "spray", "strip", "strips", "fillet", "fillets",
    "stick", "sticks", "block",
}

_BARE_RE = re.compile(r'^[\d\s/½⅓⅔¼¾⅛⅜⅝⅞.\-]+$')


def infer_unit(qty: str, ing: str) -> str:
    """Return qty with a unit appended when it is a bare number."""
    qty = qty.strip() if qty else ""
    if not qty or qty.upper() == "NA":
        return ""

    # Already has a unit word?
    if set(qty.lower().split()) & _UNIT_WORDS:
        return qty

    # Not a bare number / fraction?
    if not _BARE_RE.match(qty):
        return qty  # "to taste", "as needed", etc.

    ing_lower = ing.lower().strip() if isinstance(ing, str) else ""
    unit = None
    for key in _SORTED_KEYS:
        if key in ing_lower:
            unit = UNIT_MAP[key]
            break

    if unit is None:
        # Fallback heuristics
        if any(w in ing_lower for w in ("powder", "ground ", "dried ", "flakes", "flaked")):
            unit = "tsp"
        elif any(w in ing_lower for w in ("fresh ", "chopped ", "minced ", "sliced ", "diced ")):
            unit = "cup"
        elif any(w in ing_lower for w in ("sauce", "syrup", "paste", "puree")):
            unit = "tbsp"
        elif any(w in ing_lower for w in ("leaf", "leaves", "herb")):
            unit = "tsp"
        else:
            unit = "cup"   # safe default

    if unit == "":
        return qty   # countable — bare number stays as-is
    return f"{qty} {unit}"


# ── R-vector helpers ───────────────────────────────────────────────────────────

def parse_r_vector(s):
    """Parse R-style c("a", "b", NA, ...) into a Python list of strings."""
    if not isinstance(s, str):
        return []
    s = s.strip()
    if not s or s.upper() in ("NA", "NULL"):
        return []

    # Strip outer c( ... )
    m = re.match(r'^c\((.*)\)$', s, re.DOTALL)
    inner = m.group(1) if m else s

    # Try ast parsing first (handles quoted strings and NA atoms reliably)
    try:
        # Replace bare R NA with Python None
        inner_py = re.sub(r'(?<!["\w])NA(?!["\w])', 'None', inner)
        tup = ast.literal_eval(f"({inner_py},)")
        return ["" if x is None else str(x) for x in tup]
    except Exception:
        pass

    # Fallback: manual split on `", ` boundaries
    parts = re.split(r'",\s*"', inner)
    result = []
    for p in parts:
        p = p.strip().strip('"')
        result.append("" if p.upper() == "NA" else p)
    return result


def to_r_vector(lst):
    """Encode a Python list back to R-style c("a", "b", ...) notation."""
    if not lst:
        return "NA"
    parts = [f'"{x}"' if x else "NA" for x in lst]
    return f"c({', '.join(parts)})"


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    print(f"Loading {INPUT_CSV} ...")
    df = pd.read_csv(INPUT_CSV, nrows=MAX_ROWS)
    print(f"Loaded {len(df):,} recipes.")

    enriched_quantities = []
    total_pairs = 0
    fixed_count = 0

    for _, row in df.iterrows():
        qty_list = parse_r_vector(row.get("RecipeIngredientQuantities", ""))
        ing_list = parse_r_vector(row.get("RecipeIngredientParts", ""))

        # Align lengths
        length = max(len(qty_list), len(ing_list))
        qty_list += [""] * (length - len(qty_list))
        ing_list  += [""] * (length - len(ing_list))

        new_qtys = []
        for q, ing in zip(qty_list, ing_list):
            total_pairs += 1
            new_q = infer_unit(q, ing)
            if new_q != q and q not in ("", "NA"):
                fixed_count += 1
            new_qtys.append(new_q)

        enriched_quantities.append(to_r_vector(new_qtys))

    df["RecipeIngredientQuantities"] = enriched_quantities
    df.to_csv(OUTPUT_CSV, index=False)

    print(f"\nResults:")
    print(f"  Total (qty, ingredient) pairs processed : {total_pairs:,}")
    print(f"  Quantities enriched with a culinary unit : {fixed_count:,}")
    print(f"\nOutput saved to:")
    print(f"  {OUTPUT_CSV}")


if __name__ == "__main__":
    main()
