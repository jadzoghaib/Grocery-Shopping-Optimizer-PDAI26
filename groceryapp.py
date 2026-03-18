import json
import os

import pandas as pd
import streamlit as st
from groq import Groq

_DATA_DIR             = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
_USER_RECIPES_FILE    = os.path.join(_DATA_DIR, "user_recipes.json")
_RATING_ADJUSTMENTS_FILE = os.path.join(_DATA_DIR, "rating_adjustments.json")


def _load_user_recipes():
    try:
        if os.path.exists(_USER_RECIPES_FILE):
            with open(_USER_RECIPES_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass
    return []


def _load_rating_adjustments():
    try:
        if os.path.exists(_RATING_ADJUSTMENTS_FILE):
            with open(_RATING_ADJUSTMENTS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass
    return {}

from core.data import load_recipe_data
from components.ui import (
    apply_theme,
    render_sidebar,
    render_tab_basket,
    render_tab_calendar,
    render_tab_forum,
    render_tab_history,
    render_tab_meal_plan,
)


def _init_groq_client():
    try:
        groq_key = st.secrets.get("GROQ_API_KEY", None)
    except Exception:
        groq_key = None
    groq_key = groq_key or os.environ.get("GROQ_API_KEY")
    if groq_key:
        try:
            return Groq(api_key=groq_key)
        except Exception as e:
            st.error(f"Failed to initialize Groq client: {e}")
    return None


def init():
    defaults = {
        'messages': [],
        'meal_plan': None,
        'shopping_list': None,
        'rating_adjustments': {},
        'user_recipes': [],
        'basket': [],
    }
    for key, val in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = val

    # Load persisted data from disk on first run
    if not st.session_state['user_recipes']:
        st.session_state['user_recipes'] = _load_user_recipes()
    if not st.session_state['rating_adjustments']:
        st.session_state['rating_adjustments'] = _load_rating_adjustments()
    if 'groq_client' not in st.session_state:
        st.session_state.groq_client = _init_groq_client()


def main():
    st.set_page_config(page_title="Grocery Trip Optimizer", layout="wide")
    init()
    st.title("🛒 Grocery Trip Optimizer")

    try:
        df_recipes = load_recipe_data()
        if hasattr(df_recipes, 'attrs') and 'url_map' in df_recipes.attrs:
            st.session_state['ingredient_url_map'] = df_recipes.attrs['url_map']
            st.toast("Loaded Mercadona prices!", icon="🛒")
    except Exception as e:
        st.error(f"Error loading recipes: {e}")
        df_recipes = pd.DataFrame()

    render_sidebar(df_recipes)

    tabs = st.tabs([
        "🛒 Basket",
        "📅 Meal Planner",
        "📅 Calendar",
        "📚 History",
        "🍽️ Recipe Forum",
    ])
    with tabs[0]:
        render_tab_basket()
    with tabs[1]:
        render_tab_meal_plan(df_recipes)
    with tabs[2]:
        render_tab_calendar()
    with tabs[3]:
        render_tab_history()
    with tabs[4]:
        render_tab_forum()

    apply_theme()


if __name__ == "__main__":
    main()
