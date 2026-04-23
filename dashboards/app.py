"""Dash analytics dashboards — mounted inside FastAPI at /dash/.

Four pages (routed via dcc.Location):
  /dash/overview    — Dashboard home: meal plan macro summary
  /dash/meal-plan   — Meal planner: per-day nutrition + cost breakdown
  /dash/shopping    — Shopping list: cost per ingredient + match quality
  /dash/history     — Purchase history: spending over time

Mounting trick (Dash 4 + FastAPI/Starlette):
  requests_pathname_prefix = '/dash/'   browser-facing URL prefix
  routes_pathname_prefix   = '/'        Flask route prefix (path after mount strips /dash)
"""
from __future__ import annotations

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

import dash
from dash import dcc, html, Input, Output, callback

from dashboards import cache

# ── Plotly theme ───────────────────────────────────────────────────────────────

_THEME    = "plotly_white"
_PRIMARY  = "#059669"
_COLORS   = {
    "exact":       "#059669",
    "alternative": "#ef4444",
    "none":        "#f59e0b",
    "Breakfast":   "#f59e0b",
    "Lunch":       "#3b82f6",
    "Snack":       "#8b5cf6",
    "Dinner":      "#059669",
}
_SLOT_ORDER = ["Breakfast", "Lunch", "Snack", "Dinner"]
_MACRO_COLORS = {"calories": "#6366f1", "protein": "#059669", "carbs": "#f59e0b", "fat": "#ef4444"}

# ── App setup ──────────────────────────────────────────────────────────────────

dash_app = dash.Dash(
    __name__,
    requests_pathname_prefix="/dash/",   # browser-facing prefix
    routes_pathname_prefix="/",          # Flask route prefix (Starlette strips /dash)
    suppress_callback_exceptions=True,
    title="GroceryAI Analytics",
    meta_tags=[{"name": "viewport", "content": "width=device-width, initial-scale=1"}],
)

# ── Shared layout ──────────────────────────────────────────────────────────────

_BASE_STYLE = {
    "fontFamily": "Inter, system-ui, sans-serif",
    "background": "#ffffff",
    "padding": "0",
    "margin": "0",
}

dash_app.layout = html.Div(
    [
        dcc.Location(id="url", refresh=False),
        dcc.Interval(id="interval", interval=8_000, n_intervals=0),  # refresh every 8s
        html.Div(id="page-content", style={"padding": "16px 20px"}),
    ],
    style=_BASE_STYLE,
)


# ── Helpers ────────────────────────────────────────────────────────────────────

def _empty(message: str, icon: str = "📊") -> html.Div:
    return html.Div(
        [
            html.Div(icon, style={"fontSize": "2.5rem", "marginBottom": "10px"}),
            html.P(message, style={"color": "#64748b", "fontSize": "0.9rem", "textAlign": "center"}),
        ],
        style={"display": "flex", "flexDirection": "column", "alignItems": "center",
               "justifyContent": "center", "minHeight": "200px"},
    )


def _section(title: str, children) -> html.Div:
    return html.Div(
        [html.H3(title, style={"fontSize": "0.95rem", "fontWeight": "600",
                                "color": "#1e293b", "marginBottom": "8px"}),
         *children],
        style={"marginBottom": "20px"},
    )


def _fig(fig) -> dcc.Graph:
    fig.update_layout(
        margin=dict(l=10, r=10, t=30, b=10),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family="Inter, sans-serif", size=11),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    )
    return dcc.Graph(figure=fig, config={"displayModeBar": False},
                     style={"height": "260px"})


# ── Page layouts ───────────────────────────────────────────────────────────────

def _layout_overview() -> html.Div:
    data = cache.fetch("meal_plan")
    if not data:
        return _empty("No meal plan generated yet.\nGenerate one from the Meal Planner page.", "🍽️")

    df = pd.DataFrame(data)
    for col in ["calories", "protein", "carbs", "fat", "cost"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)

    day_col  = next((c for c in df.columns if c.lower() == "day"), None)
    slot_col = next((c for c in df.columns if c.lower() in ("meal", "slot")), None)

    charts = []

    # Calories by day stacked by meal slot
    if day_col and slot_col and "calories" in df.columns:
        fig = px.bar(
            df, x=day_col, y="calories", color=slot_col,
            barmode="stack", template=_THEME,
            color_discrete_map=_COLORS,
            category_orders={slot_col: _SLOT_ORDER},
            labels={"calories": "kcal", day_col: ""},
            title="Daily Calories by Meal Slot",
        )
        charts.append(_fig(fig))

    # Macro averages
    macros_available = [m for m in ["protein", "carbs", "fat"] if m in df.columns]
    if macros_available and day_col:
        avg = df.groupby(day_col)[macros_available].sum().mean()
        fig2 = go.Figure(go.Bar(
            x=macros_available,
            y=[avg[m] for m in macros_available],
            marker_color=[_MACRO_COLORS.get(m, _PRIMARY) for m in macros_available],
            text=[f"{avg[m]:.0f}g" for m in macros_available],
            textposition="outside",
        ))
        fig2.update_layout(template=_THEME, title="Avg Daily Macros (g)",
                           yaxis_title="grams", xaxis_title="")
        charts.append(_fig(fig2))

    if not charts:
        return _empty("Meal plan data incomplete — charts unavailable.")

    return html.Div(charts)


def _layout_meal_plan() -> html.Div:
    data = cache.fetch("meal_plan")
    if not data:
        return _empty("Generate a meal plan first to see analytics.", "📅")

    df = pd.DataFrame(data)
    for col in ["calories", "protein", "carbs", "fat", "cost", "prep_time"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)

    day_col  = next((c for c in df.columns if c.lower() == "day"), None)
    slot_col = next((c for c in df.columns if c.lower() in ("meal", "slot")), None)
    charts   = []

    # Per-day macro breakdown (grouped bars)
    macros = [m for m in ["protein", "carbs", "fat"] if m in df.columns]
    if day_col and macros:
        daily = df.groupby(day_col)[macros].sum().reset_index()
        melted = daily.melt(id_vars=day_col, value_vars=macros, var_name="Macro", value_name="grams")
        fig = px.bar(
            melted, x=day_col, y="grams", color="Macro", barmode="group",
            template=_THEME, color_discrete_map=_MACRO_COLORS,
            labels={"grams": "g", day_col: ""},
            title="Daily Macronutrient Breakdown",
        )
        charts.append(_fig(fig))

    # Slot distribution pie
    if slot_col and "calories" in df.columns:
        slot_cals = df.groupby(slot_col)["calories"].sum().reset_index()
        fig2 = px.pie(
            slot_cals, names=slot_col, values="calories",
            color=slot_col, color_discrete_map=_COLORS,
            template=_THEME, title="Calorie Split by Meal Slot",
            hole=0.4,
        )
        charts.append(_fig(fig2))

    # Cost vs prep_time scatter
    if "cost" in df.columns and "prep_time" in df.columns:
        name_col = next((c for c in df.columns if c.lower() in ("name", "recipe", "meal_name")), None)
        fig3 = px.scatter(
            df, x="prep_time", y="cost",
            color=slot_col if slot_col else None,
            color_discrete_map=_COLORS,
            hover_name=name_col,
            template=_THEME,
            labels={"prep_time": "Prep Time (min)", "cost": "Cost (€)"},
            title="Recipe Cost vs Prep Time",
        )
        charts.append(_fig(fig3))

    return html.Div(charts) if charts else _empty("Meal plan data incomplete.")


def _layout_shopping() -> html.Div:
    data = cache.fetch("shopping")
    if not data:
        return _empty("Generate a shopping list first to see analytics.", "🛒")

    df = pd.DataFrame(data)

    # Normalise column names (server returns various formats)
    col_map = {}
    for raw in df.columns:
        low = raw.lower().replace(" ", "_")
        if "total" in low and "price" in low:
            col_map[raw] = "total_price"
        elif "unit" in low and "price" in low:
            col_map[raw] = "unit_price"
        elif "ingredient" in low:
            col_map[raw] = "ingredient"
        elif "match" in low and "quality" in low:
            col_map[raw] = "match_quality"
        elif "count" in low or low == "packs":
            col_map[raw] = "count"
    df = df.rename(columns=col_map)

    for col in ["total_price", "unit_price", "count"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)

    charts = []

    # Cost per ingredient (horizontal bar, top 15)
    if "ingredient" in df.columns and "total_price" in df.columns:
        top = df.nlargest(15, "total_price").sort_values("total_price")
        mq_col = "match_quality" if "match_quality" in top.columns else None
        color_seq = (
            [_COLORS.get(mq, _PRIMARY) for mq in top[mq_col]]
            if mq_col else [_PRIMARY] * len(top)
        )
        fig = go.Figure(go.Bar(
            x=top["total_price"], y=top["ingredient"],
            orientation="h",
            marker_color=color_seq,
            text=[f"€{v:.2f}" for v in top["total_price"]],
            textposition="outside",
        ))
        fig.update_layout(
            template=_THEME, title="Cost per Ingredient (€)",
            xaxis_title="€", yaxis_title="",
            height=300 + len(top) * 12,
        )
        charts.append(dcc.Graph(figure=fig, config={"displayModeBar": False},
                                style={"height": f"{300 + len(top) * 12}px"}))

    # Match quality donut
    if "match_quality" in df.columns:
        mq_counts = df["match_quality"].value_counts().reset_index()
        mq_counts.columns = ["quality", "count"]
        fig2 = px.pie(
            mq_counts, names="quality", values="count",
            color="quality", color_discrete_map=_COLORS,
            hole=0.5, template=_THEME,
            title="Match Quality Distribution",
        )
        charts.append(_fig(fig2))

    # Total cost KPI
    if "total_price" in df.columns:
        total = df["total_price"].sum()
        fig3 = go.Figure(go.Indicator(
            mode="number",
            value=total,
            number={"prefix": "€", "valueformat": ".2f"},
            title={"text": "Total Shopping Cost"},
        ))
        fig3.update_layout(template=_THEME, height=150,
                           margin=dict(l=10, r=10, t=40, b=10))
        charts.append(dcc.Graph(figure=fig3, config={"displayModeBar": False},
                                style={"height": "150px"}))

    return html.Div(charts) if charts else _empty("Shopping data incomplete.")


def _layout_history() -> html.Div:
    data = cache.fetch("history")
    if not data:
        return _empty("No purchase history yet. Complete a shopping order first.", "📦")

    records = []
    for session in data:
        date  = session.get("date", "")
        total = session.get("total", 0)
        items = session.get("items", [])
        records.append({"date": date, "total": total, "item_count": len(items)})

    df = pd.DataFrame(records)
    df["total"]      = pd.to_numeric(df["total"], errors="coerce").fillna(0)
    df["item_count"] = pd.to_numeric(df["item_count"], errors="coerce").fillna(0)
    df["date"]       = pd.to_datetime(df["date"], errors="coerce")
    df = df.sort_values("date")

    charts = []

    # Spending over time
    if len(df) >= 2:
        fig = px.line(
            df, x="date", y="total",
            markers=True, template=_THEME,
            labels={"date": "Order Date", "total": "Spend (€)"},
            title="Spending Over Time",
            color_discrete_sequence=[_PRIMARY],
        )
        charts.append(_fig(fig))
    elif len(df) == 1:
        charts.append(html.P(
            f"Only one order on record (€{df['total'].iloc[0]:.2f}). "
            "Complete more orders to see trends.",
            style={"color": "#64748b", "fontSize": "0.85rem"},
        ))

    # Item count per order
    if "item_count" in df.columns:
        fig2 = px.bar(
            df, x="date", y="item_count",
            template=_THEME, color_discrete_sequence=["#6366f1"],
            labels={"date": "", "item_count": "Items"},
            title="Items per Order",
        )
        charts.append(_fig(fig2))

    return html.Div(charts) if charts else _empty("History data incomplete.")


# ── Router callback ────────────────────────────────────────────────────────────

@callback(
    Output("page-content", "children"),
    Input("url", "pathname"),
    Input("interval", "n_intervals"),
)
def render_page(pathname: str, _n):
    p = (pathname or "/").rstrip("/") or "/"
    # Strip any /dash prefix — dcc.Location may report the full browser path.
    if p.startswith("/dash"):
        p = p[5:].rstrip("/") or "/"
    # Also handle bare path without prefix
    print(f"[Dash] render_page: raw={pathname!r}  normalised={p!r}")
    if p in ("/overview", "/", ""):
        return _layout_overview()
    if p in ("/meal-plan", "/meal_plan"):
        return _layout_meal_plan()
    if p == "/shopping":
        return _layout_shopping()
    if p == "/history":
        return _layout_history()
    # Fallback: try partial match
    if "shopping" in p:
        return _layout_shopping()
    if "meal" in p:
        return _layout_meal_plan()
    if "history" in p:
        return _layout_history()
    if "overview" in p:
        return _layout_overview()
    return _empty(f"Unknown page: {pathname!r} → {p!r}")
