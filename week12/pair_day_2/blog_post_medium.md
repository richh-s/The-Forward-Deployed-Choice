# Your Agent Isn't Calling a Tool. It's Writing a String.

*And the difference matters more than you think.*

---

I spent weeks building an AI agent that "called tools." It wrote to HubSpot. It booked calendar slots. It made decisions about which email variant to send.

Except it didn't.

What it actually did was output a JSON string. My Python code read that string and decided what to do. The model had no idea HubSpot existed. It was just predicting characters.

When I finally understood what *actually* happens when a model calls a tool — at the token level — I had to rewrite several things. This post is what I wish I had read before I built the system.

---

## The Setup

My agent uses a plain `chat.completions.create()` call with a system prompt that says something like:

```
Available functions:
- book_calendar_slot(prospect_email, time_slot)
- write_to_hubspot(contact_id, email_sent)

If you need to call a function, output JSON:
{"action": "function_name", "args": {...}}
```

This is called **prompt-stuffing**. It works. Until it doesn't.

The model might output `"action": "book_calender_slot"` (typo). Or `"action": "schedule_meeting"` (hallucinated name). Or valid-looking JSON that causes a bug two steps later because the logic was wrong but the syntax was fine.

I blamed the model. I was wrong.

---

## What Actually Changes When You Use `tools=[...]`

When you pass a `tools` parameter to the API, three things happen that do not happen with prompt-stuffing.

### 1. The tool schema becomes special tokens, not text

The SDK converts your Python dict into a structured block that gets prepended to the conversation context. It looks something like this inside the model's context window:

```
# Tools

namespace functions {

// Book a calendar slot for a prospect
type book_calendar_slot = (_: {
  prospect_email: string,
  time_slot: string,
}) => any;

}
```

The model never sees a Python dict. It sees tokens. That format is not documentation — it is the exact token sequence the model was fine-tuned to recognize as a tool definition. There is a specific training corpus behind this. (Schick et al. 2023 — the Toolformer paper — showed how special API-call tokens get injected into training data so the model learns to produce them at the right moments.)

### 2. The model was trained to output a specific token sequence for tool calls

During post-training, the model saw thousands of examples with this pattern:

*Tool definitions in context + user query that warrants tool use → structured tool-call output*

It learned that when this pattern is present, the high-probability continuation is not a natural-language sentence but:

```json
{"name": "book_calendar_slot", "arguments": "{\"prospect_email\": \"cto@novapay.io\"}"}
```

This is not intelligence. It is pattern-matching on tokens seen during training. The model is not "deciding" to call a tool in any deliberate sense — it is predicting the next token, and the next token happens to be the start of a tool call because that has high probability given the context.

### 3. The backend applies logit masking against your schema

This is the part that changes everything.

Once the model starts generating a tool call, the inference engine tracks exactly where it is in your JSON schema. For every token it is about to generate, it checks: is this token valid at this position given the schema?

If the answer is no — **the probability of that token is set to −∞.** It cannot be sampled. Ever.

If your schema says `variant` must be one of `["signal_grounded", "exploratory"]`, and the model has generated `{"variant": "`, the engine masks out every token in the vocabulary except those that could start `signal_grounded` or `exploratory`. The model literally cannot hallucinate a third option. The option does not exist at that generation step.

This technique is called **logit masking** or **grammar-based constrained decoding**.

---

## The Observable Proof

You can verify this with one field in the API response:

```python
response = client.chat.completions.create(
    model="gpt-4o-mini",
    messages=messages,
    tools=tools,
    tool_choice="auto"
)

print(response.choices[0].finish_reason)
```

**With prompt-stuffing:** `finish_reason` is always `"stop"` — the model ended a sentence.

**With function-calling:** `finish_reason` is `"tool_calls"` — generation stopped because the tool call JSON was complete, not because the model reached a natural endpoint.

The full difference side by side:

```
=== Prompt-stuffing output ===
finish_reason: "stop"
content: '{"action": "book_calender_slot", "args": {"email": "..."}}'
#                      ^^ typo — model hallucinated field name

=== Function-calling output ===
finish_reason: "tool_calls"
tool_calls[0].function.name: "book_calendar_slot"   ← exact match, guaranteed
tool_calls[0].function.arguments: '{"prospect_email": "...", "time_slot": "..."}'
#                                                              ← schema-valid, guaranteed
```

---

## Why This Reframes Every "Agent Bug"

Here is what I got wrong in my original system.

With prompt-stuffing, "the model called the wrong tool" is not a meaningful failure category. **The model never called a tool.** It generated text. My Python code called the tool. If the wrong thing happened, either:

- The model generated the wrong text (model failure — fix the prompt or the training)
- My code acted on valid text incorrectly (scaffolding failure — fix the code)

These require completely different fixes. A prompt change cannot fix a scaffolding bug. A code change cannot fix a model that is generating the wrong output.

Once I understood logit masking, I went back through my probe descriptions and rewrote two of them:

**P-023 (HubSpot write before delivery confirmed):** I had written "agent writes to HubSpot before email confirmed delivered." Wrong. The model outputted valid JSON. My `hubspot_writer.py` called the API without checking delivery status first. That is a scaffolding failure. The fix is a precondition check in the code, not a prompt change.

**P-026 (Cal.com double-booking):** Same pattern. The model generated a time slot. `calendar.py` booked it without querying existing reservations. Scaffolding failure. Fix lives in `calendar.py`.

Reattributing these correctly changed which engineer owns the fix.

---

## Two Things Worth Knowing

**`tool_choice` controls who decides.** `tool_choice="auto"` lets the model decide whether to call a tool or respond in text — this is probabilistic, based on training. `tool_choice={"type": "function", "function": {"name": "..."}}` forces the call regardless of context — this is a hard constraint you impose. Use auto for generation, forced choice for structured extraction.

**Parallel tool calls mean the model is blind to its own results.** When a model outputs multiple tool calls in one response, it generates all of them before any are executed. It does not see the result of call 1 before generating call 2. If your agent needs the output of one call to decide the next action, that requires two separate API calls — one to get the result, one to decide what to do with it. This is the most common source of multi-step agent breakage.

---

## What This Scope Doesn't Cover

This post covers the single-call mechanism only — what changes at the token level when `tools` is present. It does not cover how to build a loop where the model sees a tool result and decides whether to call again. That is the ReAct pattern and it deserves a separate post.

---

## Sources

- **Schick et al. (2023)** — *Toolformer: Language Models Can Teach Themselves to Use Tools.* The foundational paper on how special API-call tokens are injected into training data. [arxiv.org/abs/2302.04761](https://arxiv.org/abs/2302.04761)
- **OpenAI Function Calling Reference** — Authoritative documentation for `tools`, `tool_choice`, `finish_reason`, and the parallel tool call format. [platform.openai.com/docs/guides/function-calling](https://platform.openai.com/docs/guides/function-calling)
- **Willard & Louf (2023)** — *Efficient Guided Generation for Large Language Models.* The paper behind most production logit masking implementations. [arxiv.org/abs/2307.09702](https://arxiv.org/abs/2307.09702)

---

*Written during Week 12 of the 10Academy TRP1 Forward-Deployed Engineer program. This post is the explainer I wrote for my pair-day partner's knowledge gap on function-calling mechanics.*
