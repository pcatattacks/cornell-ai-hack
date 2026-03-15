"""Generate a PDF report of Promptfoo judge eval results."""

import json
import sys
from collections import defaultdict
from datetime import datetime

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)


def _extract_metadata(result: dict) -> dict:
    for path in [
        lambda r: r.get("response", {}).get("metadata", {}),
        lambda r: r.get("metadata", {}),
        lambda r: r.get("vars", {}).get("metadata", {}),
    ]:
        meta = path(result)
        if meta and meta.get("judge_verdict"):
            return meta
    return {}


def generate_report(
    results_path: str = "output/results.json",
    output_path: str = "output/judge-eval-report.pdf",
) -> None:
    with open(results_path) as f:
        data = json.load(f)

    results = data.get("results", [])
    if isinstance(results, dict):
        results = results.get("results", [])

    # Analyze results
    total = 0
    agreements = 0
    false_negatives = 0
    false_positives = 0
    disagreements = []
    by_category = defaultdict(lambda: {"total": 0, "agree": 0, "verdicts": defaultdict(int)})

    for result in results:
        metadata = _extract_metadata(result)
        judge_verdict = metadata.get("judge_verdict")
        promptfoo_pass = result.get("success")

        if judge_verdict is None or promptfoo_pass is None:
            continue

        total += 1
        category = metadata.get("inferred_category", "unknown")
        by_category[category]["total"] += 1
        by_category[category]["verdicts"][judge_verdict] += 1

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
                "prompt": str(result.get("vars", {}).get("prompt", result.get("prompt", "")))[:200],
                "judge": judge_verdict,
                "promptfoo": "PASS" if pf_pass else "FAIL",
                "category": category,
                "evidence": metadata.get("judge_evidence", ""),
                "confidence": metadata.get("judge_confidence", 0),
                "response": str(result.get("response", {}).get("output", ""))[:300],
            })

    # Build PDF
    doc = SimpleDocTemplate(output_path, pagesize=letter, topMargin=0.75 * inch, bottomMargin=0.75 * inch)
    styles = getSampleStyleSheet()
    elements = []

    # Custom styles
    title_style = ParagraphStyle("Title2", parent=styles["Title"], fontSize=22, spaceAfter=6)
    subtitle_style = ParagraphStyle("Subtitle", parent=styles["Normal"], fontSize=11, textColor=colors.grey, spaceAfter=20)
    h2_style = ParagraphStyle("H2", parent=styles["Heading2"], spaceBefore=16, spaceAfter=8)
    body_style = ParagraphStyle("Body", parent=styles["Normal"], fontSize=10, leading=14)
    small_style = ParagraphStyle("Small", parent=styles["Normal"], fontSize=8, leading=10, textColor=colors.Color(0.3, 0.3, 0.3))

    # Title
    elements.append(Paragraph("Judge Eval Report", title_style))
    elements.append(Paragraph(f"Generated {datetime.now().strftime('%Y-%m-%d %H:%M')} | {total} test cases", subtitle_style))

    # Summary
    elements.append(Paragraph("Executive Summary", h2_style))
    agreement_pct = f"{agreements / total * 100:.1f}" if total else "0"
    elements.append(Paragraph(
        f"The vulnerability judge was evaluated against Promptfoo's built-in grader across "
        f"<b>{total}</b> prompt injection test cases. The judge achieved <b>{agreement_pct}% agreement</b> "
        f"with Promptfoo's grader, with <b>{false_positives}</b> false positive(s) and "
        f"<b>{false_negatives}</b> false negative(s).",
        body_style,
    ))
    elements.append(Spacer(1, 12))

    # Overall metrics table
    elements.append(Paragraph("Overall Metrics", h2_style))
    metrics_data = [
        ["Metric", "Value"],
        ["Total Test Cases", str(total)],
        ["Agreements", f"{agreements} ({agreement_pct}%)"],
        ["Disagreements", str(len(disagreements))],
        ["False Positives (judge too aggressive)", str(false_positives)],
        ["False Negatives (judge too lenient)", str(false_negatives)],
    ]
    metrics_table = Table(metrics_data, colWidths=[3 * inch, 2.5 * inch])
    metrics_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.Color(0.2, 0.2, 0.3)),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 10),
        ("BACKGROUND", (0, 1), (-1, -1), colors.Color(0.95, 0.95, 0.97)),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.Color(0.8, 0.8, 0.8)),
        ("ALIGN", (1, 0), (1, -1), "CENTER"),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("LEFTPADDING", (0, 0), (-1, -1), 10),
    ]))
    elements.append(metrics_table)
    elements.append(Spacer(1, 16))

    # Category breakdown
    elements.append(Paragraph("Results by Category", h2_style))
    cat_data = [["Category", "Total", "Agreed", "Agreement %", "Verdicts"]]
    for cat, counts in sorted(by_category.items()):
        rate = f"{counts['agree'] / counts['total'] * 100:.0f}%" if counts["total"] else "N/A"
        verdicts = ", ".join(f"{v}: {c}" for v, c in sorted(counts["verdicts"].items()))
        cat_data.append([
            cat.replace("_", " ").title(),
            str(counts["total"]),
            str(counts["agree"]),
            rate,
            verdicts,
        ])

    cat_table = Table(cat_data, colWidths=[1.8 * inch, 0.7 * inch, 0.8 * inch, 1.1 * inch, 2.1 * inch])
    cat_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.Color(0.2, 0.2, 0.3)),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("BACKGROUND", (0, 1), (-1, -1), colors.Color(0.95, 0.95, 0.97)),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.Color(0.8, 0.8, 0.8)),
        ("ALIGN", (1, 0), (3, -1), "CENTER"),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
    ]))
    elements.append(cat_table)
    elements.append(Spacer(1, 16))

    # Disagreements detail
    if disagreements:
        elements.append(Paragraph("Disagreements (Detailed)", h2_style))
        elements.append(Paragraph(
            "These are cases where the judge and Promptfoo's grader produced different verdicts. "
            "Each case warrants review to determine which grader is correct.",
            body_style,
        ))
        elements.append(Spacer(1, 8))

        for i, d in enumerate(disagreements[:10], 1):
            fp_fn = "FALSE POSITIVE" if d["promptfoo"] == "PASS" else "FALSE NEGATIVE"
            elements.append(Paragraph(
                f"<b>Disagreement #{i}</b> — <font color='red'>{fp_fn}</font> "
                f"[{d['category'].replace('_', ' ').title()}]",
                ParagraphStyle("DisagreeHeader", parent=body_style, fontSize=10, spaceBefore=8, textColor=colors.Color(0.1, 0.1, 0.1)),
            ))

            detail_data = [
                ["Judge Verdict", d["judge"]],
                ["Promptfoo Verdict", d["promptfoo"]],
                ["Confidence", f"{d['confidence']:.0%}"],
            ]
            detail_table = Table(detail_data, colWidths=[1.5 * inch, 5 * inch])
            detail_table.setStyle(TableStyle([
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
                ("BACKGROUND", (0, 0), (-1, -1), colors.Color(1, 0.97, 0.95)),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.Color(0.85, 0.85, 0.85)),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
            ]))
            elements.append(detail_table)

            elements.append(Paragraph(f"<b>Attack Prompt:</b> {d['prompt'][:300]}", small_style))
            elements.append(Paragraph(f"<b>Evidence:</b> {d['evidence'][:300]}", small_style))
            elements.append(Paragraph(f"<b>Chatbot Response:</b> {d['response'][:300]}", small_style))
            elements.append(Spacer(1, 8))

    # Recommendations
    elements.append(Paragraph("Recommendations", h2_style))
    recs = []
    if false_positives > 0:
        recs.append(
            f"<b>Reduce false positives:</b> The judge flagged {false_positives} case(s) as VULNERABLE "
            f"that Promptfoo considered safe. Review the judge prompt to reduce over-sensitivity, "
            f"particularly in the system_prompt_extraction category."
        )
    if false_negatives > 0:
        recs.append(
            f"<b>Reduce false negatives:</b> The judge missed {false_negatives} successful attack(s). "
            f"Tighten the judge prompt to catch more subtle vulnerabilities."
        )
    if not recs:
        recs.append(
            "<b>Judge is well-calibrated:</b> No disagreements found. Consider expanding the test suite "
            "with more attack categories (harmful, hijacking) via Promptfoo Cloud for broader coverage."
        )
    recs.append(
        "<b>Expand coverage:</b> Enable Promptfoo Cloud (free tier) to unlock harmful content plugins, "
        "hijacking, and composite jailbreak strategies for more comprehensive testing."
    )

    for rec in recs:
        elements.append(Paragraph(f"&bull; {rec}", body_style))
        elements.append(Spacer(1, 4))

    # Build
    doc.build(elements)
    print(f"Report saved to {output_path}")


if __name__ == "__main__":
    results = sys.argv[1] if len(sys.argv) > 1 else "output/results.json"
    output = sys.argv[2] if len(sys.argv) > 2 else "output/judge-eval-report.pdf"
    generate_report(results, output)
