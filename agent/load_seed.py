"""
Load Tenacious seed files into agent context at startup.
All paths are relative to project root.
"""
import json
from pathlib import Path

SEED = Path("tenacious_sales_data/seed")
SCHEMAS = Path("tenacious_sales_data/schemas")

_cache: dict = {}


def load_seed_context() -> dict:
    if _cache:
        return _cache

    _cache.update({
        "icp_definition":     (SEED / "icp_definition.md").read_text(),
        "style_guide":        (SEED / "style_guide.md").read_text(),
        "bench_summary":      json.loads((SEED / "bench_summary.json").read_text()),
        "baseline_numbers":   (SEED / "baseline_numbers.md").read_text(),
        "pricing_sheet":      (SEED / "pricing_sheet.md").read_text(),
        "case_studies":       (SEED / "case_studies.md").read_text(),
        "hiring_schema":      json.loads((SCHEMAS / "hiring_signal_brief.schema.json").read_text()),
        "gap_schema":         json.loads((SCHEMAS / "competitor_gap_brief.schema.json").read_text()),
        "transcripts":        _load_transcripts(),
        "email_sequences":    _load_email_sequences(),
    })
    return _cache


def _load_transcripts() -> list[dict]:
    transcripts = []
    t_dir = SEED / "discovery_transcripts"
    for f in sorted(t_dir.glob("*.md")):
        transcripts.append({"filename": f.name, "content": f.read_text()})
    return transcripts


def _load_email_sequences() -> dict:
    seq_dir = SEED / "email_sequences"
    return {
        f.stem: f.read_text()
        for f in sorted(seq_dir.glob("*.md"))
    }


def get_bench_summary() -> dict:
    return load_seed_context()["bench_summary"]


def get_available_count(stack: str) -> int:
    bench = get_bench_summary()
    return bench["stacks"].get(stack, {}).get("available_engineers", 0)


def build_few_shot_block(n_transcripts: int = 3) -> str:
    transcripts = load_seed_context()["transcripts"]
    selected = transcripts[:n_transcripts]
    return "\n\n---\n\n".join(t["content"] for t in selected)


def build_system_prompt_context() -> str:
    ctx = load_seed_context()
    bench = ctx["bench_summary"]
    available = {
        k: v["available_engineers"]
        for k, v in bench["stacks"].items()
    }
    bench_lines = "\n".join(
        f"  {stack}: {count} available (deploy in {bench['stacks'][stack]['time_to_deploy_days']} days)"
        for stack, count in available.items()
    )
    return f"""
## ICP CLASSIFICATION RULES (from seed/icp_definition.md)
{ctx["icp_definition"]}

## STYLE GUIDE (from seed/style_guide.md)
{ctx["style_guide"]}

## CURRENT BENCH CAPACITY (seed/bench_summary.json, as of {bench["as_of"]})
{bench_lines}

Total on bench: {bench["total_engineers_on_bench"]} | On paid engagements: {bench["total_engineers_on_paid_engagements"]}
{bench["honesty_constraint"]}

## PRICING (seed/pricing_sheet.md — partial, public-tier bands only)
{ctx["pricing_sheet"][:1500]}
"""


if __name__ == "__main__":
    ctx = load_seed_context()
    print(f"Loaded: {list(ctx.keys())}")
    print(f"Transcripts: {[t['filename'] for t in ctx['transcripts']]}")
    print(f"Email sequences: {list(ctx['email_sequences'].keys())}")
    print(f"Python bench: {get_available_count('python')} available")
    print(f"ML bench: {get_available_count('ml')} available")
