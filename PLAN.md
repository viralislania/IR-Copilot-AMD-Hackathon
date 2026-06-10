# IR-Copilot — Autonomous Earnings Call Script, Deck & Q&A Cheat-Sheet
### A grounded, multi-agent Investor-Relations workflow on AMD ROCm

> **Note:** This is the original single-file summary. The **authoritative, expanded plan now
> lives in the [`docs/`](docs/index.md) MkDocs site** (`mkdocs serve`), which reflects the
> latest decisions: **MI300X** (no quantization, 70B full-precision), **CopilotKit** as the
> primary UI (Flutter GenUI optional), a **multimodal wiki** (PDF/image/audio/video), a
> dedicated **competitor-comparison** agent, and **fine-tuning as the critical feature**.

> **One-liner:** A multi-agent system that ingests a company's quarterly financials,
> predicts the hardest questions institutional investors will ask, and autonomously drafts
> a compliant earnings-call script, a slide-deck outline, and a CEO/CFO "Q&A Cheat Sheet" —
> with **every number and claim traced to evidence**, served by **open-source LLMs on AMD
> GPUs (ROCm + vLLM)**, and reviewed **with a human in the loop** through a live, streaming
> **Flutter GenUI** front-end.

---

## 0. Why this wins the hackathon (judge-facing summary)

| Required capability | How we deliver it |
|---|---|
| **AMD ROCm + vLLM (critical)** | All generation/reasoning/embedding models served by **vLLM on ROCm** (MI300X / Radeon) via an OpenAI-compatible endpoint. Throughput + token-budget numbers measured live. |
| **LangGraph** | 6-node multi-agent state machine with a **human-in-the-loop interrupt** and SSE/WebSocket streaming. |
| **Qdrant (vector DB)** | "IR Wiki at scale" — millions of transcript/filing/news chunks; hybrid + reranked retrieval. (ChromaDB swap documented as fallback.) |
| **Flutter GenUI** | Backend agents emit **A2UI v0.9** messages over an **A2A WebSocket**; Flutter renders live cards and streams partial results. |
| **RAG / LLM wiki at scale** | Confirmed-evidence-only index of transcripts, SEC filings, news, competitor calls. |
| **Open-source models only** | Llama-3.1-8B, Mistral-7B, DeepSeek-R1-Distill, BGE embeddings, FinBERT — all from Hugging Face. |
| **No missing / hallucinated financials** | A **Financial Fact Store** with deterministic slotting + a **numeric grounding verifier** that rejects any number not backed by a source. |
| **Grounding & evidence everywhere** | Every sentence in the script/deck/cheat-sheet carries a citation chip (source, date, value, URL). |
| **Human in the loop** | LangGraph `interrupt` pauses before finalizing the draft; reviewer edits/approves in the Flutter UI. |
| **Streaming backend → Flutter** | Partial agent outputs streamed as `updateComponents` / `updateDataModel`. |
| **Yahoo Finance / defeatbeta-api** | Primary data via `defeatbeta-api`; `yfinance` fallback. |
| **News / social sentiment** | News-search tool + FinBERT sentiment → a "Market Sentiment" screen. |
| **Kaggle / HF demo data** | HF earnings-call + financial-phrasebank datasets; Kaggle Motley-Fool transcripts for demo. |
| **Unsloth fine-tuning highlight** | QLoRA fine-tune of the Predictive-Analyst model to predict investor questions — boosts recall **and** cuts prompt tokens (no few-shot stuffing). |

---

## 1. Problem & user

**User:** the Investor Relations (IR) team of a public company (IR Officer + CFO + CEO).
**Pain:** Before every quarterly earnings call they spend 1–2 weeks manually: pulling
financials, reading competitor calls, guessing analyst questions, drafting the CEO script,
building the deck, and prepping a Q&A cheat sheet. The work is error-prone (a single wrong
number on a call is a compliance/market event) and repetitive.

**Our promise:** Compress that to minutes, with **zero tolerance for wrong numbers** and a
**human approval gate** before anything is finalized.

---

## 2. The multi-agent workflow (maps directly to the idea)

```
                          ┌──────────────────────────────────────────────┐
                          │              LangGraph Orchestrator            │
                          └──────────────────────────────────────────────┘
   (1) Data Extraction ──► (2) Sentiment & News ──► (3) Predictive Analyst
        Agent                    Agent                     Agent
          │                        │                         │
          ▼                        ▼                         ▼
   Financial Fact Store      Sentiment snapshot       Predicted Q&A list
   (numbers + provenance)    (FinBERT + news)         (RAG over IR Wiki)
          └──────────────┬─────────────┴──────────────┬───────────┘
                         ▼                             ▼
                 (4) Drafting Agent ───────► (5) Grounding Verifier
                 script + deck + cheat        (numeric + claim check)
                         │                             │
                         └────────────► (6) Human-in-the-Loop ◄─── reviewer edits
                                          (LangGraph interrupt)
                                                  │ approve
                                                  ▼
                                   Final artifacts + learning loop
```

| # | Agent | Job | Key tech |
|---|---|---|---|
| 1 | **Data Extraction Agent** | Pull all quarterly financials + ratios from `defeatbeta-api`; validate & normalize into a typed **Financial Fact Store** with source provenance. | defeatbeta-api, DuckDB, Pydantic |
| 2 | **Sentiment & News Agent** | Search recent news + social posts on the ticker; classify with FinBERT; summarize prevailing narrative + risk topics. | News-search tool, FinBERT (vLLM/transformers) |
| 3 | **Predictive Analyst Agent** | RAG over past transcripts, competitor calls, filings, and the sentiment snapshot to predict the **hardest institutional-investor questions**. **(Unsloth fine-tuned.)** | Qdrant RAG + fine-tuned DeepSeek/Llama on vLLM |
| 4 | **Drafting Agent** | Synthesize everything into (a) earnings-call script, (b) deck bullet outline, (c) CEO/CFO Q&A cheat sheet — numbers **slotted**, not generated. | Mistral-7B / Llama-3.1-8B on vLLM |
| 5 | **Grounding Verifier** | Re-check every numeric token + factual claim against the Fact Store / retrieved evidence; flag or block unsupported content. | Deterministic checker + NLI model |
| 6 | **Human-in-the-Loop** | Pause; reviewer approves/edits each section in Flutter; edits feed back. | LangGraph `interrupt`, Flutter GenUI |

---

## 3. Technical architecture

```
┌─────────────────────────── FLUTTER (GenUI) FRONT-END ───────────────────────────┐
│  Screens: Setup ▸ Financial Snapshot ▸ Market Sentiment ▸ Predicted Q&A ▸        │
│           Draft Script (HITL) ▸ Deck Outline ▸ Q&A Cheat Sheet                   │
│  genui + genui_a2a  ── A2uiAgentConnector (WebSocket) ── renders A2UI v0.9 cards │
└───────────────────────────────▲───────────────────┬─────────────────────────────┘
        UserActionEvent (approve/edit)  │   │   updateComponents / updateDataModel (stream)
                                        │   ▼
┌──────────────────────────── BACKEND (Python / FastAPI) ──────────────────────────┐
│  A2A WebSocket server  ←→  A2UI emitter (maps agent events → A2UI messages)       │
│  ───────────────────────────────────────────────────────────────────────────────│
│  LangGraph StateGraph  (nodes 1–6, conditional edges, interrupt_before=[hitl])   │
│  Checkpointer (MemorySaver/SQLite) for resume after human edit                    │
│  ───────────────────────────────────────────────────────────────────────────────│
│  Tools:  defeatbeta-api │ yfinance │ news-search │ Qdrant retriever │ verifier    │
│  Financial Fact Store (Pydantic + DuckDB)   IR Wiki ingestion pipeline            │
└───────────────────────────────▲───────────────────────────────▲──────────────────┘
                                 │ OpenAI-compatible HTTP        │
┌──────────────────── AMD ROCm GPU NODE (vLLM serving) ─────────────────────────────┐
│  vLLM (ROCm)  ── /v1/chat/completions , /v1/embeddings                            │
│   • Mistral-7B-Instruct-v0.3      (Drafting Agent)                                │
│   • DeepSeek-R1-Distill-Llama-8B  (Predictive Analyst, fine-tuned LoRA)           │
│   • Llama-3.1-8B-Instruct         (general reasoning / verifier NLI)              │
│   • BAAI/bge-base-en-v1.5         (embeddings for Qdrant)                         │
│   • ProsusAI/finbert              (sentiment; transformers on ROCm)               │
└───────────────────────────────────────────────────────────────────────────────────┘
```

**Why this shape:** the model node is the only GPU dependency and is fully open-source on
**AMD ROCm**; everything above it is provider-neutral (talks plain OpenAI HTTP), so the demo
runs identically on an MI300X box or a Radeon dev card.

---

## 4. Component deep-dives

### 4.1 Data layer — accurate financials (defeatbeta-api)

`defeatbeta-api` (pip: `defeatbeta-api`, Python 3.11+, data hosted on Hugging Face
`yahoo-finance-data` + DuckDB/`cache_httpfs` for sub-second SQL) gives us every metric the
brief lists. `yfinance` is the fallback for any gap.

```python
from defeatbeta_api.data.ticker import Ticker

t = Ticker("NVDA")
facts = {
    "price":            t.price(),
    "ttm_eps":          t.ttm_eps(),
    "ttm_pe":           t.ttm_pe(),
    "market_cap":       t.historical_market_cap(),
    "ps_ratio":         t.historical_ps_ratio(),
    "pb_ratio":         t.historical_pb_ratio(),
    "peg_ratio":        t.historical_peg_ratio(),
    "roe":              t.historical_roe(),
    "roa":              t.historical_roa(),
    "roic":             t.historical_roic(),
    "wacc":             t.historical_wacc(),
    "equity_multiplier":t.historical_equity_multiplier(),
    "asset_turnover":   t.historical_asset_turnover(),
    "income_stmt":      t.quarterly_income_statement(),
    "revenue_segment":  t.revenue_by_segment(),
    "revenue_geo":      t.revenue_by_geography(),
    "sec_filings":      t.sec_filing(),
    "news":             t.stock_news(),
}
transcripts = t.earning_call_transcripts()           # list + get_transcript(year, quarter)
```

**Financial Fact Store** — the anti-hallucination backbone. Every metric becomes a typed,
addressable fact with provenance:

```python
class FinancialFact(BaseModel):
    metric: str            # "ttm_eps"
    period: str            # "FY2026Q1"
    value: float
    unit: str              # "USD", "%", "x", "USD_bn"
    source: str            # "defeatbeta-api:ttm_eps"
    source_url: str | None # SEC filing / dataset URL
    as_of: date
    fact_id: str           # stable hash → cited in UI as [F-0007]
```

The LLM **never invents numbers**. It is given fact IDs and writes templated slots like
`Revenue was {{F-0012}} ({{F-0012.value}})`; a deterministic renderer substitutes verified
values. See §5 for the verifier.

---

### 4.2 IR Wiki — RAG at scale (Qdrant)

The "LLM wiki at scale" is a Qdrant collection of everything an analyst would read:

| Corpus | Source | Volume (demo) |
|---|---|---|
| Past earnings-call transcripts (target co.) | defeatbeta-api / Kaggle Motley-Fool | ~40 calls |
| Competitor transcripts | defeatbeta-api (peer tickers) | ~200 calls |
| SEC filings (10-K/10-Q) | defeatbeta-api `sec_filing()` | ~50 docs |
| Stock news | `stock_news()` + news-search tool | rolling |
| HF earnings-call Q&A datasets | `jlh-ibm/earnings_call`, `lamini/earnings-calls-qa` | for fine-tune + eval |

**Pipeline:** chunk (≈512 tokens, sentence-aware, section-tagged) → embed with
`BAAI/bge-base-en-v1.5` (served by vLLM `/v1/embeddings` on ROCm) → upsert to Qdrant with
rich payload `{ticker, doc_type, period, speaker, role(analyst|exec), url, char_span}`.

**Retrieval:** hybrid (dense + payload filter on ticker/period) → **BGE reranker** top-k →
return chunks **with citations**. Only **confirmed/sourced** chunks are indexed (mirrors the
repo's `incident-memory-rag` "confirmed-only" rule), so retrieval never surfaces speculation.

> *ChromaDB fallback:* identical interface behind a `VectorStore` protocol; swap by env var
> `VECTOR_BACKEND=chroma`. Qdrant is primary for payload-filtered hybrid search at scale.

---

### 4.3 LangGraph orchestration

```python
class IRState(TypedDict):
    ticker: str
    period: str
    facts: list[FinancialFact]          # node 1
    sentiment: SentimentSnapshot        # node 2
    predicted_questions: list[Question] # node 3
    draft: DraftBundle                  # node 4  (script, deck, cheat_sheet)
    verification: VerifyReport          # node 5
    human_feedback: HumanEdit | None    # node 6
    messages: Annotated[list, add_messages]

g = StateGraph(IRState)
g.add_node("extract",    data_extraction_agent)
g.add_node("sentiment",  sentiment_news_agent)
g.add_node("predict",    predictive_analyst_agent)
g.add_node("draft",      drafting_agent)
g.add_node("verify",     grounding_verifier)
g.add_node("hitl",       human_review_node)
g.add_node("finalize",   finalize_and_learn)

g.set_entry_point("extract")
g.add_edge("extract", "sentiment")
g.add_edge("sentiment", "predict")
g.add_edge("predict", "draft")
g.add_edge("draft", "verify")
# verifier loops back to draft if unsupported numbers/claims found
g.add_conditional_edges("verify", lambda s: "hitl" if s["verification"].passed else "draft")
g.add_edge("hitl", "finalize")

graph = g.compile(
    checkpointer=MemorySaver(),       # SQLite in prod → resume after human edit
    interrupt_before=["hitl"],        # <-- HUMAN-IN-THE-LOOP gate
)
```

- **Streaming:** `graph.astream(..., stream_mode="updates")` emits each node's partial output;
  the A2UI emitter converts those into `updateComponents`/`updateDataModel` messages.
- **HITL:** execution pauses at `interrupt_before=["hitl"]`; the Flutter approve/edit action
  resumes via `graph.ainvoke(Command(resume=human_edit), config={thread_id})`.
- **Learning loop:** approved edits + final Q&A are written back to the IR Wiki (Qdrant) so the
  next quarter's prediction improves — same pattern as the repo's `langgraph-orchestration`
  confirmed-incident write-back.

---

### 4.4 Market Sentiment section (news + social)

- **News-search tool:** `defeatbeta-api.stock_news()` + a web/news search tool (WebSearch or a
  free News API) for last-N-days headlines on the ticker and its peers.
- **Social sentiment:** pull recent posts (e.g., a Kaggle/HF stock-tweets dataset for the demo;
  pluggable live source) and classify with **FinBERT (`ProsusAI/finbert`)**.
- **Output `SentimentSnapshot`:** net sentiment score, top positive/negative themes, "topics
  investors are angry about" — each theme carries the source headlines as evidence. This snapshot
  is fed into the Predictive Analyst (angry topics → likely hard questions) and rendered as a
  **gauge + theme cards** in Flutter.

---

### 4.5 AMD ROCm + vLLM serving  ⭐ (the critical piece)

All inference runs on **AMD GPUs via vLLM's ROCm backend**, exposed as an OpenAI-compatible
server so LangGraph/LangChain talk to it with zero vendor lock-in.

**Bring-up (MI300X `gfx942` / Radeon `gfx1100`):**

```bash
# Official AMD ROCm vLLM image (prebuilt for ROCm)
docker run -it --rm \
  --device=/dev/kfd --device=/dev/dri \
  --group-add video --ipc=host --shm-size 16G \
  -p 8000:8000 \
  rocm/vllm:latest

# Serve an open-source model (OpenAI-compatible endpoint)
vllm serve mistralai/Mistral-7B-Instruct-v0.3 \
  --dtype float16 --max-model-len 8192 \
  --gpu-memory-utilization 0.90 --port 8000
```

Key ROCm/vLLM knobs we tune and report in the demo:
- `HIP_VISIBLE_DEVICES` to pin GPUs; `--tensor-parallel-size` for multi-GPU (MI300X).
- `VLLM_USE_TRITON_FLASH_ATTN=1` (ROCm FlashAttention) for throughput.
- `--max-num-seqs` + continuous batching → measured **tokens/sec** and **concurrent agents**.
- Quantization (AWQ/GPTQ) option for the 8B reasoning model to fit smaller Radeon cards.

**Models on the node** (all open-source, all from Hugging Face):

| Role | Model | Endpoint |
|---|---|---|
| Drafting | `mistralai/Mistral-7B-Instruct-v0.3` | `/v1/chat/completions` |
| Predictive Analyst | `deepseek-ai/DeepSeek-R1-Distill-Llama-8B` **+ our LoRA** | `/v1/chat/completions` (`--enable-lora`) |
| General reasoning / NLI verify | `meta-llama/Llama-3.1-8B-Instruct` | `/v1/chat/completions` |
| Embeddings | `BAAI/bge-base-en-v1.5` | `/v1/embeddings` |
| Sentiment | `ProsusAI/finbert` (transformers on ROCm) | internal |

LangGraph client config:

```python
from langchain_openai import ChatOpenAI
llm = ChatOpenAI(base_url="http://rocm-node:8000/v1", api_key="EMPTY",
                 model="mistralai/Mistral-7B-Instruct-v0.3", temperature=0.2)
```

**Demo headline:** show `rocm-smi` GPU utilization live while 4 agents run concurrently against
one vLLM server — proves the AMD stack carries the whole multi-agent workload.

---

### 4.6 Unsloth fine-tuning highlight  ⭐

**Use case:** the **Predictive Analyst Agent** — predict the hardest analyst questions.

**Why fine-tune:** A base model needs many few-shot examples of (transcript → analyst questions)
stuffed into the prompt to predict well. That is expensive in tokens and dilutes context. We
fine-tune so the skill is **in the weights**, giving higher question-recall **and** a much
smaller prompt.

**Recipe (Unsloth QLoRA):**
- **Base:** `DeepSeek-R1-Distill-Llama-8B` (or `Llama-3.1-8B-Instruct`).
- **Data:** (prepared-remarks + financial snapshot) → (actual analyst Q&A) pairs mined from
  earnings transcripts — HF `jlh-ibm/earnings_call`, `lamini/earnings-calls-qa`, Kaggle
  Motley-Fool transcripts. We split the analyst-question turns as the target.
- **Train:** Unsloth 4-bit QLoRA (`FastLanguageModel.from_pretrained(..., load_in_4bit=True)`),
  LoRA r=16, on the AMD GPU; export LoRA adapter; serve with vLLM `--enable-lora`.

```python
from unsloth import FastLanguageModel
model, tok = FastLanguageModel.from_pretrained(
    "deepseek-ai/DeepSeek-R1-Distill-Llama-8B", max_seq_length=8192, load_in_4bit=True)
model = FastLanguageModel.get_peft_model(model, r=16, lora_alpha=16,
            target_modules=["q_proj","k_proj","v_proj","o_proj",
                            "gate_proj","up_proj","down_proj"])
# ... SFTTrainer on (context → analyst_questions) pairs ...
model.save_pretrained("lora_qpredict")   # served by vLLM --enable-lora
```

**Measured highlight (the slide we show judges):**
- **Accuracy:** question-prediction **recall@10 up** vs base (we evaluate against held-out real
  Q&A — overlap / semantic-match score).
- **Token/context optimization:** few-shot examples dropped from ~6 to **0**, cutting prompt
  size by **~60–70%** per call → cheaper + lower latency on the ROCm node, with equal-or-better
  recall. This is the concrete "improves accuracy / optimizes token usage" win.

---

### 4.7 Flutter GenUI front-end (streaming + HITL)

Uses the **`genui` + `genui_a2a`** packages. Backend is an **A2A WebSocket server**; Flutter
connects with `A2uiAgentConnector` and renders **A2UI v0.9** messages live.

```dart
final _controller   = SurfaceController(catalogs: [
  BasicCatalogItems.asCatalog().copyWith([
    financialSnapshotCard, sentimentGauge, predictedQaList,
    draftSectionWithCitations, evidenceChip, approveEditBar,   // custom catalog items
  ]),
]);
final _transport    = A2uiTransportAdapter(onSend: _sendToAgent);
final _connector    = A2uiAgentConnector(url: Uri.parse('ws://rocm-node:8080'));
final _conversation = Conversation(controller: _controller, transport: _transport);

_msgSub  = _connector.stream.listen(_transport.addMessage);    // structured A2UI messages
_textSub = _connector.textStream.listen(_transport.addChunk);  // raw streamed text
```

**Screens (each a Surface):**
1. **Setup** — ticker + quarter; kicks off the graph.
2. **Financial Snapshot** — `updateComponents` builds metric cards; values arrive via
   `updateDataModel` to `/facts/<id>/value` so numbers stream in without full re-render.
3. **Market Sentiment** — gauge + theme cards with source headlines.
4. **Predicted Q&A** — ranked hard questions, each with a "why" + retrieved evidence chip.
5. **Draft Script (HITL)** — streamed paragraph-by-paragraph; **every sentence shows an evidence
   chip `[F-0012]`**; an `approveEditBar` (Approve / Edit / Regenerate) dispatches a
   `UserActionEvent` that resumes the LangGraph interrupt with the human's edit.
6. **Deck Outline** — bullet list per slide.
7. **Q&A Cheat Sheet** — question → suggested answer → backing numbers.

**Streaming mapping:** LangGraph node update → A2UI emitter →
`updateComponents` (new card) / `updateDataModel` (value fill) → Flutter rebuilds only the bound
widget. **HITL action:** button → `dispatchEvent(UserActionEvent('approve_section', payload))` →
WebSocket → `Command(resume=...)`.

> A2UI rules we respect (from the genui skill): one `id:"root"` per surface; `createSurface`
> before `updateComponents`; `catalogId =
> https://a2ui.org/specification/v0_9/basic_catalog.json`; every block has `"version":"v0.9"`;
> dispose order `conversation → transport → controller → connector`.

---

## 5. Grounding & evidence — "no missing, no hallucinated numbers"

This is the differentiator, enforced at three layers:

1. **Source of truth:** numbers live only in the **Financial Fact Store** (§4.1). The LLM
   receives fact IDs + values, and writes **slots** (`{{F-0012}}`), never free-form digits.
2. **Numeric grounding verifier (node 5):** after drafting, a deterministic pass extracts every
   numeric token from the generated text and asserts each one matches a Fact-Store value within
   tolerance. Any unmatched number → **blocked**, draft regenerated (conditional edge back to
   `draft`). This guarantees *no hallucinated* numbers.
3. **Claim grounding (NLI):** non-numeric claims (e.g., "demand accelerated in EMEA") are checked
   against retrieved IR-Wiki evidence with an NLI model (Llama-3.1-8B prompted as entailment
   judge). Unsupported claims are flagged for the human, not silently kept.
4. **Coverage check ("no missing"):** the verifier asserts every **required metric** for the
   period is present in the script/cheat-sheet (revenue, EPS, margins, guidance...). Missing
   metric → flagged in the HITL panel.

Every rendered sentence carries an **evidence chip** (metric, value, period, source URL),
tappable in Flutter — so the reviewer can audit each claim before approval.

---

## 6. Models, data sources & stack (all open-source)

**Models (Hugging Face):** Mistral-7B-Instruct-v0.3, DeepSeek-R1-Distill-Llama-8B (+ our LoRA),
Llama-3.1-8B-Instruct, BAAI/bge-base-en-v1.5, BGE reranker, ProsusAI/finbert.

**Data:** `defeatbeta-api` (primary, HF `yahoo-finance-data`), `yfinance` (fallback),
news-search tool. **Demo / fine-tune datasets:** HF `jlh-ibm/earnings_call`,
`lamini/earnings-calls-qa`, `financial_phrasebank`; Kaggle Motley-Fool Earnings Transcripts,
Kaggle stock-tweets (social sentiment).

**Stack:** Python 3.11, FastAPI, LangGraph, Qdrant (ChromaDB fallback), DuckDB, Pydantic,
Unsloth, vLLM-ROCm, sentence-transformers; Flutter + `genui`/`genui_a2a`.

---

## 7. Repo structure

```
amdhackathonfin/
├── PLAN.md                      # this file
├── backend/
│   ├── serving/                 # vLLM-ROCm launch scripts, model configs, rocm-smi probes
│   ├── data/                    # defeatbeta client, fact_store.py, yfinance fallback
│   ├── wiki/                    # ingestion → chunk → embed → Qdrant; retriever + reranker
│   ├── agents/                  # extraction, sentiment, predictive, drafting, verifier nodes
│   ├── graph/                   # LangGraph StateGraph, state, interrupts, checkpointer
│   ├── a2ui/                    # A2A WebSocket server + agent-event → A2UI emitter
│   ├── verify/                  # numeric grounding + NLI claim checker + coverage
│   └── api/                     # FastAPI app
├── finetune/                    # Unsloth QLoRA: data prep, train, eval, adapter export
├── flutter_app/                 # genui app: catalog items, surfaces/screens, connector
└── eval/                        # no-hallucination tests, recall@k, token-savings bench
```

---

## 8. Hackathon execution plan (phased)

| Phase | Deliverable | Proof |
|---|---|---|
| **P0 Infra** | vLLM-ROCm serving Mistral + BGE; `rocm-smi` shows GPU busy | OpenAI call returns; embeddings work |
| **P1 Data** | defeatbeta-api → Financial Fact Store with provenance | facts for demo ticker, all metrics present |
| **P2 Wiki** | Qdrant ingest of transcripts/filings/news + reranked retrieval | cited chunks returned |
| **P3 Agents** | LangGraph nodes 1–5 wired, streaming `astream` | end-to-end draft generated |
| **P4 Grounding** | numeric verifier + coverage + claim NLI | injected wrong number is caught & blocked |
| **P5 Sentiment** | news-search + FinBERT snapshot | gauge + themes |
| **P6 Fine-tune** | Unsloth QLoRA adapter; before/after recall + token bench | slide with metrics |
| **P7 Flutter** | genui screens + A2A streaming + HITL approve/edit | live demo, reviewer edits a paragraph |
| **P8 Polish** | demo script, eval numbers, fallback paths | dry run |

---

## 9. Demo script (4 minutes)

1. Type ticker **NVDA**, quarter — graph starts; **Financial Snapshot** streams in (numbers
   filling via `updateDataModel`). 2. **Market Sentiment** gauge appears with angry-topic themes.
3. **Predicted Q&A** ranks the hardest questions (powered by the **Unsloth-fine-tuned** model —
   show the before/after recall + token slide). 4. **Draft Script** streams sentence-by-sentence,
   each with an **evidence chip**. 5. We **inject a wrong number** into a regenerate prompt → the
   **Grounding Verifier blocks it** (no-hallucination proof). 6. Reviewer **edits one line and
   approves** in Flutter → graph resumes → **final script, deck outline, Q&A cheat sheet**.
7. Cut to `rocm-smi` — all of it ran on **AMD ROCm + vLLM** with open-source models.

---

## 10. Evaluation (how we prove the claims)

- **No hallucinated numbers:** adversarial test set with injected wrong figures → verifier
  catch-rate target **100%** on numerics; report precision/recall on flagged claims.
- **No missing numbers:** coverage check over a required-metric checklist per period.
- **Fine-tune win:** question-prediction **recall@10** (base vs LoRA) on held-out real analyst
  Q&A + **prompt-token reduction %** at equal recall.
- **ROCm performance:** vLLM tokens/sec, concurrent-agent latency, GPU utilization on the AMD
  node.
- **RAG quality:** retrieval hit-rate / citation correctness on a labeled query set.

---

## 11. Risks & mitigations

| Risk | Mitigation |
|---|---|
| ROCm model/image friction | Use official `rocm/vllm` image; AWQ-quantized 8B fallback for smaller cards; pin `gfx` arch. |
| defeatbeta-api gaps/rate limits | `yfinance` fallback + local DuckDB cache; pre-fetch demo ticker. |
| LLM invents a number | Slotting + deterministic numeric verifier blocks it (§5). |
| Fine-tune doesn't beat base | Keep base as default; LoRA is additive — ship whichever wins on eval. |
| Flutter A2UI rendering bugs | `DebugCatalogView` + `exampleData` to test cards without the LLM. |
| Demo network flakiness | Cache fact store, embeddings, and a recorded transcript locally. |

---

## 12. Stretch goals

- Export the approved deck to **PPTX** (pptx skill) and script to **DOCX**.
- Multi-company **competitor comparison** screen.
- "What changed since last quarter" diff agent.
- Voice delivery: TTS read-through of the approved script.

---

*All inference is open-source models on AMD ROCm via vLLM; all financial numbers are
source-grounded with provenance; a human approves before anything is final.*
