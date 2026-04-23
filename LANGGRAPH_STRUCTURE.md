# LangGraph Structure — Grocery Shopping Optimizer

All LLM pipelines. Every agent uses **Groq `llama-3.3-70b-versatile`** as the single provider.

---

## 1. Grocery RAG Agent — `services/rag.py`

**Pattern:** `create_react_agent` (prebuilt ReAct loop)  
**Entry:** `rag_answer(question, messages_history, api_key) → str`

| Component | Implementation |
|---|---|
| Memory | LangChain message list (SystemMessage + history + HumanMessage) |
| Tools | `search_recipes` — TF-IDF on recipe DB · `search_mercadona` — TF-IDF on Mercadona DB |
| Orchestrator | `ChatGroq` temp=0.3 |
| Planning | ReAct loop — LLM decides which tool to call and when |
| Feedback | Tool results injected back as ToolMessages; loop continues until no tool calls |

```mermaid
flowchart TD
    A([User message + history]) --> B[Build message state]
    B --> C[agent_node · ChatGroq · tools bound]
    C --> D{Tool calls?}
    D -->|search_recipes| E1[TF-IDF on recipe DB]
    D -->|search_mercadona| E2[TF-IDF on Mercadona DB]
    E1 & E2 -->|ToolMessage injected| C
    D -->|No| F[Final AIMessage]
    F --> G[parse_basket_intent · extract add_to_basket JSON]
    G --> H([reply + basket_items])
```

---

## 2. Nutrition Coach Agent — `services/nutrition_agent.py`

**Pattern:** `create_react_agent`  
**Entry:** `nutrition_answer(question, messages_history, api_key) → str`

| Component | Implementation |
|---|---|
| Memory | LangChain message list |
| Tools | `calculate_macros` — Mifflin-St Jeor TDEE · `lookup_food` — USDA CSV · `search_nutrition_knowledge` — KB search |
| Orchestrator | `ChatGroq` temp=0.3 |
| Planning | Must call `calculate_macros` before stating targets; must call `lookup_food` before citing nutrition values |
| Feedback | Tool results loop back; agent refines until complete |

```mermaid
flowchart TD
    A([Nutrition question]) --> B[Build message state]
    B --> C[nutrition_agent_node · ChatGroq · 3 tools]
    C --> D{Tool call?}
    D -->|calculate_macros| E1[Mifflin-St Jeor TDEE + macro targets]
    D -->|lookup_food| E2[Local CSV · kcal + macros per 100g]
    D -->|search_nutrition_knowledge| E3[KB directory search]
    E1 & E2 & E3 -->|ToolMessage injected| C
    D -->|No| F[Final AIMessage]
    F --> G[parse_nutrition_plan · extract nutrition_plan JSON]
    G --> H([reply + optional weekly plan export])
```

---

## 3. Basket Debate — Multi-Agent — `services/debate.py`

**Pattern:** Two `create_react_agent` instances + Moderator plain invoke  
**Entry:** `debate_basket(items, api_key) → dict`

| Component | Budget Optimizer | Nutritionist |
|---|---|---|
| Memory | LangGraph message state | LangGraph message state |
| Tools | `get_basket_cost_breakdown` · `identify_overbuying` · `get_category_cost_split` | `check_food_group_coverage` · `identify_ultra_processed` · `count_produce_variety` |
| Orchestrator | `ChatGroq` temp=0.3 | `ChatGroq` temp=0.3 |
| Planning | Calls all 3 cost tools, then synthesises | Calls all 3 nutrition tools, then synthesises |
| Feedback | Tool results loop back | Tool results loop back |

```mermaid
flowchart TD
    START([Basket items]) --> FMT[_parse_basket · normalise]

    FMT --> BA & NA

    subgraph BA[Budget Agent · create_react_agent]
        B1[ChatGroq] --> B2{tool?}
        B2 -->|cost_breakdown| BT1[items ranked by spend]
        B2 -->|overbuying| BT2[excess perishables]
        B2 -->|category_split| BT3[protein/produce/pantry %]
        BT1 & BT2 & BT3 --> B1
        B2 -->|done| BOUT[4-5 bullet argument]
    end

    subgraph NA[Nutrition Agent · create_react_agent]
        N1[ChatGroq] --> N2{tool?}
        N2 -->|food_group_coverage| NT1[present / missing groups]
        N2 -->|ultra_processed| NT2[processed items flagged]
        N2 -->|produce_variety| NT3[distinct fruit+veg count]
        NT1 & NT2 & NT3 --> N1
        N2 -->|done| NOUT[4-5 bullet argument]
    end

    BOUT & NOUT --> MOD[Moderator · plain ChatGroq · temp=0.2\nneutral 3-bullet synthesis]
    MOD --> END([budget + nutrition + verdict])
```

---

## 4. News RAG + CAG — `services/news_rag.py`

**Pattern:** LlamaIndex `VectorStoreIndex` (RAG path) + Groq LLM preprocessing (CAG path)  
**Entry:** `query_news(question, api_key) → dict`

```mermaid
flowchart TB
    subgraph OFFLINE[Offline · APScheduler every 6h]
        SRC[fetch_health_news\nPubMed RSS × 2 · Huberman RSS\nDuckDuckGo × 3]

        SRC --> CAG & RAG

        subgraph CAG[CAG Path — LLM Preprocessing]
            C1[Groq LLM\nextract per article:\nmain_finding · evidence_level\nsupplements · key_stats · applicability]
            C2[(news_kv_cache.json)]
            C1 --> C2
        end

        subgraph RAG[RAG Path — Vector Embedding]
            R1[HuggingFaceEmbedding\nBAAI/bge-small-en-v1.5 384-dim]
            R2[(Qdrant · local · data/qdrant_news/)]
            R1 --> R2
        end
    end

    subgraph QUERY[Query Time]
        Q([User question])
        Q --> VS[Qdrant vector search · top-5 chunks]
        Q --> KV[Load news_kv_cache.json · all preprocessed summaries]
        VS & KV --> MERGE[Combined prompt\nKV cache section + retrieved context section]
        MERGE --> GEN[Groq LLM · grounded answer]
        GEN --> ANS([answer + sources + kv_cache_used flag])
    end
```

---

## 5. Shopping Pipeline — StateGraph — `core/shopping.py`

**Pattern:** LangGraph `StateGraph` with typed state and conditional fallback edges  
**Entry:** `optimize_shopping_list_groq(items, groq_client, people_count) → DataFrame`

```mermaid
flowchart TD
    START([all_items + people_count]) --> N1

    subgraph P1[Pass 1 · LLM Consolidation]
        N1[pass1_node\nGroq LLM · ConsolidationResponse\nmerge dupes · normalise units]
        G1{Guards?\nunit_sanity + coverage}
        FB1[fallback_pass1_node\nrule_based_consolidate]
        N1 --> G1
        G1 -->|Fail| FB1
    end

    G1 -->|Pass| N2
    FB1 --> N2

    subgraph P2[Pass 2 · TF-IDF Retrieval — no LLM]
        N2[pass2_node\n_search_bilingual_scored\ntop-5 candidates + cosine score]
    end

    N2 --> N3

    subgraph P3[Pass 3 · LLM SKU Selection]
        N3[pass3_node\nGroq LLM × batches of 5\nSelectionResponse · match_quality]
        G3{Per-item guards?\nhallucination · price · URL}
        FB3[fallback_pass3_node\nrule_based_select per item]
        REC[reconcile_node\nLLM tag vs deterministic classifier\ntrust deterministic on disagree]
        N3 --> G3
        G3 -->|Item fails| FB3
        G3 -->|Item passes| REC
        FB3 --> REC
    end

    REC --> COMPILE[compile_node\nbuild DataFrame\n_source · match_quality · match_reason]
    COMPILE --> END([DataFrame])
```

**State type:**

```python
class ShoppingState(TypedDict):
    all_items:    list        # raw ingredient rows from meal plan
    people_count: int
    groq_client:  Any
    feedback:     dict        # data/pack_feedback.json
    raw_lines:    list[str]
    consolidated: list[dict]  # Pass 1 output
    pass1_source: str         # "llm" | "fallback"
    cand_ctx:     list[dict]  # Pass 2 output
    rows:         list[dict]  # Pass 3 output
    error:        str | None
```

---

## Full System Overview

```mermaid
flowchart LR
    subgraph FE[Frontend SPA]
        P1[Chat Panel]
        P2[Planner + Basket]
        P3[Nutrition Coach]
        P4[Body Optimizer]
    end

    subgraph API[FastAPI server.py]
        E1[/api/chat]
        E2[/api/shopping-list/generate]
        E3[/api/nutrition-chat]
        E4[/api/debate]
        E5[/api/body/news/query]
    end

    subgraph LANG[LangGraph Agents]
        G1[Grocery RAG\ncreate_react_agent · 2 tools]
        G2[Nutrition Coach\ncreate_react_agent · 3 tools]
        G3[Budget Optimizer\ncreate_react_agent · 3 tools]
        G4[Nutritionist\ncreate_react_agent · 3 tools]
        G5[Moderator · plain invoke]
    end

    subgraph PIPE[Other Pipelines]
        S1[Shopping StateGraph\nPass1 → Pass2 → Pass3]
        S2[News RAG+CAG\nQdrant + KV Cache]
    end

    P1 --> E1 --> G1
    P3 --> E3 --> G2
    P2 --> E2 --> S1
    P2 --> E4 --> G3 & G4 --> G5
    P4 --> E5 --> S2

    GROQ(["☁️ Groq · llama-3.3-70b-versatile"])
    G1 & G2 & G3 & G4 & G5 & S1 & S2 -.->|all LLM calls| GROQ
```
