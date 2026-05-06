# What the Model Is Actually Doing When It "Chooses" a Tool

*Written by Rahel Samson for Lidya Dagnaw, whose `composer.py` calls `chat.completions.create()` with a plain text prompt and no `tools` parameter.*

---

## The Question

You call `chat.completions.create()` without a `tools` parameter — you stuff the function description into your system prompt and parse the model's text output yourself. When someone uses function-calling properly (with the `tools` parameter), what is the model actually doing differently at the token level? And what does the `tools` parameter mechanically change about generation?

This is not a style question. The mechanism is genuinely different. Here is what is happening.

---

## The Load-Bearing Mechanism

When you pass `tools=[...]` to the API, three things happen that do not happen with prompt-stuffing:

**1. The tool schema is serialized into the context with special tokens.**

The SDK converts your Python dict into a structured text block that gets prepended to the conversation. In practice it looks something like this inside the model's context:

```
# Tools

## functions

namespace functions {

// Book a calendar slot for a prospect
type book_calendar_slot = (_: {
  prospect_email: string,
  time_slot: string,
}) => any;

} // namespace functions
```

The model never sees a Python dict. It sees tokens. The format above is not documentation — it is the exact token sequence the model was fine-tuned to recognize as a tool definition.

**2. The model was trained to produce a special output sequence when it decides to call a tool.**

During post-training (RLHF/SFT), the model saw thousands of examples of the pattern: *context with tool definitions + user query that warrants tool use → output in tool-call format*. It learned that when this pattern is present, the high-probability next token sequence is not a natural-language sentence but a structured tool call:

```json
{"name": "book_calendar_slot", "arguments": "{\"prospect_email\": \"cto@novapay.io\", \"time_slot\": \"2026-05-07T14:00:00Z\"}"}
```

The model is not making a deliberate choice. It is predicting the next token. When the context contains a tool definition and a query that resembles the training examples, the tool-call token sequence has higher probability than a text response.

**3. The backend enforces constrained decoding against the function's JSON schema.**

Once the model starts generating a tool call, the decoding algorithm validates each token against the schema you declared. If the model tries to output a field that does not exist in the schema, the backend rejects that token and samples the next highest-probability valid token. This is why function-calling produces valid JSON every time — it is not the model being careful; it is the generation being constrained.

You can observe this mechanically: when function-calling fires, `response.choices[0].finish_reason` is `"tool_calls"`, not `"stop"`. Generation stopped not at a natural endpoint but at the point where the tool call JSON was complete.

---

## Showing the Difference

```python
# --- Prompt-stuffing (what you have) ---
messages = [
    {"role": "system", "content": """
        Available functions:
        - book_calendar_slot(prospect_email: str, time_slot: str)
        - write_to_hubspot(contact_id: str, email_sent: bool)

        If you need to call a function, output JSON:
        {"action": "function_name", "args": {...}}
        Otherwise output the email text.
    """},
    {"role": "user", "content": "Compose outreach for cto@novapay.io"}
]

response = client.chat.completions.create(model="gpt-4o-mini", messages=messages)
text = response.choices[0].message.content   # you parse this string yourself
# finish_reason is always "stop" — model just ended its sentence
# No guarantee of valid JSON. No guarantee it calls the function at all.


# --- Function-calling (tools parameter) ---
tools = [{
    "type": "function",
    "function": {
        "name": "book_calendar_slot",
        "description": "Book a discovery call slot for a qualified prospect",
        "parameters": {
            "type": "object",
            "properties": {
                "prospect_email": {"type": "string"},
                "time_slot": {"type": "string", "description": "ISO 8601 datetime"},
            },
            "required": ["prospect_email", "time_slot"]
        }
    }
}]

response = client.chat.completions.create(
    model="gpt-4o-mini",
    messages=messages,
    tools=tools,
    tool_choice="auto"   # model decides whether to call or respond in text
)

msg = response.choices[0].message
if msg.tool_calls:
    call = msg.tool_calls[0]
    print(call.function.name)       # "book_calendar_slot" — guaranteed string match
    print(call.function.arguments)  # '{"prospect_email": "...", "time_slot": "..."}' — schema-valid
    # finish_reason is "tool_calls", not "stop"
else:
    print(msg.content)              # model chose to respond in text instead
```

**Observable output — prompt-stuffing:**
```
finish_reason: "stop"
content: '{"action": "book_calender_slot", "args": {"email": "cto@novapay.io"}}'
#                      ^^ typo — model hallucinated field name, Python KeyError on parse
```

**Observable output — function-calling:**
```
finish_reason: "tool_calls"    ← generation stopped here, not at a sentence boundary
tool_calls[0].function.name: "book_calendar_slot"    ← exact match, guaranteed
tool_calls[0].function.arguments: '{"prospect_email": "cto@novapay.io", "time_slot": "2026-05-07T14:00:00Z"}'
#                                                                          ← schema-valid, guaranteed
```

`finish_reason` is the fastest way to verify the mechanism is firing in your own code. If it returns `"stop"`, the model responded in text. If it returns `"tool_calls"`, the constrained decoding path fired.

The critical observable difference: with function-calling, `call.function.name` is guaranteed to match a function you declared. With prompt-stuffing, the model might output `"action": "book_calender_slot"` (typo), `"action": "schedule_meeting"` (hallucinated name), or no JSON at all.

---

## Why This Changes How You Attribute Failures

With prompt-stuffing, there is no such thing as the model "choosing to call a tool." The model outputs text. Your Python code reads that text and decides what to do. The model has no awareness of what `book_calendar_slot` does or whether calling it is appropriate — it just predicts tokens that look like the pattern in its context.

This means:
- If the model outputs `"action": "book_calendar_slot"` when it should not have → that is a **model failure** (wrong token prediction given the context)
- If the model outputs the right action but your code calls the wrong endpoint → that is a **scaffolding failure**
- If the model outputs valid JSON but your code acts on it before a prerequisite is satisfied (email confirmed delivered, in your P-023 case) → that is a **scaffolding failure**

With true function-calling, the model's contribution ends at the tool-call JSON. Everything after — whether to actually execute the call, whether to check preconditions, whether to chain calls — is scaffolding. The model does not know whether `write_to_hubspot` ran successfully. It cannot check. It only generates the call request.

This is the distinction your probe descriptions are missing: the model generates an intent, the scaffolding executes it. Failures in execution are always scaffolding failures.

---

**What this post does not cover:** How to build a multi-step tool-use loop (where the model sees the tool result and decides whether to call again) — that is the ReAct pattern and deserves its own explainer. This post only covers the single-call mechanism: what changes at the token level when `tools` is present. If your question is about chaining calls, the adjacent explainer would be on ReAct (Yao et al. 2022).

---

## Two Adjacent Concepts

**`tool_choice` parameter:** Passing `tool_choice="auto"` lets the model decide whether to call a tool or respond in text. Passing `tool_choice={"type": "function", "function": {"name": "book_calendar_slot"}}` forces the call — the model must output that function call regardless of context. This is the difference between the model choosing and you choosing. In most agent architectures, `"auto"` is what you want for generation and forced choice is what you want for structured extraction.

**Parallel tool calls:** Modern models can output multiple tool calls in a single response (`tool_calls` is a list). The model generates all of them before any are executed. It does not see the result of the first call before generating the second. If your agent needs the result of call 1 to decide whether to make call 2, you need two separate API calls, not one with two tools. This is the most common source of multi-step agent breakage.

---

## Pointers

- **Schick et al. (2023)** — *Toolformer: Language Models Can Teach Themselves to Use Tools.* The foundational paper showing how special API-call tokens are injected into the training corpus so the model learns to call tools at the right positions. The mechanism in production function-calling is a productionized version of this. [arxiv.org/abs/2302.04761](https://arxiv.org/abs/2302.04761)
- **OpenAI Function Calling Reference** — Authoritative documentation for the `tools` parameter, `tool_choice`, `tool_calls` response format, and the parallel tool call pattern. [platform.openai.com/docs/guides/function-calling](https://platform.openai.com/docs/guides/function-calling)
- **Tool used:** The code above is runnable with `openai` SDK and any OpenRouter-compatible model. The `finish_reason` field is the fastest way to verify the mechanism is firing: `"tool_calls"` means the model generated a tool call; `"stop"` means it responded in text.
- **Follow-on:** If you want to understand how the constrained decoding works at the logit level, see Willard & Louf (2023) *Efficient Guided Generation for Large Language Models* — the paper behind most JSON-mode and schema-constrained generation implementations. [arxiv.org/abs/2307.09702](https://arxiv.org/abs/2307.09702)
