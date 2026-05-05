# Morning Call Summary — Day 1

*Written by: Zemzem Hibet | Confirmed by: Rahel Samson*

---

## Sharpening Record

**Rahel's original draft question:**
"My judge model might be biased toward shorter responses. How do I check whether my LLM judge is favoring length over quality?"

**Interrogation from Zemzem:**
- "Which judge model specifically?"
- "What is the actual word count difference? Do you have a number?"
- "Which artifact would change if you found out the bias was real — your model card? Your datasheet? Your training pairs?"
- "What would you *do differently* if the swap test reversed? Would you retrain, or just document it?"

**Movement:** The original draft was answerable by linking any blog post on LLM evaluation bias. After interrogation, Rahel named: Qwen3-Next-80B as the specific judge model; 108 vs 231 words as the measured gap (2.14× ratio); `datasheet.md` and `training_data/preference_pairs.jsonl` as the specific artifacts whose credibility depends on the answer; and the concrete consequence — 40 preference pairs that trained her judge critic, with Delta A = +0.332 resting on them. The question moved from "how do I check for bias" to "given these specific numbers, is the 2.14× gap a quality signal or a judge artifact, and how do I separate the two."

**Zemzem's original draft question:**
"I send a large shared prefix in every API call. How does KV caching work and why does it save money?"

**Interrogation from Rahel:**
- "What is the actual size of the prefix in tokens?"
- "What model are you calling? The bytes-per-token calculation changes by architecture."
- "Can you verify the cache is firing from API metadata? What field do you read?"
- "Why does it have to be byte-identical — is that a design choice or a mathematical requirement?"

**Movement:** The original draft was answerable by reading Anthropic's pricing page. After interrogation, Zemzem named: ~2,500 tokens as the prefix size; the specific files sent (`icp_definition.md`, `style_guide.md`, `bench_summary.json`); the `cache_read_input_tokens` / `cache_creation_input_tokens` fields as the verification mechanism; and the specific question — why byte-for-byte identity is a mathematical requirement, not just a guideline. The question moved from "how does caching work" to "what is being stored at the transformer level, how many bytes per token per layer, and why does one extra space invalidate the cache."

Both questions committed as final by end of call.
