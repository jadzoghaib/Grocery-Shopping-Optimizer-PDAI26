"""
Recipe import helpers.

Supports:
  - Web URL  : JSON-LD structured data first, LLM fallback
  - YouTube  : transcript via youtube-transcript-api, then LLM parsing
"""

import json
import re


# ── Shared LLM call ───────────────────────────────────────────────────────────

_EXTRACT_SYSTEM = (
    "You are a recipe extraction assistant. Given text from a recipe source, "
    "extract the recipe and return ONLY a JSON object. "
    "Leave numeric fields as 0 if the information is not available."
)

_EXTRACT_PROMPT = """Extract the recipe from the following text and return a JSON object with exactly these keys:
{
  "name": "Recipe name",
  "ingredients": ["quantity unit ingredient", ...],
  "instructions": "Step 1: ...\\nStep 2: ...",
  "category": "Main Dish|Breakfast|Lunch/Snacks|Dessert|Salad|Soup|Pasta|Vegetable|Other",
  "calories": 0,
  "protein": 0,
  "carbs": 0,
  "fat": 0,
  "prep_time": 0
}

Text:
{text}"""


def _call_llm(text: str, groq_client) -> dict:
    prompt = _EXTRACT_PROMPT.replace("{text}", text[:6000])
    resp = groq_client.chat.completions.create(
        messages=[
            {"role": "system", "content": _EXTRACT_SYSTEM},
            {"role": "user",   "content": prompt},
        ],
        model="llama-3.3-70b-versatile",
        temperature=0,
        response_format={"type": "json_object"},
        max_tokens=1024,
    )
    return json.loads(resp.choices[0].message.content)


# ── JSON-LD parser ────────────────────────────────────────────────────────────

def _parse_jsonld(soup) -> dict | None:
    """Try to extract a Recipe from JSON-LD structured data on the page."""
    for tag in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(tag.string or "")
            # data can be a single object or a list
            items = data if isinstance(data, list) else [data]
            for item in items:
                # Handle @graph
                if "@graph" in item:
                    items.extend(item["@graph"])
                    continue
                if item.get("@type") in ("Recipe", "schema:Recipe"):
                    return item
        except Exception:
            continue
    return None


def _recipe_from_jsonld(ld: dict) -> dict:
    """Convert a JSON-LD Recipe object to our internal format."""

    def _text(v):
        if isinstance(v, str):
            return v
        if isinstance(v, dict):
            return v.get("text", v.get("name", ""))
        return str(v)

    # Ingredients
    raw_ings = ld.get("recipeIngredient", [])
    ingredients = [_text(i) for i in raw_ings if i]

    # Instructions
    raw_inst = ld.get("recipeInstructions", "")
    if isinstance(raw_inst, str):
        instructions = raw_inst.strip()
    elif isinstance(raw_inst, list):
        steps = []
        for idx, step in enumerate(raw_inst, 1):
            t = _text(step)
            if t:
                steps.append(f"Step {idx}: {t}")
        instructions = "\n".join(steps)
    else:
        instructions = ""

    # Nutrition
    nutr = ld.get("nutrition", {}) or {}
    def _num(val):
        if val is None:
            return 0
        m = re.search(r"[\d.]+", str(val))
        return float(m.group()) if m else 0

    # Prep time (ISO 8601 duration PT30M etc.)
    def _parse_duration(d):
        if not d:
            return 0
        h = re.search(r"(\d+)H", str(d))
        m = re.search(r"(\d+)M", str(d))
        return int(h.group(1) if h else 0) * 60 + int(m.group(1) if m else 0)

    total_time = _parse_duration(ld.get("totalTime") or ld.get("cookTime") or ld.get("prepTime"))

    return {
        "name":         ld.get("name", "").strip(),
        "ingredients":  ingredients,
        "instructions": instructions,
        "category":     "Main Dish",
        "calories":     _num(nutr.get("calories")),
        "protein":      _num(nutr.get("proteinContent")),
        "carbs":        _num(nutr.get("carbohydrateContent")),
        "fat":          _num(nutr.get("fatContent")),
        "prep_time":    total_time,
    }


# ── URL import ────────────────────────────────────────────────────────────────

def import_from_url(url: str, groq_client=None) -> dict:
    """
    Fetch a recipe from a web URL.
    Returns a dict with keys: name, ingredients (list), instructions,
    category, calories, protein, carbs, fat, prep_time.
    Raises on failure.
    """
    import requests
    from bs4 import BeautifulSoup

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120 Safari/537.36"
        )
    }
    resp = requests.get(url, headers=headers, timeout=12)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    # 1. Try JSON-LD
    ld = _parse_jsonld(soup)
    if ld:
        result = _recipe_from_jsonld(ld)
        if result.get("name") and result.get("ingredients"):
            return result

    # 2. LLM fallback
    if not groq_client:
        raise ValueError("Could not extract recipe from structured data and no LLM client available.")

    text = soup.get_text(separator="\n", strip=True)
    return _call_llm(text, groq_client)


# ── YouTube import ────────────────────────────────────────────────────────────

def _extract_video_id(url: str) -> str:
    patterns = [
        r"(?:v=|youtu\.be/|embed/|shorts/)([A-Za-z0-9_-]{11})",
    ]
    for p in patterns:
        m = re.search(p, url)
        if m:
            return m.group(1)
    raise ValueError(f"Cannot extract YouTube video ID from: {url}")


def import_from_youtube(url: str, groq_client) -> dict:
    """
    Fetch a recipe from a YouTube video via its transcript.
    Returns same dict format as import_from_url.
    Requires groq_client for parsing.
    """
    from youtube_transcript_api import YouTubeTranscriptApi

    video_id = _extract_video_id(url)
    ytt = YouTubeTranscriptApi()
    transcript = ytt.fetch(video_id)
    text = " ".join(t.text for t in transcript)

    result = _call_llm(text, groq_client)
    return result
