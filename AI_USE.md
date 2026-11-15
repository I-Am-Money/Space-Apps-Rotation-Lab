# AI use disclosure

The original project was built with Claude Code assistance, as recorded in the project handoff. OpenAI Codex assisted with subsequent debugging, input propagation, caching, the irrigation-saving objective, tests, and documentation.

An optional Anthropic API call writes an English explanation using computed model output. Without a key, or on API failure, the app uses a deterministic template. The app labels the explanation source. Weather and district yield observations are cached source data; AI-generated yields are not used for validation.

Per-acre cost proxies, irrigation supply parameters and crop-response parameters remain labeled modeling assumptions. Potential yields are derived from the archived district series; unknown measurement quotes remain absent. AI assistance does not establish agronomic validity. No NASA endorsement is claimed.
