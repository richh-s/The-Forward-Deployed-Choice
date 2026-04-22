"""
Save the NovaPay hiring signal brief to data/ for C007 claim evidence.
Run after confirming signal outputs are correct.
"""
import json
import os
import sys

# Ensure project root is on path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from enrichment.mock_brief import HIRING_SIGNAL_BRIEF, COMPETITOR_GAP_BRIEF

os.makedirs("data", exist_ok=True)

with open("data/hiring_signal_brief_novapay.json", "w") as f:
    json.dump(HIRING_SIGNAL_BRIEF, f, indent=2)

with open("data/competitor_gap_brief_novapay.json", "w") as f:
    json.dump(COMPETITOR_GAP_BRIEF, f, indent=2)

print("Saved: data/hiring_signal_brief_novapay.json")
print("Saved: data/competitor_gap_brief_novapay.json")

# Verify all 6 signals present
signals = HIRING_SIGNAL_BRIEF["signals"]
for i in range(1, 7):
    key = f"signal_{i}_{'funding_event' if i==1 else 'job_post_velocity' if i==2 else 'layoff_event' if i==3 else 'leadership_change' if i==4 else 'ai_maturity' if i==5 else 'icp_segment'}"
    present = key in signals and signals[key] is not None
    print(f"  Signal {i}: {'OK' if present else 'MISSING'} ({key})")
