---
id: '005'
title: Agent layer
repo: textread
model: sonnet
budget_usd: 2.00
phase: textread
depends_on: ['002']
---

# 005 — Agent layer

## Requirements

- R01: WHEN `agent.evaluate(raw, context, model)` is called, THE SYSTEM SHALL make
  exactly one `messages.create` call to the Anthropic API using the specified model.
- R02: WHEN the API response is received, THE SYSTEM SHALL parse it into a `Mapping`
  dataclass and return it.
- R03: WHEN `model` is `"haiku"`, THE SYSTEM SHALL use model ID
  `claude-haiku-4-5-20251001`. WHEN `model` is `"sonnet"`, THE SYSTEM SHALL use
  `claude-sonnet-4-5`. WHEN `model` is `"opus"`, THE SYSTEM SHALL use `claude-opus-4-5`.
- R04: WHEN the raw content exceeds 80 000 characters, THE SYSTEM SHALL truncate it
  to 80 000 characters before inserting it into the prompt.
- R05: WHEN the API returns a response that cannot be parsed as valid JSON matching
  the output schema, THE SYSTEM SHALL raise `AgentError` with the raw response text.
- R06: WHEN `context.role` and `context.stack` and `context.projects` are all empty,
  THE SYSTEM SHALL still call the API with a generic prompt (no crash on empty context).
- R07: WHEN the `Mapping` is returned, its `verdict` field SHALL be one of
  `worth_reading`, `skim`, or `skip`. Any other value SHALL raise `AgentError`.

## Design

### overview

`agent.py` makes a fresh Anthropic SDK call per invocation — no session, no caching,
no multi-turn. It builds a structured system prompt from the user context and embeds
the raw content in the user message. The API is instructed to return JSON matching
the output schema. The response is extracted from `content[0].text`, parsed with
`json.loads`, validated, and returned as a `Mapping` dataclass.

The client is instantiated inside `evaluate()` on each call — simple, predictable,
no global state. The `ANTHROPIC_API_KEY` env var is required; the SDK raises
`anthropic.AuthenticationError` if absent (let it propagate — the user must set it).

### modules

- `src/textread/agent.py` — New file. `Mapping` dataclass + `evaluate()` + model alias
  resolution.
- `tests/test_agent.py` — New file. All tests mock `anthropic.Anthropic` client.

### data_structures

```python
@dataclass
class Mapping:
    verdict: str          # "worth_reading" | "skim" | "skip"
    score: int            # 0-100
    reason: str           # one-line explanation for this user
    summary: str          # <=200 words, context-lensed
    key_points: list[str]
    connects_to: list[str]   # project names from context
    tags: list[str]

class AgentError(Exception):
    """Raised on parse failure or invalid verdict."""
```

Model alias map:
```python
MODEL_ALIASES = {
    "haiku":  "claude-haiku-4-5-20251001",
    "sonnet": "claude-sonnet-4-5",
    "opus":   "claude-opus-4-5",
}
```

### sequence

evaluate_flow:
  1. Resolve model ID from alias map. If alias not found, use the string as-is (allows
     raw model IDs).
  2. Truncate raw content to 80 000 chars if needed (R04).
  3. Build system prompt:
     ```
     You are a relevance filter for a developer.
     User context:
       Role: {context.role}
       Stack: {", ".join(context.stack)}
       Projects: {serialised list of project name + summary + current}
       Downweight: {", ".join(context.filters.get("downweight", []))}
     Return ONLY valid JSON matching this schema — no markdown, no prose:
     {json.dumps(SCHEMA, indent=2)}
     ```
  4. User message: `URL: {url}\n\nContent:\n{truncated_raw}`.
  5. Call `client.messages.create(model=model_id, max_tokens=1024, system=system_prompt,
     messages=[{"role": "user", "content": user_msg}])`.
  6. Extract `response.content[0].text`. Parse with `json.loads`.
  7. Validate `verdict` in allowed set (R07). Build and return `Mapping(**parsed)`.
  8. On `json.JSONDecodeError` or KeyError → raise `AgentError(raw_text)`.

### prompt_schema

The literal JSON schema string embedded in the system prompt:
```json
{
  "verdict": "worth_reading | skim | skip",
  "score": "integer 0-100",
  "reason": "one-line explanation for this specific user",
  "summary": "<=200 word summary lensed through user context",
  "key_points": ["string", "..."],
  "connects_to": ["project name from user context", "..."],
  "tags": ["string", "..."]
}
```

### degradation

`AgentError` is the only error surface this module exposes. Callers should catch it
and print `[ERROR] Agent failed: {e}` then exit with code 1.

## Steps

1. Create `src/textread/agent.py`:
   - `MODEL_ALIASES`, `AgentError`, `Mapping` per `data_structures`.
   - `_build_system_prompt(context: ReadContext) -> str` — constructs the system prompt
     string per `sequence.evaluate_flow` step 3.
   - `evaluate(url: str, raw: str, context: ReadContext, model: str = "haiku") -> Mapping`
     per `sequence.evaluate_flow`.

2. Create `tests/test_agent.py`:
   - Use `unittest.mock.patch("textread.agent.anthropic.Anthropic")` to mock the client.
   - Helper `mock_response(text: str)` — returns a mock that makes `client.messages.create`
     return an object where `content[0].text == text`.
   - `test_r01_single_api_call` — assert `create` is called exactly once.
   - `test_r02_returns_mapping` — mock returns valid JSON; assert result is `Mapping`.
   - `test_r03_model_alias_haiku` — assert the model ID passed to create matches haiku ID.
   - `test_r03_model_alias_sonnet` — same for sonnet.
   - `test_r04_truncates_long_content` — pass 100 000 char string; assert the `create`
     call's user message contains at most 80 000 chars of content.
   - `test_r05_bad_json_raises_agent_error` — mock returns `"not json"`; assert `AgentError`.
   - `test_r06_empty_context_no_crash` — call with `ReadContext()`; assert no exception
     (API is mocked to return valid JSON).
   - `test_r07_invalid_verdict_raises` — mock returns JSON with `verdict: "banana"`;
     assert `AgentError`.

3. Run `uv run pytest tests/test_agent.py -v` — all green.

## Commit message
feat: add agent layer with Anthropic SDK and structured output (v0.5.0)
