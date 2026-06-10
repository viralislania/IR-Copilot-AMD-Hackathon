"""IR-Copilot — grounded multi-agent Investor-Relations workflow.

Submodules:
  config        — settings from .env
  facts         — Financial Fact Store + grounding helpers
  embeddings    — hash | sentence-transformers | vllm
  vectorstore   — Qdrant wiki (memory | docker | local)
  llm           — mock | vllm chat clients
  corpus        — demo transcripts/news/social
  agents.*      — sentiment, competitor, predictive, drafting, verify
"""
__all__ = ["config", "facts", "embeddings", "vectorstore", "llm", "corpus", "agents"]
