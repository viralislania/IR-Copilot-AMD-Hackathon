# AMD MI300X + vLLM

!!! danger "Critical platform requirement"
    **All inference runs on AMD GPUs via vLLM's ROCm backend**, exposed as an
    OpenAI-compatible server. LangGraph/LangChain talk to it over plain HTTP, so there is zero
    vendor lock-in above the model node.

## Why MI300X changes the design

The **MI300X has 192 GB of HBM3e per GPU** (8 per node typical). That means:

- **No quantization required** — run 70B-class models in `float16`/`bf16` for top draft
  quality.
- **Multiple models co-resident** — drafting (70B), reasoning (8B + LoRA), embeddings, ASR,
  and sentiment can be served concurrently.
- **Long context** comfortably (full transcripts + filings + peer context in one prompt).

## Bring-up

Use AMD's prebuilt ROCm vLLM image (`gfx942` is the MI300X arch).

```bash
docker run -it --rm \
  --device=/dev/kfd --device=/dev/dri \
  --group-add video --ipc=host --shm-size 32G \
  -p 8000:8000 \
  rocm/vllm:latest

# Drafting model — full precision on MI300X (no quantization)
vllm serve meta-llama/Llama-3.1-70B-Instruct \
  --dtype bfloat16 --max-model-len 32768 \
  --tensor-parallel-size 1 \
  --gpu-memory-utilization 0.90 --port 8000
```

```bash
# Reasoning model with hot-swappable LoRA (Predictive Analyst)
vllm serve deepseek-ai/DeepSeek-R1-Distill-Llama-8B \
  --enable-lora --lora-modules qpredict=/models/lora_qpredict \
  --dtype bfloat16 --max-model-len 16384 --port 8001
```

```bash
# Embeddings endpoint for the wiki
vllm serve BAAI/bge-base-en-v1.5 --task embed --port 8002
```

## ROCm / vLLM tuning we report live

| Knob | Purpose |
|---|---|
| `HIP_VISIBLE_DEVICES` | pin GPUs |
| `--tensor-parallel-size` | shard large models across MI300X GPUs |
| `VLLM_USE_TRITON_FLASH_ATTN=1` | ROCm FlashAttention → throughput |
| `--max-num-seqs` | continuous-batching concurrency |
| `--enable-lora` / `--lora-modules` | serve the [fine-tuned](finetuning.md) adapter |
| `rocm-smi` | live GPU utilization in the demo |

## Models on the node (all open-source, all Hugging Face)

| Role | Model | Port |
|---|---|---|
| Drafting | `meta-llama/Llama-3.1-70B-Instruct` | 8000 |
| Predictive Analyst | `deepseek-ai/DeepSeek-R1-Distill-Llama-8B` **+ LoRA** | 8001 |
| Verifier / NLI | `meta-llama/Llama-3.1-8B-Instruct` | 8003 |
| Embeddings | `BAAI/bge-base-en-v1.5` | 8002 |
| Sentiment | `ProsusAI/finbert` (transformers on ROCm) | internal |
| ASR (audio/video wiki) | `openai/whisper-large-v3` | internal |

!!! note "Model choice is configurable"
    Mistral-7B-Instruct is a drop-in lighter drafting alternative. The MI300X headroom is why
    we default to the 70B for draft quality, but every model is selected by config/env.

## Client wiring (provider-neutral)

```python
from langchain_openai import ChatOpenAI

drafting_llm = ChatOpenAI(
    base_url="http://mi300x-node:8000/v1", api_key="EMPTY",
    model="meta-llama/Llama-3.1-70B-Instruct", temperature=0.2,
)
analyst_llm = ChatOpenAI(
    base_url="http://mi300x-node:8001/v1", api_key="EMPTY",
    model="qpredict",   # the LoRA adapter name
)
```

## Demo headline

Run all six [agents](agents.md) concurrently against the MI300X node and show **`rocm-smi`**
GPU utilization climbing in real time — proving the AMD stack carries the entire multi-agent
workload, with the fine-tuned adapter hot-swapped via `--enable-lora`.
