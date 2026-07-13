# Financial Report & News RAG Assistant

A stock-focused Q&A assistant over financial reports (SEC EDGAR / TWSE MOPS) and news (Yahoo Finance RSS). All inference runs locally via Ollama — your data never leaves this machine.

**What you can ask:**

- "What was AAPL's revenue in the latest quarter?"
- "What is TSMC (2330)'s gross margin in the latest quarter?"
- "Any negative news about 2330 recently?"

Each answer cites its sources and ends with an investment manager's trend view (with a disclaimer — not investment advice). Every response comes with a downloadable `.md` analysis file. Companies not yet in the database are fetched automatically (listed companies only — the first question may take a few minutes).
