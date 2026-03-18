
# Grocery Shopping Optimizer

![Python](https://img.shields.io/badge/Python-3.8+-blue.svg)
![Streamlit](https://img.shields.io/badge/Streamlit-1.0+-red.svg)
![LLM](https://img.shields.io/badge/LLM-Multi--Provider-green.svg)

An advanced app that combines linear programming, agentic RAG with tool-use, and real supermarket data to generate personalized meal plans and optimized shopping lists based on your nutritional goals, budget, and preferences.

## Key Features

### Meal Plan Optimizer
- **Nutritional Targets**: Set daily goals for Calories, Protein, Carbs, and Fat.
- **Budget & Time Constraints**: Ensure meals fit your wallet and schedule.
- **Dietary Preferences**: Filter out disliked or allergic ingredients.
- **Linear Programming (PuLP)**: Finds the optimal combination of recipes to hit your macros and minimize deviations.
- **Meal Calendar**: Visual weekly calendar view with `.ics` export for Google Calendar, Outlook, and Apple Calendar.
- **Recipe Ratings**: Rate meals with ▲/▼ buttons — ratings influence future meal plan generation.
- **Recipe Forum**: Add your own recipes (manually, via URL, or from YouTube), which are prioritized in meal planning.
- **Comparable Recipe Finder**: Swap any meal slot with a nutritionally similar alternative (±30% macros).

### Real-Time Shopping List
- **Mercadona Product Matching**: TF-IDF semantic search matches ingredients to real Mercadona products with prices and buy links.
- **Bilingual Lookup**: Falls back to Spanish translations for ingredients not found in English.
- **AI Quantity Refinement**: Groq LLM optimizes pack sizes and quantities on top of the product matches.
- **SKU Override**: Click any product in the list to swap it for an alternative Mercadona match.
- **Ingredient Aggregation**: Compiles and deduplicates all ingredients from your meal plan into a consolidated list.

### Agentic RAG Assistant (Sidebar)
- **Multi-Provider LLM Support**: Works with OpenAI, Groq, Anthropic, Mistral, Cohere, Gemini, Ollama, and OpenRouter.
- **Tool-Use Architecture**: The LLM autonomously decides when to call `search_recipes` or `search_mercadona` — no hardcoded routing.
- **Text-Based Tool Call Fallback**: Handles models (e.g. DeepSeek via Ollama) that output tool calls as plain text instead of structured API calls.
- **Basket-Aware Context**: Every chat message includes your current basket contents so the assistant can suggest complementary items.
- **Full Conversation History**: The assistant remembers previous messages within a session.
- **Basket Add from Chat**: The assistant can add Mercadona products directly to your basket via a single confirmation button.

### Basket Tab
- **KPI Metrics Bar**: Live display of total cost, item count, items from meal plan, and manual/chat additions.
- **Interactive AgGrid Table**: Drag rows to reorder, multi-select checkboxes for bulk removal, inline cell editing.
- **PDF Export**: Download your shopping list as a branded PDF with a single click.
- **Order History**: Confirmed purchases are saved to history for future reference.

### Visualizations
- **Macro Comparison Chart**: Plotly bar chart comparing average daily nutrition against your targets.
- **Nutrition Metrics**: Per-macro delta indicators showing how close your plan is to your goals.

## Installation

```bash
# Clone the repository
git clone https://github.com/jadzoghaib/Grocery-Shopping-Optimizer-PDAI26.git

# Navigate to the project directory
cd Grocery-Shopping-Optimizer-PDAI26

# Install required dependencies
pip install -r requirements.txt
```

## Usage

```bash
streamlit run groceryapp.py
```

With micromamba (recommended):
```bash
micromamba run -n grocery-optimizer streamlit run groceryapp.py
```

## Technology Stack

| Component | Technology |
|---|---|
| Web framework | Streamlit |
| Optimization | PuLP (linear programming) |
| Visualization | Plotly |
| Product search | scikit-learn TF-IDF |
| LLM providers | OpenAI, Groq, Anthropic, Mistral, Cohere, Gemini, Ollama, OpenRouter |
| RAG architecture | Agentic tool-use (structured + text-based fallback) |
| Basket table | streamlit-aggrid |
| PDF export | ReportLab |
| Data | Food.com recipes (5000 rows), Mercadona product catalogue |

## Configuration

API keys are managed via Streamlit secrets (`.streamlit/secrets.toml`) or entered directly in the sidebar UI at runtime. No key is required for Ollama (local models).

Supported LLM providers and their default models:

| Provider | Default Model |
|---|---|
| OpenAI | gpt-4o-mini |
| Groq | llama-3.3-70b-versatile |
| Anthropic | claude-sonnet-4-6 |
| Mistral | mistral-small-latest |
| Cohere | command-r-plus |
| Gemini | gemini-2.0-flash |
| Ollama | deepseek-v3.1:671b-cloud |
| OpenRouter | meta-llama/llama-3.3-70b-instruct:free |

## Notes

- The Ollama provider requires a running Ollama instance at `http://localhost:11434`.
- The assistant uses tool-use RAG: it calls `search_recipes` or `search_mercadona` only when needed, so general conversation works without any retrieval context.
- Recipe nutrition values are normalized per serving before display.
