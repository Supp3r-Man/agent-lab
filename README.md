# Agent Lab

Ten agent apps adapted from the open-source
[awesome-llm-apps](https://github.com/Shubhamsaboo/awesome-llm-apps) collection
and collected in one place with a shared setup. The original code is by Shubham
Saboo and contributors; see [Attribution](#attribution). Each one is a Streamlit
app or a CLI. You bring your own API keys (OpenAI, Anthropic, Google or Firecrawl, depending on the app). Nothing is stored.

| Agent | What it does | Stack | Run |
|---|---|---|---|
| [DevPulse Signal Intelligence](agents/devpulse-signal-intelligence) | Pulls signals from GitHub, ArXiv, HackerNews, Medium and HuggingFace. Scores relevance and risk, then writes a digest. | Agno | `python main.py` |
| [Codebase Migration Planner](agents/codebase-migration-planner) | Plans a file-by-file migration, pauses for human approval, refactors files in parallel, then writes a report with charts. | LangGraph | `streamlit run app.py` |
| [HackerNews Research Team](agents/hackernews-research-team) | A team of agents that researches HackerNews stories and users and drafts posts or reports. | Agno | `streamlit run research_agent.py` |
| [Agent Chess Arena](agents/agent-chess-arena) | Two LLM agents play chess, with a referee agent that rejects illegal moves. | AutoGen | `streamlit run ai_chess_agent.py` |
| [Deep Research Agent](agents/deep-research-agent) | Researches a topic by searching and scraping the web with Firecrawl, then writes a report. | OpenAI Agents SDK | `streamlit run deep_research_openai.py` |
| [Fraud Investigation Agent](agents/fraud-investigation-agent) | Investigates a suspicious case with address checks and web evidence, and produces a structured report. | Agno | `streamlit run fraud_investigation_agent.py` |
| [Negotiation Battle Simulator](agents/negotiation-battle-simulator) | Buyer and seller agents with different personalities negotiate in a live web UI. Needs a Google key. | Google ADK, Next.js | see its README |
| [Multi-Agent Trust Layer](agents/multi-agent-trust-layer) | Identity, trust scores, scoped delegation and an audit trail for agent-to-agent calls. Runs without a key. | Python | `python multi_agent_trust_layer.py` |
| [Career Coach with Memory](agents/career-coach-memory) | An orchestrator routes questions to resume, interview, skills and salary specialists. Mem0 and Qdrant remember each candidate across sessions. Needs one Google key. Its tool data is mock data. | Google ADK, Mem0 | `streamlit run adk_career_coach_agent_memory.py` |
| [Meeting Prep Crew](agents/meeting-prep-crew) | A crew of agents that researches the people and context for a meeting. Needs Anthropic and Serper keys. | CrewAI | `streamlit run meeting_agent.py` |

## Quick start

```bash
git clone https://github.com/Supp3r-Man/agent-lab.git
cd agent-lab/agents/<agent-folder>
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
export OPENAI_API_KEY=sk-...                         # Windows: $env:OPENAI_API_KEY="sk-..."
```

DevPulse has a heuristic fallback, so `python verify.py` runs without a key, and the Trust Layer demo needs none.
The Meeting Prep Crew is hardcoded to an older Claude model id (`claude-3-5-sonnet-20240620`) that may no longer be available. Change it in `meeting_agent.py` if the app errors.

## Attribution

These apps are adapted from
[awesome-llm-apps](https://github.com/Shubhamsaboo/awesome-llm-apps) by
Shubham Saboo and contributors, under the Apache License 2.0. See
[NOTICE](NOTICE) and [LICENSE](LICENSE).
