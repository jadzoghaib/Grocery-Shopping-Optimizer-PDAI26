"""Per-ingredient-category pack caps.

Imported by both ``core.shopping`` and ``core.shopping_fallback`` so the same
logic applies whether the LLM or the rule-based fallback produces the row.

Why we need this
----------------
The 10-pack global cap was designed to catch absurd LLM mistakes on bulk
staples (e.g. "buy 50 bags of flour"). But herbs and spices are sold in
100 g jars and a single jar lasts months — 10 jars of parsley is genuinely
wrong. Fresh meat, dairy, and produce have natural upper limits too.

Cap table
---------
  Herbs & dried spices  → 2   (one jar is a year's supply of dried parsley)
  Condiments & sauces   → 2   (mustard, soy sauce, etc. — very slow use)
  Eggs                  → 2   (a 24-egg tray; 2 trays = 48 eggs = plenty)
  Dairy                 → 3   (milk, butter, cream, cheese)
  Meat & fish           → 4   (chicken, beef, salmon — perishable)
  Fresh produce         → 4   (tomatoes, peppers, onions, etc.)
  Bulk dry staples      → 8   (flour, sugar, rice, pasta — legitimately large)
  Default               → 5
"""
from __future__ import annotations

# ── Category keyword sets ─────────────────────────────────────────────────────
# Checks are applied in order; the FIRST match wins.
# Keep herb/spice keywords BEFORE produce keywords so that "black pepper"
# (spice) is caught before "pepper" (vegetable).

_HERB_SPICE_KEYWORDS: tuple[str, ...] = (
    # Dried herbs
    "parsley", "cilantro", "coriander", "basil", "thyme", "rosemary",
    "oregano", "dill", "mint", "sage", "tarragon", "chives", "bay leaf",
    "bay leaves",
    # Ground / dried spices
    "cumin", "paprika", "turmeric", "cinnamon", "nutmeg", "cardamom",
    "cloves", "clove", "cayenne", "saffron", "allspice", "ancho chili",
    "chili powder", "chili flakes", "red pepper flakes", "curry powder",
    "garam masala", "five spice", "star anise", "fennel seed",
    "garlic powder", "onion powder", "smoked paprika", "black pepper",
    "white pepper", "pepper flakes",
    # Baking additives
    "baking soda", "baking powder", "bicarbonate", "cream of tartar",
    "vanilla extract", "vanilla",
    # Yeast
    "yeast",
)

_CONDIMENT_KEYWORDS: tuple[str, ...] = (
    "mustard", "ketchup", "mayonnaise", "mayo",
    "soy sauce", "tamari", "fish sauce", "oyster sauce", "hoisin",
    "worcestershire", "hot sauce", "sriracha", "tabasco",
    "tahini", "miso", "pesto",
    "vinegar", "balsamic",
    "jam", "marmalade", "honey", "maple syrup", "agave",
    "peanut butter", "almond butter", "nutella",
)

_EGG_KEYWORDS: tuple[str, ...] = (
    "eggs", "egg",
)

_DAIRY_KEYWORDS: tuple[str, ...] = (
    "milk", "butter", "cream", "yogurt", "yoghurt",
    "sour cream", "heavy cream", "whipping cream", "double cream",
    "condensed milk", "evaporated milk",
    "cheese", "cheddar", "mozzarella", "parmesan", "ricotta",
    "feta", "gouda", "brie", "camembert", "cottage cheese", "cream cheese",
    "queso", "fromage",
)

_MEAT_FISH_KEYWORDS: tuple[str, ...] = (
    "chicken", "beef", "pork", "lamb", "veal", "turkey", "duck",
    "salmon", "tuna", "cod", "hake", "trout", "sea bass", "sea bream",
    "shrimp", "prawns", "mussels", "clams", "squid", "octopus", "crab",
    "bacon", "ham", "sausage", "chorizo", "salami", "pepperoni", "prosciutto",
    "hamburger", "burger", "mince", "mincemeat",
    "steak", "ribs", "chops", "loin", "breast", "thigh", "drumstick",
)

_PRODUCE_KEYWORDS: tuple[str, ...] = (
    "onion", "tomato", "pepper", "carrot", "potato", "garlic",
    "broccoli", "spinach", "lettuce", "cucumber", "zucchini", "courgette",
    "mushroom", "avocado", "lemon", "lime", "orange", "apple", "banana",
    "strawberry", "blueberry", "grape", "mango", "pineapple", "peach",
    "pear", "melon", "watermelon", "kiwi", "pomegranate",
    "celery", "leek", "asparagus", "kale", "chard", "eggplant", "aubergine",
    "beetroot", "fennel", "artichoke", "peas", "corn", "green beans",
    "cabbage", "cauliflower", "coliflower", "radish", "turnip",
    "spring onion", "scallion", "shallot",
    "cherry tomato", "plum tomato",
)

_STAPLE_KEYWORDS: tuple[str, ...] = (
    "flour", "sugar", "rice", "pasta", "oats", "breadcrumbs", "bread crumbs",
    "bread", "couscous", "bulgur", "polenta", "lentils", "chickpeas",
    "beans", "raisins", "dates", "nuts", "almonds", "walnuts", "cashews",
    "cornstarch", "corn flour", "maizena",
    "oil", "olive oil", "sunflower oil", "vegetable oil",
    "water", "stock", "broth", "wine", "beer", "juice",
)

# ── Public helper ─────────────────────────────────────────────────────────────

def get_pack_cap(ingredient_name: str) -> int:
    """Return the maximum packs to buy for this ingredient.

    Checks are ordered from most-restrictive to least; the first matching
    category wins.
    """
    name = (ingredient_name or "").lower().strip()

    for kw in _HERB_SPICE_KEYWORDS:
        if kw in name:
            return 2

    for kw in _CONDIMENT_KEYWORDS:
        if kw in name:
            return 2

    for kw in _EGG_KEYWORDS:
        # Only match if the whole word appears (avoid matching "eggplant")
        import re
        if re.search(rf"\b{re.escape(kw)}\b", name):
            return 2

    for kw in _DAIRY_KEYWORDS:
        if kw in name:
            return 3

    for kw in _MEAT_FISH_KEYWORDS:
        if kw in name:
            return 4

    for kw in _PRODUCE_KEYWORDS:
        if kw in name:
            return 4

    for kw in _STAPLE_KEYWORDS:
        if kw in name:
            return 6

    return 5  # default
