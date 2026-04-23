CUISINE_MAP = {
    "American":      ["american", "burger", "sandwich", "steak", "casserole", "comfort food", "soul",
                      "southern", "southwestern u.s.", "cajun", "tex mex", "creole", "gumbo",
                      "college food", "potluck", "kid friendly"],
    "Italian":       ["italian", "pasta", "pizza", "risotto", "spaghetti", "lasagna", "tuscan",
                      "sicilian", "roman", "manicotti", "penne", "pasta shells"],
    "Mexican/Latin": ["mexican", "taco", "burrito", "enchilada", "salsa", "guacamole", "quesadilla",
                      "fajita", "south american", "brazilian", "argentinian", "cuban", "peruvian",
                      "venezuelan", "colombian", "tex mex"],
    "Asian":         ["asian", "chinese", "japanese", "thai", "vietnamese", "indian", "korean",
                      "filipino", "indonesian", "sushi", "stir fry", "curry", "ramen", "teriyaki",
                      "szechuan", "hawaiian", "australian"],
    "Mediterranean": ["mediterranean", "greek", "turkish", "lebanese", "middle eastern", "egyptian",
                      "spanish", "portuguese", "hummus", "falafel", "couscous", "moroccan",
                      "southwest asia"],
    "African":       ["african", "moroccan", "south african", "ethiopian", "nigerian", "egyptian"],
    "Caribbean":     ["caribbean", "cuban", "jamaican", "trinidadian", "haitian"],
    "French":        ["french", "quiche", "souffle", "crepe", "provencal"],
    "European":      ["european", "german", "polish", "scandinavian", "swiss", "austrian", "english",
                      "uk", "irish", "scottish", "welsh", "dutch", "hungarian", "russian", "danish",
                      "swedish", "finnish", "norwegian", "pennsylvania dutch"],
    "Healthy":       ["healthy", "low carb", "low fat", "high protein", "keto", "paleo", "vegan",
                      "vegetarian", "gluten free", "salad", "sugar free", "low cholesterol",
                      "high fiber", "very low carbs", "lactose free", "egg free", "diabetic",
                      "kosher", "low protein", "free of"],
    "Junk Food":     ["deep fried", "fried", "junk food", "fast food", "processed", "candy", "chips",
                      "fries", "onion rings", "greasy", "cheese sauce", "battered"],
    "User Input":    ["user input"],
}

ALLOWED_RECIPE_TERMS = [
    # Proteins & meat
    "chicken", "chicken breast", "chicken thigh and leg", "chicken crockpot", "whole chicken",
    "beef", "beef liver", "beef organ meats", "roast beef", "meatloaf", "meatballs",
    "pork", "ham", "lamb", "veal", "rabbit", "duck", "duck breasts", "whole duck",
    "whole turkey", "turkey breast", "pheasant", "goose", "elk", "wild game",
    "tuna", "trout", "salmon", "bass", "halibut", "catfish", "perch", "orange roughy", "whitefish",
    "crab", "crawfish", "lobster", "mussels", "oysters", "squid", "shrimp",
    # Grains & carbs
    "rice", "white rice", "brown rice", "short grain rice", "long grain rice", "medium grain rice",
    "pasta", "pasta shells", "penne", "spaghetti", "macaroni",
    "bread", "breads", "wheat bread", "quick breads", "yeast breads", "sourdough breads",
    "oatmeal", "grains", "quinoa",
    # Vegetables & fruit
    "vegetable", "potato", "sweet potato", "yam/sweet potato", "peppers", "onions", "spinach",
    "cauliflower", "corn", "greens", "chard", "broccoli",
    "fruit", "apple", "cherries", "berries", "raspberries", "strawberry", "grapes",
    "pineapple", "plums", "melons", "papaya", "oranges", "citrus", "lemon", "lime",
    "tropical fruits", "kiwi fruit", "coconut",
    # Cuisines & regions (all extracted from dataset)
    "asian", "chinese", "japanese", "thai", "vietnamese", "indian", "korean", "filipino",
    "indonesian", "mexican", "cuban", "brazilian", "colombian", "peruvian", "venezuelan",
    "south american", "caribbean", "african", "moroccan", "south african", "egyptian",
    "greek", "turkish", "lebanese", "spanish", "portuguese", "mediterranean",
    "southwest asia", "southwestern u.s.", "cajun", "creole", "tex mex",
    "european", "german", "polish", "scandinavian", "swiss", "austrian", "scottish",
    "welsh", "dutch", "hungarian", "russian", "danish", "swedish", "finnish", "norwegian",
    "pennsylvania dutch", "canadian", "australian", "new zealand", "native american",
    "hawaiian", "vietnamese", "szechuan", "thai",
    # Dietary
    "healthy", "vegan", "vegetarian", "low cholesterol", "very low carbs", "high protein",
    "high fiber", "low protein", "lactose free", "egg free", "kosher", "gluten-free appetizers",
    "diabetic", "free of", "sugar free",
    # Meal types
    "breakfast", "brunch", "breakfast casseroles", "breakfast eggs",
    "lunch/snacks", "stew", "soup", "chili", "chowders", "clear soup",
    "salad", "salad dressings", "roast", "pot roast", "pot pie",
    "casserole", "one dish meal", "stir fry", "curry", "curries",
    "meatloaf", "meatballs", "sauces", "spreads", "chutneys",
    # Cooking methods & time
    "under 15 minutes", "under 30 minutes", "under 60 minutes", "under 4 hours",
    "< 15 mins", "< 30 mins", "< 60 mins", "< 4 hours",
    "weeknight", "crockpot", "oven", "stove top", "broil/grill", "broiled grill",
    "microwave", "pressure cooker", "dehydrator", "freezer", "refrigerator", "no cook",
    "steam", "steamed", "small appliance",
    # Other characteristics
    "easy", "beginner cook", "inexpensive", "kid friendly", "toddler friendly",
    "college food", "potluck", "for large groups", "from scratch",
    "spicy", "savory", "wild game",
    # Misc categories from dataset
    "beverages", "shakes", "smoothies", "gelatin", "nuts", "cheese", "eggs",
    "beans", "black beans", "lentil", "soy/tofu", "grains",
    "pork", "poultry", "meat", "seafood",
    "summer", "winter", "spring", "thanksgiving", "christmas", "hanukkah", "st. patrick's day",
    "ice cream", "frozen desserts",
    # User-submitted recipes
    "user input",
]

BLOCKED_RECIPE_TERMS = [
    # Candy & pure sugar
    "candy", "candies", "lollipop", "fudge", "taffy", "marshmallow", "gummy", "gummi",
    "caramel popcorn", "cotton candy", "hard candy", "chewing gum", "toffee", "brittle",
    "praline", "truffle", "nougat", "fondant", "marzipan", "rock candy", "peanut brittle",
    # Alcohol & cocktails
    "alcoholic", "alcoholic beverages", "cocktail", "cocktails", "shots", "shot",
    "liqueur", "margarita", "sangria", "mojito", "mimosa", "martini", "manhattan",
    "whiskey", "vodka", "rum", "gin", "bourbon", "champagne", "tequila", "brandy",
    "schnapps", "mead", "punch beverage", "mixed drinks", "bartending",
    "beer bread",  # keep general beer blocked as drink; cooking uses are rare in this dataset
    "wine cooler", "wine drink",
]
