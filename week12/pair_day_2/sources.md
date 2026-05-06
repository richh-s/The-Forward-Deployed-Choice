# Sources — Day 2 Explainer (Function-Calling at the Token Level)

*Sources used by Rahel Samson to write the function-calling explainer for Lidya Dagnaw.*

---

## Canonical Papers

**1. Schick et al. (2023) — Toolformer: Language Models Can Teach Themselves to Use Tools**
- URL: https://arxiv.org/abs/2302.04761
- Load-bearing use: The foundational paper showing how API-call tokens are injected into the training corpus so models learn to call tools at the right positions. Section 3 describes exactly how the special `[` and `]` call tokens are inserted and what the model learns to do with them. Production function-calling in GPT-4 and Claude is a productionized version of this mechanism. Used to explain why the model "knows" to produce tool-call syntax — it was trained on data containing these tokens.

**2. OpenAI Function Calling Reference Documentation**
- URL: https://platform.openai.com/docs/guides/function-calling
- Load-bearing use: Authoritative source for the `tools` parameter schema, `tool_choice` options, `tool_calls` response format, `finish_reason: "tool_calls"` signal, and the parallel tool call pattern. No paper covers the production API behavior — this documentation is the primary source for the observable mechanism described in the hands-on section.

---

## Tool Used

**OpenAI Python SDK — `response.choices[0].finish_reason` and `response.choices[0].message.tool_calls`**

The side-by-side code in the explainer is runnable with any OpenRouter-compatible model that supports function-calling (e.g., `openai/gpt-4o-mini`). The key verification step:

```python
response = client.chat.completions.create(
    model="openai/gpt-4o-mini",
    messages=messages,
    tools=tools,
    tool_choice="auto"
)

print(response.choices[0].finish_reason)
# "tool_calls" if function-calling fired
# "stop" if model responded in text

if response.choices[0].message.tool_calls:
    call = response.choices[0].message.tool_calls[0]
    print(call.function.name)        # guaranteed to match a declared function
    print(call.function.arguments)   # guaranteed schema-valid JSON
```

Running this against the same query with and without the `tools` parameter produces visibly different `finish_reason` values, confirming the mechanism described in the explainer.
