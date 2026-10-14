# Agent Lab

Four multi-agent apps adapted from the open-source
[awesome-llm-apps](https://github.com/Shubhamsaboo/awesome-llm-apps) collection
and collected in one place with a shared setup. The original code is by Shubham
Saboo and contributors; see [Attribution](#attribution). Each one is a Streamlit
app or a CLI. You bring your own OpenAI key. Nothing is stored.

| Agent | What it does | Stack | Run |
|---|---|---|---|
| [DevPulse Signal Intelligence](agents/devpulse-signal-intelligence) | Pulls signals from GitHub, ArXiv, HackerNews, Medium and HuggingFace. Scores relevance and risk, then writes a digest. | Agno | `python main.py` |
| [Codebase Migration Planner](agents/codebase-migration-planner) | Plans a file-by-file migration, pauses for human approval, refactors files in parallel, then writes a report with charts. | LangGraph | `streamlit run app.py` |
| [HackerNews Research Team](agents/hackernews-research-team) | A team of agents that researches HackerNews stories and users and drafts posts or reports. | Agno | `streamlit run research_agent.py` |
| [Agent Chess Arena](agents/agent-chess-arena) | Two LLM agents play chess, with a referee agent that rejects illegal moves. | AutoGen | `streamlit run ai_chess_agent.py` |

## Quick start

```bash
git clone https://github.com/Supp3r-Man/agent-lab.git
cd agent-lab/agents/<agent-folder>
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
export OPENAI_API_KEY=sk-...                         # Windows: $env:OPENAI_API_KEY="sk-..."
```

DevPulse has a heuristic fallback, so `python verify.py` runs without a key.

## Attribution

These apps are adapted from
[awesome-llm-apps](https://github.com/Shubhamsaboo/awesome-llm-apps) by
Shubham Saboo and contributors, under the Apache License 2.0. See
[NOTICE](NOTICE) and [LICENSE](LICENSE).
