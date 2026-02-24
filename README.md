
# Grocery Shopping Optimizer

![Python](https://img.shields.io/badge/Python-3.8+-blue.svg)
![Streamlit](https://img.shields.io/badge/Streamlit-1.0+-red.svg)
![Groq](https://img.shields.io/badge/LLM-Groq-green.svg)

An advanced app that combines linear programming, LLMs, and real supermarket data to generate personalized meal plans and optimized shopping lists based on your nutritional goals, budget, and preferences.

## Key Features

### Meal Plan Optimizer
- **Nutritional Targets**: Set daily goals for Calories, Protein, Carbs, and Fat.
- **Budget & Time Constraints**: Ensure meals fit your wallet and schedule.
- **Dietary Preferences**: Filter out disliked or allergic ingredients.
- **Linear Programming (PuLP)**: Finds the optimal combination of recipes to hit your macros and minimize deviations.
- **Recipe Forum**: Add your own recipes, which are prioritized in meal planning.
- **Pinned Recipes**: Optionally pin favorite recipes for inclusion.

### Real-Time Shopping List
- **Mercadona API Integration**: Fetches real product prices, names, and links from Mercadona supermarket.
- **Groq LLM Matching**: Uses Groq LLM to match generic ingredients to store products and optimize the cart.
- **Ingredient Aggregation**: Compiles all ingredients from your meal plan into a consolidated shopping list.
- **Leftover Tracking**: Adds leftover items to a pantry for future use.

### Modern User Interface
- **Multi-tab Design**: Navigate between Meal Plan, Pantry, Order History, and Recipe Forum.
- **Interactive Elements**: Adjust parameters in real-time and see effects instantly.
- **Visualizations**: Compare average daily nutrition against targets using Plotly charts.
- **Debug Features**: Expanders show ingredient lists before and after grouping, and highlight dropped/skipped entries.

## Installation

```bash
# Clone the repository
git clone <your-repo-url>

# Navigate to the project directory
cd Grocery-Shopping-Optimizer

# Install required dependencies
pip install -r requirements.txt
```

## Usage

```bash
# Run the Streamlit app
streamlit run groceryapp.py
```

## Technology Stack

- **Streamlit**: Interactive web application
- **PuLP**: Linear programming optimization
- **Plotly**: Data visualization
- **Groq LLM**: Ingredient matching and cart optimization
- **Pandas & NumPy**: Data manipulation and analysis
- **Mercadona API**: Real supermarket product data

## Notes

- To use Groq LLM features, ensure you have a valid Groq API key set in your environment.
- The Recipe Forum allows you to add custom recipes, which are prioritized in meal planning.
- Debug expanders help diagnose missing shopping cart entries.
