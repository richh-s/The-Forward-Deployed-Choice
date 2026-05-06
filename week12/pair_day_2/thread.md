# Tweet Thread — Day 2

*Function-calling at the token level. Published under Rahel Samson. Ready to post.*

---

**Tweet 1**
You stuff a function description into your system prompt and parse the model's JSON output yourself.

That is NOT the same as function-calling with the `tools` parameter.

The model is doing something fundamentally different in each case. Here's what's actually happening at the token level. 🧵

---

**Tweet 2**
When you pass `tools=[...]`, the SDK serializes your function schema into a special token format and prepends it to the context — not as plain text, but as a structured block the model was fine-tuned to recognize.

The model was trained on thousands of examples: *tool definition in context + relevant query → output tool-call syntax.*

It's not reading your docs. It's pattern-matching on tokens it was trained on.

---

**Tweet 3**
The model's "choice" is just next-token prediction.

When the context contains a tool definition + a query that resembles training examples, the token sequence `{"name": "your_function", "arguments": ...}` gets higher probability than a natural-language response.

There's no deliberation. There's no reasoning step. Just: which token is most likely next?

---

**Tweet 4**
The backend then enforces constrained decoding against your schema.

If the model tries to output a field that doesn't exist, that token is blocked. The next highest-probability valid token is used instead.

Observable proof:

```
finish_reason: "tool_calls"   ← constrained decoding fired
tool_calls[0].function.name: "book_calendar_slot"   ← exact match, guaranteed
```

With prompt-stuffing, finish_reason is always "stop" — the model just ended a sentence.

---

**Tweet 5**
The practical consequence for agents:

With prompt-stuffing, Python decides what to do after parsing the model's text. The model generated an intent. Your code executed it.

If something goes wrong after the model's output → that's a scaffolding failure, not a model failure.

Most "agent bugs" are mislabeled. The model did its job. The scaffolding didn't check preconditions.

---

**Tweet 6**
Full explainer: the token-level mechanism, side-by-side code, observable API output, and why your probe descriptions are probably misattributing failures.

[blog link]

Sources:
- Schick et al. (2023) Toolformer — arxiv.org/abs/2302.04761
- OpenAI function calling docs
