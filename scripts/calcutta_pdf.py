"""
Generate a printable Calcutta auction cheat sheet PDF.
"""

import csv
from pathlib import Path
from reportlab.lib.pagesizes import letter, landscape
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import (
    SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, PageBreak,
    KeepTogether
)
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT

PAYOUTS = {1: 0.41, 2: 0.19, 3: 0.10, 4: 0.06, 5: 0.04,
           6: 0.035, 7: 0.03, 8: 0.025, 9: 0.02, 10: 0.015}


def load_players(csv_path):
    players = []
    with open(csv_path, "r") as f:
        reader = csv.DictReader(f)
        for row in reader:
            name = row["player_name"].strip().strip('"')

            def flt(key):
                v = row.get(key, "")
                return float(v) if v else 0.0

            p = {
                "name": name,
                "win_dg": flt("win_dg"),
                "win_book": flt("win_book_consensus"),
                "win_comp": flt("win_composite"),
                "t10_dg": flt("t10_dg"),
                "t10_book": flt("t10_book_consensus"),
                "t10_comp": flt("t10_composite"),
                "t20_comp": flt("t20_composite"),
                "mc_comp": flt("make_cut_composite"),
                "coursefit": row.get("coursefit", "").strip(),
                "expert": row.get("expert_picks", "").strip(),
            }

            # EV calculation
            pw = p["win_comp"]
            pt = p["t10_comp"]
            p2_10 = max(pt - pw, 0) / 9.0
            ev = pw * PAYOUTS[1] + sum(p2_10 * PAYOUTS[k] for k in range(2, 11))
            p["ev_pct"] = ev * 100

            # Signal score
            win_delta = (p["win_dg"] - p["win_book"]) * 100
            t10_delta = (p["t10_dg"] - p["t10_book"]) * 100
            p["win_delta"] = win_delta
            p["t10_delta"] = t10_delta

            score = 0
            if win_delta > 0.2: score += 1
            elif win_delta < -0.2: score -= 1
            if t10_delta > 2: score += 1
            elif t10_delta < -2: score -= 1
            if "[++]" in p["coursefit"]: score += 1
            elif "[+]" in p["coursefit"]: score += 0.5
            elif "[-]" in p["coursefit"]: score -= 0.5
            if "[++]" in p["expert"]: score += 1
            elif "[+]" in p["expert"]: score += 0.5
            elif "[-]" in p["expert"]: score -= 0.5
            p["score"] = score

            if score >= 2: p["signal"] = "STRONG BUY"
            elif score >= 1: p["signal"] = "BUY"
            elif score <= -1.5: p["signal"] = "STRONG AVOID"
            elif score <= -0.5: p["signal"] = "AVOID"
            else: p["signal"] = "HOLD"

            players.append(p)

    players.sort(key=lambda x: x["ev_pct"], reverse=True)
    total_ev = sum(p["ev_pct"] for p in players)
    for p in players:
        p["norm_pct"] = (p["ev_pct"] / total_ev) * 100
    return players


def signal_color(signal):
    if signal == "STRONG BUY": return colors.Color(0.0, 0.5, 0.0)    # dark green
    if signal == "BUY": return colors.Color(0.2, 0.65, 0.2)           # green
    if signal == "STRONG AVOID": return colors.Color(0.7, 0.0, 0.0)   # dark red
    if signal == "AVOID": return colors.Color(0.8, 0.3, 0.3)          # red
    return colors.Color(0.3, 0.3, 0.3)                                # gray


def signal_bg(signal):
    if signal == "STRONG BUY": return colors.Color(0.85, 0.95, 0.85)
    if signal == "BUY": return colors.Color(0.9, 0.97, 0.9)
    if signal == "STRONG AVOID": return colors.Color(0.95, 0.85, 0.85)
    if signal == "AVOID": return colors.Color(0.97, 0.9, 0.9)
    return colors.Color(0.97, 0.97, 0.97)


def build_pdf(players, output_path):
    doc = SimpleDocTemplate(
        str(output_path),
        pagesize=landscape(letter),
        leftMargin=0.4*inch, rightMargin=0.4*inch,
        topMargin=0.4*inch, bottomMargin=0.4*inch
    )

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle('Title2', parent=styles['Title'], fontSize=18, spaceAfter=4)
    subtitle_style = ParagraphStyle('Sub', parent=styles['Normal'], fontSize=9, textColor=colors.gray, spaceAfter=2)
    section_style = ParagraphStyle('Section', parent=styles['Heading2'], fontSize=13, spaceBefore=8, spaceAfter=4)
    small = ParagraphStyle('Small', parent=styles['Normal'], fontSize=7, leading=9)
    small_bold = ParagraphStyle('SmallBold', parent=small, fontName='Helvetica-Bold')
    small_r = ParagraphStyle('SmallR', parent=small, alignment=TA_RIGHT)
    small_c = ParagraphStyle('SmallC', parent=small, alignment=TA_CENTER)
    tiny = ParagraphStyle('Tiny', parent=styles['Normal'], fontSize=6.5, leading=8)
    tiny_r = ParagraphStyle('TinyR', parent=tiny, alignment=TA_RIGHT)
    tiny_c = ParagraphStyle('TinyC', parent=tiny, alignment=TA_CENTER)

    story = []

    # === PAGE 1: TITLE + MAIN PRICING TABLE ===
    story.append(Paragraph("Masters 2026 Calcutta Cheat Sheet", title_style))
    story.append(Paragraph(
        "Composite odds (DataGolf + 14 sportsbooks) | Payout: 1st 41%, 2nd 19%, 3rd 10%, 4th 6%, 5th 4%, "
        "6th 3.5%, 7th 3%, 8th 2.5%, 9th 2%, 10th 1.5%",
        subtitle_style
    ))
    story.append(Spacer(1, 4))

    # Build main table — top 35 players (fits one landscape page)
    header = [
        Paragraph('<b>#</b>', small_c),
        Paragraph('<b>Player</b>', small),
        Paragraph('<b>Win%</b>', small_r),
        Paragraph('<b>T10%</b>', small_r),
        Paragraph('<b>Fair %</b>', small_r),
        Paragraph('<b>Max Bid</b>', small_r),
        Paragraph('<b>Walk Away</b>', small_r),
        Paragraph('<b>DG vs Bk</b>', small_c),
        Paragraph('<b>CF</b>', small_c),
        Paragraph('<b>Exp</b>', small_c),
        Paragraph('<b>Score</b>', small_c),
        Paragraph('<b>Signal</b>', small_c),
    ]

    data = [header]
    row_colors = []

    for i, p in enumerate(players[:35]):
        dg_vs_bk = f"{p['t10_delta']:+.1f}%"
        row = [
            Paragraph(str(i+1), tiny_c),
            Paragraph(p["name"], tiny),
            Paragraph(f"{p['win_comp']*100:.2f}%", tiny_r),
            Paragraph(f"{p['t10_comp']*100:.1f}%", tiny_r),
            Paragraph(f"{p['norm_pct']:.2f}%", tiny_r),
            Paragraph(f"{p['norm_pct']:.2f}%", tiny_r),
            Paragraph(f"{p['norm_pct']*0.85:.2f}%", tiny_r),
            Paragraph(dg_vs_bk, tiny_c),
            Paragraph(p["coursefit"], tiny_c),
            Paragraph(p["expert"], tiny_c),
            Paragraph(f"{p['score']:+.1f}", tiny_c),
            Paragraph(p["signal"], tiny_c),
        ]
        data.append(row)
        row_colors.append(signal_bg(p["signal"]))

    col_widths = [0.25*inch, 1.6*inch, 0.55*inch, 0.5*inch, 0.55*inch, 0.6*inch, 0.65*inch, 0.6*inch, 0.4*inch, 0.4*inch, 0.45*inch, 0.9*inch]

    t = Table(data, colWidths=col_widths, repeatRows=1)

    style_cmds = [
        ('BACKGROUND', (0, 0), (-1, 0), colors.Color(0.2, 0.2, 0.3)),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('FONTSIZE', (0, 0), (-1, -1), 7),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('GRID', (0, 0), (-1, -1), 0.3, colors.Color(0.8, 0.8, 0.8)),
        ('TOPPADDING', (0, 0), (-1, -1), 1.5),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 1.5),
        ('LEFTPADDING', (0, 0), (-1, -1), 3),
        ('RIGHTPADDING', (0, 0), (-1, -1), 3),
    ]

    # Color each row by signal
    for i, bg in enumerate(row_colors):
        style_cmds.append(('BACKGROUND', (0, i+1), (-1, i+1), bg))

    t.setStyle(TableStyle(style_cmds))
    story.append(t)

    # === PAGE 2: STRATEGY + TARGETS ===
    story.append(PageBreak())
    story.append(Paragraph("Auction Strategy Guide", title_style))
    story.append(Spacer(1, 6))

    # Target list
    story.append(Paragraph("Priority Targets (bid aggressively)", section_style))

    targets = [p for p in players if p["score"] >= 2 and p["norm_pct"] >= 0.5]
    targets.sort(key=lambda x: -x["score"])

    t_header = [
        Paragraph('<b>Player</b>', small),
        Paragraph('<b>Fair %</b>', small_r),
        Paragraph('<b>Win%</b>', small_r),
        Paragraph('<b>T10%</b>', small_r),
        Paragraph('<b>Score</b>', small_c),
        Paragraph('<b>DG vs Bk T10</b>', small_c),
        Paragraph('<b>CF</b>', small_c),
        Paragraph('<b>Exp</b>', small_c),
        Paragraph('<b>Why</b>', small),
    ]

    t_data = [t_header]
    for p in targets:
        reasons = []
        if p["t10_delta"] > 2: reasons.append("Model higher than books")
        if "[++]" in p["coursefit"]: reasons.append("Strong coursefit")
        elif "[+]" in p["coursefit"]: reasons.append("Good coursefit")
        if "[++]" in p["expert"]: reasons.append("Expert consensus")
        elif "[+]" in p["expert"]: reasons.append("Expert pick")

        t_data.append([
            Paragraph(f'<b>{p["name"]}</b>', tiny),
            Paragraph(f'{p["norm_pct"]:.2f}%', tiny_r),
            Paragraph(f'{p["win_comp"]*100:.2f}%', tiny_r),
            Paragraph(f'{p["t10_comp"]*100:.1f}%', tiny_r),
            Paragraph(f'{p["score"]:+.1f}', tiny_c),
            Paragraph(f'{p["t10_delta"]:+.1f}%', tiny_c),
            Paragraph(p["coursefit"], tiny_c),
            Paragraph(p["expert"], tiny_c),
            Paragraph(", ".join(reasons), tiny),
        ])

    t_widths2 = [1.5*inch, 0.55*inch, 0.5*inch, 0.5*inch, 0.45*inch, 0.7*inch, 0.4*inch, 0.4*inch, 3.0*inch]
    t2 = Table(t_data, colWidths=t_widths2, repeatRows=1)
    t2.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.Color(0.1, 0.4, 0.1)),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('GRID', (0, 0), (-1, -1), 0.3, colors.Color(0.8, 0.8, 0.8)),
        ('BACKGROUND', (0, 1), (-1, -1), colors.Color(0.92, 0.97, 0.92)),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('TOPPADDING', (0, 0), (-1, -1), 2),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 2),
        ('LEFTPADDING', (0, 0), (-1, -1), 3),
        ('RIGHTPADDING', (0, 0), (-1, -1), 3),
    ]))
    story.append(t2)
    story.append(Spacer(1, 12))

    # Let go list
    story.append(Paragraph("Let Others Overpay (likely overbid)", section_style))

    sells = [p for p in players if p["score"] <= -1 and p["norm_pct"] >= 0.3]
    sells.sort(key=lambda x: x["score"])

    s_data = [[
        Paragraph('<b>Player</b>', small),
        Paragraph('<b>Fair %</b>', small_r),
        Paragraph('<b>Win%</b>', small_r),
        Paragraph('<b>Score</b>', small_c),
        Paragraph('<b>DG vs Bk T10</b>', small_c),
        Paragraph('<b>Why to avoid</b>', small),
    ]]

    for p in sells:
        reasons = []
        if p["t10_delta"] < -2: reasons.append("Books inflated vs model")
        if p["win_delta"] < -0.2: reasons.append("DG win much lower than books")
        if "[-]" in p["coursefit"]: reasons.append("Poor coursefit")
        if "[-]" in p["expert"]: reasons.append("Experts down")
        if not reasons: reasons.append("Negative signal combination")

        s_data.append([
            Paragraph(f'<b>{p["name"]}</b>', tiny),
            Paragraph(f'{p["norm_pct"]:.2f}%', tiny_r),
            Paragraph(f'{p["win_comp"]*100:.2f}%', tiny_r),
            Paragraph(f'{p["score"]:+.1f}', tiny_c),
            Paragraph(f'{p["t10_delta"]:+.1f}%', tiny_c),
            Paragraph(", ".join(reasons), tiny),
        ])

    s_widths = [1.5*inch, 0.55*inch, 0.5*inch, 0.45*inch, 0.7*inch, 4.0*inch]
    s_table = Table(s_data, colWidths=s_widths, repeatRows=1)
    s_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.Color(0.5, 0.1, 0.1)),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('GRID', (0, 0), (-1, -1), 0.3, colors.Color(0.8, 0.8, 0.8)),
        ('BACKGROUND', (0, 1), (-1, -1), colors.Color(0.97, 0.92, 0.92)),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('TOPPADDING', (0, 0), (-1, -1), 2),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 2),
        ('LEFTPADDING', (0, 0), (-1, -1), 3),
        ('RIGHTPADDING', (0, 0), (-1, -1), 3),
    ]))
    story.append(s_table)
    story.append(Spacer(1, 12))

    # Recommended portfolio
    story.append(Paragraph("Recommended 9-Player Portfolio", section_style))

    rec_names = [
        "Fleetwood, Tommy", "Young, Cameron", "Matsuyama, Hideki",
        "MacIntyre, Robert", "Kim, Si Woo", "Henley, Russell",
        "Hojgaard, Nicolai", "Knapp, Jake", "Spaun, J.J."
    ]
    rec_players = [next(p for p in players if p["name"] == n) for n in rec_names]

    p_none_t10 = 1.0
    p_none_win = 1.0
    total_norm = 0
    for p in rec_players:
        p_none_t10 *= (1 - p["t10_comp"])
        p_none_win *= (1 - p["win_comp"])
        total_norm += p["norm_pct"]

    r_data = [[
        Paragraph('<b>Player</b>', small),
        Paragraph('<b>Fair %</b>', small_r),
        Paragraph('<b>Win%</b>', small_r),
        Paragraph('<b>T10%</b>', small_r),
        Paragraph('<b>Score</b>', small_c),
        Paragraph('<b>CF</b>', small_c),
        Paragraph('<b>Exp</b>', small_c),
    ]]

    for p in rec_players:
        r_data.append([
            Paragraph(f'<b>{p["name"]}</b>', tiny),
            Paragraph(f'{p["norm_pct"]:.2f}%', tiny_r),
            Paragraph(f'{p["win_comp"]*100:.2f}%', tiny_r),
            Paragraph(f'{p["t10_comp"]*100:.1f}%', tiny_r),
            Paragraph(f'{p["score"]:+.1f}', tiny_c),
            Paragraph(p["coursefit"], tiny_c),
            Paragraph(p["expert"], tiny_c),
        ])

    r_widths = [1.5*inch, 0.55*inch, 0.5*inch, 0.5*inch, 0.45*inch, 0.4*inch, 0.4*inch]
    r_table = Table(r_data, colWidths=r_widths, repeatRows=1)
    r_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.Color(0.15, 0.15, 0.4)),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('GRID', (0, 0), (-1, -1), 0.3, colors.Color(0.8, 0.8, 0.8)),
        ('BACKGROUND', (0, 1), (-1, -1), colors.Color(0.93, 0.93, 0.98)),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('TOPPADDING', (0, 0), (-1, -1), 2),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 2),
        ('LEFTPADDING', (0, 0), (-1, -1), 3),
        ('RIGHTPADDING', (0, 0), (-1, -1), 3),
    ]))
    story.append(r_table)

    # Portfolio stats
    story.append(Spacer(1, 6))
    stats_text = (
        f"<b>Portfolio Stats:</b> Total fair value: {total_norm:.1f}% | "
        f"P(at least one winner): {(1-p_none_win)*100:.1f}% | "
        f"P(at least one T10): {(1-p_none_t10)*100:.1f}% | "
        f"Target spend: ~{total_norm*0.75:.1f}% of pot"
    )
    story.append(Paragraph(stats_text, small))

    story.append(Spacer(1, 12))

    # Quick reference box
    story.append(Paragraph("Quick Reference", section_style))
    ref_data = [
        ["Signal", "Meaning", "Action"],
        ["STRONG BUY (+2 or higher)", "Model, coursefit, and experts all agree", "Bid aggressively up to Fair %"],
        ["BUY (+1 to +1.9)", "Favorable signals", "Bid up to 85% of Fair %"],
        ["HOLD (0 to +0.9)", "Neutral or mixed signals", "Only buy if price is well below Fair %"],
        ["AVOID (-0.5 to -1)", "One or more negative signals", "Let others have them"],
        ["STRONG AVOID (-1.5 or worse)", "Model says much worse than crowd thinks", "Do not bid"],
    ]

    ref_table = Table(ref_data, colWidths=[2*inch, 3*inch, 3*inch])
    ref_style = [
        ('BACKGROUND', (0, 0), (-1, 0), colors.Color(0.3, 0.3, 0.3)),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 8),
        ('GRID', (0, 0), (-1, -1), 0.3, colors.Color(0.8, 0.8, 0.8)),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('TOPPADDING', (0, 0), (-1, -1), 3),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
        ('LEFTPADDING', (0, 0), (-1, -1), 4),
    ]
    # Color rows
    for i in range(1, len(ref_data)):
        if "STRONG BUY" in ref_data[i][0]:
            ref_style.append(('BACKGROUND', (0, i), (-1, i), colors.Color(0.85, 0.95, 0.85)))
        elif "BUY" in ref_data[i][0] and "STRONG" not in ref_data[i][0]:
            ref_style.append(('BACKGROUND', (0, i), (-1, i), colors.Color(0.9, 0.97, 0.9)))
        elif "STRONG AVOID" in ref_data[i][0]:
            ref_style.append(('BACKGROUND', (0, i), (-1, i), colors.Color(0.95, 0.85, 0.85)))
        elif "AVOID" in ref_data[i][0]:
            ref_style.append(('BACKGROUND', (0, i), (-1, i), colors.Color(0.97, 0.9, 0.9)))

    ref_table.setStyle(TableStyle(ref_style))
    story.append(ref_table)

    # === PAGE 3: REMAINING PLAYERS (36-91) ===
    story.append(PageBreak())
    story.append(Paragraph("Remaining Players (#36-91)", section_style))

    rest_header = [
        Paragraph('<b>#</b>', small_c),
        Paragraph('<b>Player</b>', small),
        Paragraph('<b>Win%</b>', small_r),
        Paragraph('<b>T10%</b>', small_r),
        Paragraph('<b>Fair %</b>', small_r),
        Paragraph('<b>CF</b>', small_c),
        Paragraph('<b>Exp</b>', small_c),
        Paragraph('<b>Signal</b>', small_c),
    ]

    rest_data = [rest_header]
    rest_colors = []
    for i, p in enumerate(players[35:], 36):
        rest_data.append([
            Paragraph(str(i), tiny_c),
            Paragraph(p["name"], tiny),
            Paragraph(f"{p['win_comp']*100:.3f}%", tiny_r),
            Paragraph(f"{p['t10_comp']*100:.2f}%", tiny_r),
            Paragraph(f"{p['norm_pct']:.2f}%", tiny_r),
            Paragraph(p["coursefit"], tiny_c),
            Paragraph(p["expert"], tiny_c),
            Paragraph(p["signal"], tiny_c),
        ])
        rest_colors.append(signal_bg(p["signal"]))

    rest_widths = [0.3*inch, 1.8*inch, 0.6*inch, 0.55*inch, 0.55*inch, 0.4*inch, 0.4*inch, 0.9*inch]
    rest_table = Table(rest_data, colWidths=rest_widths, repeatRows=1)

    rest_style_cmds = [
        ('BACKGROUND', (0, 0), (-1, 0), colors.Color(0.2, 0.2, 0.3)),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('GRID', (0, 0), (-1, -1), 0.3, colors.Color(0.8, 0.8, 0.8)),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('TOPPADDING', (0, 0), (-1, -1), 1.5),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 1.5),
        ('LEFTPADDING', (0, 0), (-1, -1), 3),
        ('RIGHTPADDING', (0, 0), (-1, -1), 3),
    ]
    for i, bg in enumerate(rest_colors):
        rest_style_cmds.append(('BACKGROUND', (0, i+1), (-1, i+1), bg))

    rest_table.setStyle(TableStyle(rest_style_cmds))
    story.append(rest_table)

    doc.build(story)
    return output_path


if __name__ == "__main__":
    csv_path = Path(__file__).parent.parent / "composite_odds_masters_tournament.csv"
    output_path = Path(__file__).parent.parent / "masters_calcutta_cheat_sheet.pdf"

    players = load_players(csv_path)
    result = build_pdf(players, output_path)
    print(f"PDF saved to: {result}")
