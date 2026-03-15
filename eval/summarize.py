"""Summarize Promptfoo eval results — judge accuracy by category."""

import json
import sys
from collections import defaultdict


def _extract_metadata(result: dict) -> dict:
    """Extract judge metadata from Promptfoo result, checking multiple paths."""
    for path in [
        lambda r: r.get("response", {}).get("metadata", {}),
        lambda r: r.get("metadata", {}),
        lambda r: r.get("vars", {}).get("metadata", {}),
    ]:
        meta = path(result)
        if meta and meta.get("judge_verdict"):
            return meta
    return {}


def summarize(results_path: str = "output/results.json") -> None:
    with open(results_path) as f:
        data = json.load(f)

    # Promptfoo output may nest results under results.results or just results
    results = data.get("results", [])
    if isinstance(results, dict):
        results = results.get("results", [])
    if not results:
        print("No results found.")
        return

    # Count agreements/disagreements
    total = 0
    agreements = 0
    false_negatives = 0  # Judge says RESISTANT, Promptfoo says FAIL
    false_positives = 0  # Judge says VULNERABLE, Promptfoo says PASS
    disagreements = []
    by_category = defaultdict(lambda: {"total": 0, "agree": 0})

    for result in results:
        metadata = _extract_metadata(result)
        judge_verdict = metadata.get("judge_verdict")
        promptfoo_pass = result.get("success", result.get("pass"))

        if judge_verdict is None or promptfoo_pass is None:
            continue

        total += 1
        category = metadata.get("inferred_category", "unknown")
        by_category[category]["total"] += 1

        # Map judge verdict to pass/fail for comparison
        # RESISTANT = chatbot defended successfully = PASS
        judge_pass = judge_verdict == "RESISTANT"
        pf_pass = bool(promptfoo_pass)

        if judge_pass == pf_pass:
            agreements += 1
            by_category[category]["agree"] += 1
        else:
            if judge_pass and not pf_pass:
                false_negatives += 1
            elif not judge_pass and pf_pass:
                false_positives += 1
            disagreements.append({
                "prompt": result.get("prompt", result.get("vars", {}).get("prompt", ""))[:80],
                "judge": judge_verdict,
                "promptfoo": "PASS" if pf_pass else "FAIL",
                "category": category,
            })

    if total == 0:
        print("No valid results with judge metadata found.")
        return

    # Print summary
    print(f"\n{'='*60}")
    print(f"JUDGE EVAL SUMMARY")
    print(f"{'='*60}")
    print(f"Total test cases:    {total}")
    print(f"Agreements:          {agreements} ({agreements/total*100:.1f}%)")
    print(f"Disagreements:       {len(disagreements)}")
    print(f"False negatives:     {false_negatives} (judge too lenient)")
    print(f"False positives:     {false_positives} (judge too aggressive)")

    print(f"\n{'─'*60}")
    print(f"BY CATEGORY:")
    print(f"{'─'*60}")
    for cat, counts in sorted(by_category.items()):
        rate = counts['agree'] / counts['total'] * 100 if counts['total'] else 0
        print(f"  {cat:30s}  {counts['agree']}/{counts['total']} ({rate:.0f}%)")

    if disagreements:
        print(f"\n{'─'*60}")
        print(f"DISAGREEMENTS (judge vs promptfoo):")
        print(f"{'─'*60}")
        for d in disagreements[:20]:
            print(f"  [{d['category']}] Judge={d['judge']}, Promptfoo={d['promptfoo']}")
            print(f"    Prompt: {d['prompt']}...")
            print()


if __name__ == "__main__":
    path = sys.argv[1] if len(sys.argv) > 1 else "output/results.json"
    summarize(path)
