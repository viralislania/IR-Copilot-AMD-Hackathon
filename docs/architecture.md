# Architecture

IR-Copilot is a layered system. The only GPU dependency is the model-serving node
(**AMD MI300X + vLLM**); everything above it speaks plain OpenAI-compatible HTTP, so the
stack is provider-neutral and portable.

```mermaid
flowchart TB
    subgraph UI["UI layer (primary: CopilotKit · optional: Flutter GenUI)"]
        R[React / Next.js + CopilotKit\nuseCoAgent · useCoAgentStateRender · useLangGraphInterrupt]
        FL[Flutter genui_a2a\n(optional alternative)]
    end

    subgraph BE["Backend (Python / FastAPI)"]
        CK[copilotkit SDK\nadd_fastapi_endpoint · LangGraphAgent\n(AG-UI protocol)]
        LG[LangGraph StateGraph\nnodes 1–6 · interrupt_before=hitl · checkpointer]
        TOOLS[Tools: defeatbeta-api · yfinance · news-search\nQdrant retriever · grounding verifier]
        FS[(Financial Fact Store\nPydantic + DuckDB)]
        WIKI[(Qdrant\nmultimodal IR wiki)]
    end

    subgraph GPU["AMD MI300X node — vLLM (ROCm)"]
        M1[Llama-3.1-70B-Instruct\nDrafting]
        M2[DeepSeek-R1-Distill\nPredictive Analyst + LoRA]
        M3[Llama-3.1-8B\nverifier / NLI]
        M4[BGE embeddings]
        M5[FinBERT · Whisper]
    end

    R <-->|AG-UI events / state| CK
    FL -.optional.-> CK
    CK <--> LG
    LG <--> TOOLS
    TOOLS <--> FS
    TOOLS <--> WIKI
    LG <-->|OpenAI HTTP| GPU
```

## Layers

| Layer | Responsibility | Key tech |
|---|---|---|
| **UI** | Render streamed agent state; collect human approve/edit | CopilotKit (AG-UI), optional Flutter `genui` |
| **API / agent runtime** | Expose the graph, stream state, surface interrupts | FastAPI, `copilotkit` SDK |
| **Orchestration** | Sequence the six agents, retry loop, HITL gate, learning loop | LangGraph |
| **Tools & memory** | Fetch data, retrieve evidence, verify numbers | defeatbeta-api, Qdrant, DuckDB |
| **Models** | All inference (chat, reasoning, embeddings, sentiment, ASR) | vLLM on MI300X |

## Design principles

1. **One GPU dependency.** Only the vLLM node touches ROCm; swap GPUs or scale without
   changing app code. See [AMD MI300X + vLLM](rocm-vllm.md).
2. **Numbers are data, not generations.** The LLM slots verified facts; it never invents
   digits. See [Grounding & Evidence](grounding.md).
3. **Everything is cited.** Each rendered claim carries provenance.
4. **Human owns the final word.** The graph cannot finalize without approval.
5. **Provider-neutral UI.** CopilotKit is primary because it pairs natively with Python
   LangGraph; Flutter GenUI remains a drop-in alternative front-end. See [UI](ui.md).

## End-to-end request flow

1. User enters **ticker + quarter** in the UI → `useCoAgent` starts the LangGraph run.
2. **Data Extraction** builds the [Financial Fact Store](grounding.md) from
   [defeatbeta-api](data-sources.md).
3. **Sentiment & News** and **Competitor Comparison** enrich state.
4. **Predictive Analyst** (fine-tuned) predicts hard questions via [RAG](wiki-ingestion.md).
5. **Drafting** produces script + deck + cheat sheet with slotted numbers.
6. **Grounding Verifier** blocks any unsupported number/claim (loops back to draft).
7. Graph **pauses** at the HITL interrupt; reviewer approves/edits in the UI.
8. **Finalize** emits artifacts and writes approved Q&A back to the wiki (learning loop).

Each node's partial output is streamed to the UI as it is produced — see
[UI](ui.md) and [Orchestration](orchestration.md).
