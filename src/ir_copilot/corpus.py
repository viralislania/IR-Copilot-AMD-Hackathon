"""Small demo corpus so notebooks run offline: transcript chunks, news, social posts.

In production these come from defeatbeta-api / custom PDF/audio ingestion (docs/wiki-ingestion.md).
Here they are compact, realistic stand-ins for a reproducible demo.
"""
from __future__ import annotations

# Earnings-call transcript chunks (target + peers). role: exec (prepared) / analyst (Q&A).
TRANSCRIPT_CHUNKS = [
    {"ticker": "NVDA", "doc_type": "transcript", "period": "FY2025Q4", "role": "analyst",
     "source_url": "https://example.com/nvda/fy25q4#qa1",
     "text": "Analyst: Your data center gross margin expanded sharply. How sustainable is this "
             "gross margin level given rising competition in AI accelerators?"},
    {"ticker": "NVDA", "doc_type": "transcript", "period": "FY2025Q4", "role": "analyst",
     "source_url": "https://example.com/nvda/fy25q4#qa2",
     "text": "Analyst: Can you discuss supply constraints and lead times for your latest GPU "
             "platform, and when supply will meet the very strong demand?"},
    {"ticker": "NVDA", "doc_type": "transcript", "period": "FY2025Q3", "role": "analyst",
     "source_url": "https://example.com/nvda/fy25q3#qa1",
     "text": "Analyst: How should we think about customer concentration risk as a few large "
             "cloud customers drive a large share of data center revenue?"},
    {"ticker": "NVDA", "doc_type": "transcript", "period": "FY2025Q4", "role": "exec",
     "source_url": "https://example.com/nvda/fy25q4#prep1",
     "text": "CFO: Revenue grew across data center as customers ramped AI training and inference. "
             "We expect continued sequential growth and remain supply constrained."},
    {"ticker": "AMD", "doc_type": "transcript", "period": "FY2025Q4", "role": "analyst",
     "source_url": "https://example.com/amd/fy25q4#qa1",
     "text": "Analyst: Your gross margin trails the leader by a wide gap. What is the roadmap to "
             "close the gross margin gap with competing AI accelerators?"},
    {"ticker": "AMD", "doc_type": "transcript", "period": "FY2025Q4", "role": "analyst",
     "source_url": "https://example.com/amd/fy25q4#qa2",
     "text": "Analyst: How is your AI GPU ramp progressing against the dominant incumbent, and "
             "what software ecosystem gaps remain?"},
    {"ticker": "INTC", "doc_type": "transcript", "period": "FY2025Q4", "role": "analyst",
     "source_url": "https://example.com/intc/fy25q4#qa1",
     "text": "Analyst: With negative operating margin this quarter, what is the path back to "
             "profitability and positive return on invested capital?"},
]

# Recent news headlines per ticker.
NEWS_HEADLINES = [
    {"ticker": "NVDA", "date": "2026-05-30", "url": "https://example.com/news/1",
     "text": "NVIDIA data center demand stays red-hot but investors fret about AI capex digestion."},
    {"ticker": "NVDA", "date": "2026-05-28", "url": "https://example.com/news/2",
     "text": "Analysts raise NVIDIA targets on strong gross margin and record revenue guidance."},
    {"ticker": "NVDA", "date": "2026-05-25", "url": "https://example.com/news/3",
     "text": "Rising competition and customer in-house chips spark concern over NVIDIA market share."},
    {"ticker": "NVDA", "date": "2026-05-22", "url": "https://example.com/news/4",
     "text": "Supply constraints ease for NVIDIA's latest GPU platform, boosting optimism."},
    {"ticker": "NVDA", "date": "2026-05-20", "url": "https://example.com/news/5",
     "text": "Regulatory scrutiny over export rules weighs on NVIDIA shares."},
]

# Social posts (stand-in for a stock-tweets dataset).
SOCIAL_POSTS = [
    {"ticker": "NVDA", "url": "https://example.com/post/1",
     "text": "Margins look amazing, demand is insane. Long $NVDA."},
    {"ticker": "NVDA", "url": "https://example.com/post/2",
     "text": "Worried about competition and customers building their own chips. $NVDA overvalued?"},
    {"ticker": "NVDA", "url": "https://example.com/post/3",
     "text": "Export restrictions are a real risk for $NVDA guidance."},
    {"ticker": "NVDA", "url": "https://example.com/post/4",
     "text": "Record revenue again, guidance strong. Bullish $NVDA."},
]
