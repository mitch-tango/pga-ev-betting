from __future__ import annotations

"""
Discord bot for the PGA +EV Betting System.

Slash commands:
    /status     — Dashboard: bankroll, exposure, season ROI
    /bankroll   — Quick bankroll + recent transactions
    /scan       — Trigger pre-tournament or pre-round scan
    /place      — Log a bet from scan results
    /live       — Live spot-check during rounds
    /clv        — CLV trend
    /settle     — Auto-settle unsettled bets
"""

import asyncio
import logging
from datetime import datetime, time as dtime, timedelta
from typing import Optional
from zoneinfo import ZoneInfo

import discord
from discord import app_commands

from src.db import supabase_client as db
from src.core.edge import (
    CandidateBet,
    calculate_placement_edges,
    calculate_matchup_edges,
    calculate_3ball_edges,
)
from src.core.devig import american_to_decimal, decimal_to_american
from src.normalize.players import resolve_candidates
from src.pipeline.pull_outrights import pull_all_outrights
from src.pipeline.pull_matchups import (
    pull_tournament_matchups,
    pull_round_matchups,
    pull_3balls,
)
from src.pipeline.pull_live import pull_live_predictions
from src.pipeline.pull_results import fetch_results, match_bets_to_results
from src.core.settlement import settle_placement_bet
import config

log = logging.getLogger("pga-ev-bot")

# Market type mapping from DG API names to internal names
MARKET_MAP = {
    "win": "win",
    "top_10": "t10",
    "top_20": "t20",
    "make_cut": "make_cut",
}


ET = ZoneInfo("America/New_York")


class EVBot(discord.Client):
    """PGA +EV Betting System Discord bot."""

    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)
        # Cache last scan results for /place
        self.last_scan: list[CandidateBet] = []
        self.last_scan_tournament_id: str | None = None
        self.last_scan_time: datetime | None = None
        self._alert_task: asyncio.Task | None = None

    async def setup_hook(self):
        await self.tree.sync()
        log.info("Slash commands synced")
        if config.ALERT_ENABLED:
            self._alert_task = self.loop.create_task(self._scheduled_alerts())
            log.info("Scheduled alerts enabled (channel %s)", config.DISCORD_ALERT_CHANNEL_ID)

    async def on_ready(self):
        log.info(f"Bot ready: {self.user} ({self.user.id})")

    # ------------------------------------------------------------------
    # Scheduled alert loop
    # ------------------------------------------------------------------
    async def _scheduled_alerts(self):
        """Background loop that fires scans at configured times."""
        await self.wait_until_ready()
        log.info("Alert scheduler started")

        while not self.is_closed():
            now_et = datetime.now(ET)
            weekday = now_et.weekday()  # 0=Mon … 6=Sun

            # Wednesday 6 PM ET → pre-tournament scan
            if weekday == 2 and now_et.hour == config.ALERT_PRETOURNAMENT_HOUR:
                await self._run_and_alert("pretournament")

            # Thu(3)-Sun(6) at configured hour → pre-round scan
            if weekday in (3, 4, 5, 6) and now_et.hour == config.ALERT_PREROUND_HOUR:
                round_number = weekday - 2  # Thu=R1, Fri=R2, Sat=R3, Sun=R4
                await self._run_and_alert("preround", round_number=round_number)

            # Sleep until the next hour boundary + 1 min buffer
            now_et = datetime.now(ET)
            next_hour = now_et.replace(minute=0, second=0, microsecond=0)
            next_hour += timedelta(hours=1)
            sleep_secs = (next_hour - now_et).total_seconds() + 60
            await asyncio.sleep(sleep_secs)

    async def _run_and_alert(
        self, scan_type: str, *, round_number: int | None = None, tour: str = "pga",
        channel=None,
    ):
        """Run a scan and post results to the alert channel (or a provided channel)."""
        if channel is None:
            channel = self.get_channel(config.DISCORD_ALERT_CHANNEL_ID)
        if not channel:
            log.warning("Alert channel %s not found", config.DISCORD_ALERT_CHANNEL_ID)
            return

        log.info("Running scheduled %s scan", scan_type)
        try:
            if scan_type == "pretournament":
                result = await asyncio.to_thread(_run_pretournament_scan, tour)
            else:
                result = await asyncio.to_thread(_run_preround_scan, tour, round_number)
        except Exception as e:
            log.error("Scheduled %s scan failed: %s", scan_type, e)
            await channel.send(f"Scheduled {scan_type} scan failed: {e}")
            return

        candidates, tournament_id, tournament_name, bankroll, weekly_exp, tourn_exp = result

        # Cache for /place
        self.last_scan = candidates
        self.last_scan_tournament_id = tournament_id
        self.last_scan_time = datetime.now()

        if not candidates:
            embed = discord.Embed(
                title=f"Scheduled Scan — {tournament_name}",
                description="No +EV candidates found above threshold.",
                color=0x95A5A6,
                timestamp=datetime.now(),
            )
            await channel.send(embed=embed)
            return

        # Build the alert embed
        high_edge = [c for c in candidates if c.edge >= config.ALERT_HIGH_EDGE_THRESHOLD]
        color = 0xE74C3C if high_edge else 0xE67E22

        weekly_limit = bankroll * config.MAX_WEEKLY_EXPOSURE_PCT
        tourn_limit = bankroll * config.MAX_TOURNAMENT_EXPOSURE_PCT

        embed = discord.Embed(
            title=f"Scheduled Scan — {tournament_name}",
            description=(
                f"**{len(candidates)}** candidates found"
                f" ({len(high_edge)} high-edge)\n"
                f"Bankroll: ${bankroll:,.2f} | "
                f"Weekly: ${weekly_exp:,.0f}/${weekly_limit:,.0f} | "
                f"Tournament: ${tourn_exp:,.0f}/${tourn_limit:,.0f}"
            ),
            color=color,
            timestamp=datetime.now(),
        )

        lines = []
        lines.append(f"{'#':>2} {'Player':<20} {'Mkt':<6} {'Book':<10} {'Odds':>6} {'Edge':>5} {'Stake':>5}")
        for i, c in enumerate(candidates, 1):
            if c.opponent_name:
                name = f"{c.player_name[:9]}v{c.opponent_name[:9]}"
            else:
                name = c.player_name[:20]

            mkt = c.market_type
            if c.round_number:
                mkt = f"R{c.round_number}H2H" if c.market_type != "3_ball" else f"R{c.round_number}3B"

            flag = " **" if c.edge >= config.ALERT_HIGH_EDGE_THRESHOLD else ""
            lines.append(
                f"{i:>2} {name:<20} {mkt:<6} {c.best_book:<10} "
                f"{c.best_odds_american:>6} {c.edge*100:>4.1f}% ${c.suggested_stake:>3.0f}"
                f"{flag}"
            )

            if len("\n".join(lines)) > 900:
                embed.add_field(
                    name="Candidates" if len(embed.fields) == 0 else "\u200b",
                    value=f"```\n" + "\n".join(lines) + "\n```",
                    inline=False,
                )
                lines = []

        if lines:
            embed.add_field(
                name="Candidates" if len(embed.fields) == 0 else "\u200b",
                value=f"```\n" + "\n".join(lines) + "\n```",
                inline=False,
            )

        embed.set_footer(text="Use /place <number> to log a bet")

        # Mention role for high-edge alerts
        mention = ""
        if high_edge and config.DISCORD_ALERT_ROLE_ID:
            mention = f"<@&{config.DISCORD_ALERT_ROLE_ID}> "

        await channel.send(content=f"{mention}{len(high_edge)} high-edge bet(s) found!" if mention else None, embed=embed)



bot = EVBot()


# ---------------------------------------------------------------------------
# /alert — manual trigger + status
# ---------------------------------------------------------------------------
@bot.tree.command(name="alert", description="Trigger a scan alert now, or check alert status")
@app_commands.describe(
    action="What to do",
    round_number="Round number (for preround)",
    tour="Tour (default: pga)",
)
@app_commands.choices(action=[
    app_commands.Choice(name="Run pre-tournament scan now", value="pretournament"),
    app_commands.Choice(name="Run pre-round scan now", value="preround"),
    app_commands.Choice(name="Show alert status", value="status"),
])
async def cmd_alert(
    interaction: discord.Interaction,
    action: app_commands.Choice[str],
    round_number: Optional[int] = None,
    tour: Optional[str] = "pga",
):
    await interaction.response.defer()

    if action.value == "status":
        now_et = datetime.now(ET)
        status_lines = [
            f"**Alerts enabled:** {config.ALERT_ENABLED}",
            f"**Channel:** <#{config.DISCORD_ALERT_CHANNEL_ID}>" if config.DISCORD_ALERT_CHANNEL_ID else "**Channel:** not set",
            f"**High-edge threshold:** {config.ALERT_HIGH_EDGE_THRESHOLD*100:.0f}%",
            f"**Pre-tournament:** Wed {config.ALERT_PRETOURNAMENT_HOUR}:00 ET",
            f"**Pre-round:** Thu-Sun {config.ALERT_PREROUND_HOUR}:00 ET",
            f"**Current time (ET):** {now_et.strftime('%A %H:%M')}",
        ]
        if bot.last_scan_time:
            status_lines.append(f"**Last scan:** {bot.last_scan_time.strftime('%Y-%m-%d %H:%M')} ({len(bot.last_scan)} candidates)")
        embed = discord.Embed(
            title="Alert Configuration",
            description="\n".join(status_lines),
            color=0x3498DB,
        )
        await interaction.followup.send(embed=embed)
        return

    # Manual trigger — run scan and post alert to this channel
    await interaction.followup.send(f"Running {action.value} scan...")
    await bot._run_and_alert(action.value, round_number=round_number, tour=tour, channel=interaction.channel)


# ---------------------------------------------------------------------------
# /status
# ---------------------------------------------------------------------------
@bot.tree.command(name="status", description="Dashboard: bankroll, exposure, season ROI")
async def cmd_status(interaction: discord.Interaction):
    await interaction.response.defer()

    bankroll = await asyncio.to_thread(db.get_bankroll)
    weekly_bets = await asyncio.to_thread(db.get_open_bets_for_week)
    weekly_exposure = sum(b.get("stake", 0) for b in weekly_bets)
    weekly_limit = bankroll * config.MAX_WEEKLY_EXPOSURE_PCT

    embed = discord.Embed(
        title="PGA +EV System — Status",
        color=0x2ECC71,
        timestamp=datetime.now(),
    )
    embed.add_field(
        name="Bankroll",
        value=f"${bankroll:,.2f}",
        inline=True,
    )
    pct = (weekly_exposure / weekly_limit * 100) if weekly_limit > 0 else 0
    embed.add_field(
        name="Weekly Exposure",
        value=f"${weekly_exposure:,.0f} / ${weekly_limit:,.0f} ({pct:.0f}%)",
        inline=True,
    )

    roi_data = await asyncio.to_thread(db.get_roi_by_market)
    if roi_data:
        total_bets = sum(r.get("total_bets", 0) for r in roi_data)
        total_staked = sum(r.get("total_staked", 0) for r in roi_data)
        total_pnl = sum(r.get("total_pnl", 0) for r in roi_data)
        overall_roi = (total_pnl / total_staked * 100) if total_staked > 0 else 0

        embed.add_field(
            name="Season",
            value=(
                f"{total_bets} bets | ${total_staked:,.0f} staked\n"
                f"P&L ${total_pnl:+,.0f} | ROI {overall_roi:+.1f}%"
            ),
            inline=False,
        )

        lines = []
        lines.append(f"{'Market':<12} {'Bets':>4} {'ROI':>7} {'CLV':>6} {'W-L':>5}")
        for r in roi_data:
            w = r.get("wins", 0)
            l = r.get("losses", 0)
            lines.append(
                f"{r['market_type']:<12} {r['total_bets']:>4} "
                f"{r.get('roi_pct', 0):>+6.1f}% "
                f"{r.get('avg_clv_pct', 0):>5.2f}% "
                f"{w}-{l}"
            )
        embed.add_field(
            name="By Market",
            value=f"```\n" + "\n".join(lines) + "\n```",
            inline=False,
        )
    else:
        embed.add_field(name="Season", value="No settled bets yet.", inline=False)

    roi_by_book = await asyncio.to_thread(db.get_roi_by_book)
    if roi_by_book:
        lines = []
        for r in roi_by_book:
            lines.append(
                f"{r['book']:<12} {r['total_bets']:>4} "
                f"{r.get('roi_pct', 0):>+6.1f}% "
                f"{r.get('avg_clv_pct', 0):>5.2f}%"
            )
        embed.add_field(
            name="By Book",
            value=f"```\n" + "\n".join(lines) + "\n```",
            inline=False,
        )

    await interaction.followup.send(embed=embed)


# ---------------------------------------------------------------------------
# /bankroll
# ---------------------------------------------------------------------------
@bot.tree.command(name="bankroll", description="Quick bankroll check with recent transactions")
async def cmd_bankroll(interaction: discord.Interaction):
    await interaction.response.defer()

    bankroll = await asyncio.to_thread(db.get_bankroll)
    curve = await asyncio.to_thread(db.get_bankroll_curve)

    embed = discord.Embed(
        title=f"${bankroll:,.2f}",
        color=0x3498DB,
    )

    if curve:
        recent = curve[-5:]
        lines = []
        for row in reversed(recent):
            amt = row.get("amount", 0)
            entry_type = row.get("entry_type", "")
            date = str(row.get("entry_date", ""))[:10]
            notes = row.get("notes", "") or entry_type
            lines.append(f"${amt:>+8,.0f}  {notes:<25} {date}")
        embed.add_field(
            name="Recent Transactions",
            value=f"```\n" + "\n".join(lines) + "\n```",
            inline=False,
        )

    await interaction.followup.send(embed=embed)


# ---------------------------------------------------------------------------
# /clv
# ---------------------------------------------------------------------------
@bot.tree.command(name="clv", description="CLV trend and closing line analysis")
async def cmd_clv(interaction: discord.Interaction):
    await interaction.response.defer()

    clv_data = await asyncio.to_thread(db.get_clv_weekly)

    embed = discord.Embed(title="CLV Trend", color=0x9B59B6)

    if clv_data:
        lines = []
        lines.append(f"{'Week':<11} {'Bets':>4} {'Avg CLV':>8} {'P&L':>9}")
        for row in clv_data:
            week = str(row.get("week", ""))[:10]
            lines.append(
                f"{week:<11} {row.get('bets', 0):>4} "
                f"{row.get('avg_clv_pct', 0):>+7.2f}% "
                f"${row.get('weekly_pnl', 0):>+7,.0f}"
            )

        total_bets = sum(r.get("bets", 0) for r in clv_data)
        if total_bets > 0:
            avg_clv = sum(
                r.get("avg_clv_pct", 0) * r.get("bets", 0) for r in clv_data
            ) / total_bets
            lines.append(f"\nSeason avg CLV: {avg_clv:+.2f}%")

        embed.description = f"```\n" + "\n".join(lines) + "\n```"
    else:
        embed.description = "No CLV data yet."

    await interaction.followup.send(embed=embed)


# ---------------------------------------------------------------------------
# /scan
# ---------------------------------------------------------------------------
@bot.tree.command(name="scan", description="Run a pre-tournament or pre-round scan")
@app_commands.describe(
    scan_type="Type of scan to run",
    round_number="Round number (for preround scans)",
    tour="Tour to scan (default: pga)",
)
@app_commands.choices(scan_type=[
    app_commands.Choice(name="Pre-Tournament", value="pretournament"),
    app_commands.Choice(name="Pre-Round", value="preround"),
])
async def cmd_scan(
    interaction: discord.Interaction,
    scan_type: app_commands.Choice[str],
    round_number: Optional[int] = None,
    tour: Optional[str] = "pga",
):
    await interaction.response.defer()

    try:
        if scan_type.value == "pretournament":
            result = await asyncio.to_thread(
                _run_pretournament_scan, tour
            )
        else:
            result = await asyncio.to_thread(
                _run_preround_scan, tour, round_number
            )
    except Exception as e:
        await interaction.followup.send(f"Scan failed: {e}")
        return

    candidates, tournament_id, tournament_name, bankroll, weekly_exp, tourn_exp = result

    # Cache for /place
    bot.last_scan = candidates
    bot.last_scan_tournament_id = tournament_id
    bot.last_scan_time = datetime.now()

    if not candidates:
        embed = discord.Embed(
            title=f"Scan — {tournament_name}",
            description="No +EV candidates found above threshold.",
            color=0x95A5A6,
        )
        await interaction.followup.send(embed=embed)
        return

    weekly_limit = bankroll * config.MAX_WEEKLY_EXPOSURE_PCT
    tourn_limit = bankroll * config.MAX_TOURNAMENT_EXPOSURE_PCT

    embed = discord.Embed(
        title=f"Scan — {tournament_name}",
        description=(
            f"**{len(candidates)}** candidates found\n"
            f"Bankroll: ${bankroll:,.2f} | "
            f"Weekly: ${weekly_exp:,.0f}/${weekly_limit:,.0f} | "
            f"Tournament: ${tourn_exp:,.0f}/${tourn_limit:,.0f}"
        ),
        color=0xE67E22,
        timestamp=datetime.now(),
    )

    # Format candidates table (Discord has 1024 char limit per field)
    lines = []
    lines.append(f"{'#':>2} {'Player':<20} {'Mkt':<6} {'Book':<10} {'Odds':>6} {'Edge':>5} {'Stake':>5}")
    for i, c in enumerate(candidates, 1):
        if c.opponent_name:
            name = f"{c.player_name[:9]}v{c.opponent_name[:9]}"
        else:
            name = c.player_name[:20]

        mkt = c.market_type
        if c.round_number:
            mkt = f"R{c.round_number}H2H" if c.market_type != "3_ball" else f"R{c.round_number}3B"

        lines.append(
            f"{i:>2} {name:<20} {mkt:<6} {c.best_book:<10} "
            f"{c.best_odds_american:>6} {c.edge*100:>4.1f}% ${c.suggested_stake:>3.0f}"
        )

        # Split into multiple fields if too long
        if len("\n".join(lines)) > 900:
            embed.add_field(
                name="Candidates" if len(embed.fields) == 0 else "\u200b",
                value=f"```\n" + "\n".join(lines) + "\n```",
                inline=False,
            )
            lines = []

    if lines:
        embed.add_field(
            name="Candidates" if len(embed.fields) == 0 else "\u200b",
            value=f"```\n" + "\n".join(lines) + "\n```",
            inline=False,
        )

    embed.set_footer(text="Use /place <number> to log a bet")
    await interaction.followup.send(embed=embed)


def _run_pretournament_scan(tour: str):
    """Run pretournament scan (blocking — called via to_thread)."""
    bankroll = db.get_bankroll()
    existing_bets = db.get_open_bets_for_week()
    weekly_exposure = sum(b.get("stake", 0) for b in existing_bets)

    outrights = pull_all_outrights(None, tour)
    matchups = pull_tournament_matchups(None, tour)

    # Detect tournament
    tournament_name = "Unknown"
    tournament_id = None
    is_signature = False
    dg_event_id = None

    if outrights.get("win") and isinstance(outrights["win"], list) and outrights["win"]:
        first = outrights["win"][0]
        tournament_name = first.get("event_name", tournament_name)
        dg_event_id = str(first.get("event_id", "")) or None

    # Fallback: pull tournament name from DG field-updates API
    if tournament_name == "Unknown":
        try:
            from src.api.datagolf import DataGolfClient
            dg = DataGolfClient()
            field_resp = dg.get_field_updates(tour=tour)
            if field_resp["status"] == "ok":
                tournament_name = field_resp["data"].get("event_name", tournament_name)
        except Exception:
            pass

    season = datetime.now().year
    if dg_event_id:
        existing = db.get_tournament(dg_event_id, season)
        if existing:
            tournament_id = existing["id"]
            is_signature = existing.get("is_signature", False)
        else:
            t = db.upsert_tournament(
                tournament_name=tournament_name,
                start_date=datetime.now().strftime("%Y-%m-%d"),
                purse=0,
                dg_event_id=dg_event_id,
                season=season,
            )
            tournament_id = t.get("id")

    # Calculate edges
    all_candidates = []

    for dg_market, our_market in MARKET_MAP.items():
        data = outrights.get(dg_market, [])
        if not data:
            continue
        edges = calculate_placement_edges(
            data, our_market,
            is_signature=is_signature,
            bankroll=bankroll,
            existing_bets=existing_bets + [
                {"player_name": c.player_name, "opponent_name": c.opponent_name,
                 "opponent_2_name": c.opponent_2_name}
                for c in all_candidates
            ],
        )
        all_candidates.extend(edges)

    if matchups:
        edges = calculate_matchup_edges(
            matchups,
            is_signature=is_signature,
            bankroll=bankroll,
            existing_bets=existing_bets + [
                {"player_name": c.player_name, "opponent_name": c.opponent_name,
                 "opponent_2_name": c.opponent_2_name}
                for c in all_candidates
            ],
        )
        all_candidates.extend(edges)

    all_candidates.sort(key=lambda c: c.edge, reverse=True)

    if all_candidates:
        resolve_candidates(all_candidates, source="datagolf")

    tournament_exposure = sum(
        b.get("stake", 0) for b in existing_bets
        if b.get("tournament_id") == tournament_id
    )

    return (all_candidates, tournament_id, tournament_name,
            bankroll, weekly_exposure, tournament_exposure)


def _run_preround_scan(tour: str, round_number: int | None):
    """Run preround scan (blocking — called via to_thread)."""
    bankroll = db.get_bankroll()
    existing_bets = db.get_open_bets_for_week()
    weekly_exposure = sum(b.get("stake", 0) for b in existing_bets)

    # Detect active tournament
    tournament_id = None
    tournament_name = "Unknown"
    for b in sorted(existing_bets, key=lambda x: x.get("bet_timestamp", ""),
                    reverse=True):
        if b.get("tournament_id"):
            tournament_id = b["tournament_id"]
            break
    if tournament_id:
        t = db.get_tournament_by_id(tournament_id)
        if t:
            tournament_name = t.get("tournament_name", tournament_name)

    # Fallback: pull tournament name from DG field-updates API
    if tournament_name == "Unknown":
        try:
            from src.api.datagolf import DataGolfClient
            dg = DataGolfClient()
            field_resp = dg.get_field_updates(tour=tour)
            if field_resp["status"] == "ok":
                tournament_name = field_resp["data"].get("event_name", tournament_name)
        except Exception:
            pass

    round_matchups = pull_round_matchups(None, tour)
    three_balls = pull_3balls(None, tour)

    all_candidates = []

    if round_matchups:
        edges = calculate_matchup_edges(
            round_matchups, bankroll=bankroll,
            existing_bets=existing_bets,
            market_type="round_matchup",
        )
        for e in edges:
            e.round_number = round_number
        all_candidates.extend(edges)

    if three_balls:
        edges = calculate_3ball_edges(
            three_balls, bankroll=bankroll,
            existing_bets=existing_bets + [
                {"player_name": c.player_name, "opponent_name": c.opponent_name,
                 "opponent_2_name": c.opponent_2_name}
                for c in all_candidates
            ],
            round_number=round_number,
        )
        all_candidates.extend(edges)

    all_candidates.sort(key=lambda c: c.edge, reverse=True)

    if all_candidates:
        resolve_candidates(all_candidates, source="datagolf")

    tournament_exposure = sum(
        b.get("stake", 0) for b in existing_bets
        if b.get("tournament_id") == tournament_id
    ) if tournament_id else 0

    rnd_str = f" R{round_number}" if round_number else ""
    display_name = f"{tournament_name}{rnd_str}"

    return (all_candidates, tournament_id, display_name,
            bankroll, weekly_exposure, tournament_exposure)


# ---------------------------------------------------------------------------
# /place
# ---------------------------------------------------------------------------
@bot.tree.command(name="place", description="Log a bet from the last scan")
@app_commands.describe(
    number="Candidate number from the scan (e.g., 1)",
    odds="Actual odds placed (American, e.g., +450). Defaults to scanned odds.",
    stake="Override stake amount. Defaults to suggested stake.",
    notes="Optional notes",
)
async def cmd_place(
    interaction: discord.Interaction,
    number: int,
    odds: Optional[str] = None,
    stake: Optional[float] = None,
    notes: Optional[str] = None,
):
    await interaction.response.defer()

    if not bot.last_scan:
        await interaction.followup.send("No scan results cached. Run `/scan` first.")
        return

    idx = number - 1
    if idx < 0 or idx >= len(bot.last_scan):
        await interaction.followup.send(
            f"Invalid number. Last scan had {len(bot.last_scan)} candidates."
        )
        return

    c = bot.last_scan[idx]

    # Determine actual odds
    if odds:
        actual_decimal = american_to_decimal(odds)
        if actual_decimal is None:
            await interaction.followup.send(f"Invalid odds: {odds}")
            return
        actual_american = odds
    else:
        actual_decimal = c.best_odds_decimal
        actual_american = c.best_odds_american

    actual_implied = 1.0 / actual_decimal if actual_decimal > 0 else 0
    actual_edge = c.your_prob - actual_implied
    actual_stake = stake if stake is not None else c.suggested_stake

    # Warn if edge is gone
    if actual_edge <= 0:
        await interaction.followup.send(
            f"Edge is gone at {actual_american} "
            f"(implied {actual_implied*100:.1f}% vs your {c.your_prob*100:.1f}%). "
            f"Not logged."
        )
        return

    # Log the bet
    try:
        bet = await asyncio.to_thread(
            db.insert_bet,
            candidate_id=None,
            tournament_id=bot.last_scan_tournament_id,
            market_type=c.market_type,
            player_name=c.player_name,
            book=c.best_book,
            odds_at_bet_decimal=actual_decimal,
            odds_at_bet_american=actual_american,
            implied_prob_at_bet=actual_implied,
            your_prob=c.your_prob,
            edge=actual_edge,
            stake=actual_stake,
            scanned_odds_decimal=c.best_odds_decimal,
            player_id=c.player_id,
            opponent_name=c.opponent_name,
            opponent_id=c.opponent_id,
            opponent_2_name=c.opponent_2_name,
            opponent_2_id=c.opponent_2_id,
            round_number=c.round_number,
            correlation_haircut=c.correlation_haircut,
            notes=notes,
        )
    except Exception as e:
        await interaction.followup.send(f"Failed to log bet: {e}")
        return

    display = c.player_name
    if c.opponent_name:
        display = f"{c.player_name} vs {c.opponent_name}"

    bankroll = await asyncio.to_thread(db.get_bankroll)

    embed = discord.Embed(
        title="Bet Logged",
        color=0x2ECC71,
    )
    embed.add_field(name="Player", value=display, inline=True)
    embed.add_field(name="Market", value=c.market_type, inline=True)
    embed.add_field(name="Book", value=c.best_book, inline=True)
    embed.add_field(name="Odds", value=actual_american, inline=True)
    embed.add_field(name="Edge", value=f"{actual_edge*100:.1f}%", inline=True)
    embed.add_field(name="Stake", value=f"${actual_stake:,.0f}", inline=True)
    embed.add_field(name="Bankroll", value=f"${bankroll:,.2f}", inline=False)

    await interaction.followup.send(embed=embed)


# ---------------------------------------------------------------------------
# /live
# ---------------------------------------------------------------------------
@bot.tree.command(name="live", description="Live spot-check — DG probabilities during rounds")
@app_commands.describe(tour="Tour (default: pga)")
async def cmd_live(
    interaction: discord.Interaction,
    tour: Optional[str] = "pga",
):
    await interaction.response.defer()

    try:
        live_data = await asyncio.to_thread(pull_live_predictions, None, tour)
    except Exception as e:
        await interaction.followup.send(f"Live pull failed: {e}")
        return

    if not live_data:
        await interaction.followup.send(
            "No live data available (tournament may not be in progress)."
        )
        return

    bankroll = await asyncio.to_thread(db.get_bankroll)

    embed = discord.Embed(
        title="Live Spot-Check",
        description=(
            f"{len(live_data)} players in live model | "
            f"Edge threshold: {config.MIN_EDGE['live']*100:.0f}%\n"
            f"Bankroll: ${bankroll:,.2f}"
        ),
        color=0xE74C3C,
        timestamp=datetime.now(),
    )

    sorted_players = sorted(
        live_data,
        key=lambda p: p.get("top_20", p.get("t20", 0)) or 0,
        reverse=True,
    )

    lines = []
    lines.append(f"{'Player':<22} {'Win%':>5} {'T20%':>5} {'MC%':>5}")
    for player in sorted_players[:15]:
        name = player.get("player_name", "Unknown")[:22]
        win_pct = (player.get("win", 0) or 0) * 100
        t20_pct = (player.get("top_20", player.get("t20", 0)) or 0) * 100
        mc_pct = (player.get("make_cut", player.get("mc", 0)) or 0) * 100
        lines.append(f"{name:<22} {win_pct:>4.1f}% {t20_pct:>4.1f}% {mc_pct:>4.1f}%")

    embed.add_field(
        name="DG Live Probabilities (Top 15)",
        value=f"```\n" + "\n".join(lines) + "\n```",
        inline=False,
    )
    embed.set_footer(text="Compare vs current book lines. 8%+ edge to bet.")

    await interaction.followup.send(embed=embed)


# ---------------------------------------------------------------------------
# /player
# ---------------------------------------------------------------------------
@bot.tree.command(name="player", description="Look up a player's live position, scores & finish probabilities")
@app_commands.describe(
    name="Player name (e.g. Scottie Scheffler)",
    tour="Tour (default: pga)",
)
async def cmd_player(
    interaction: discord.Interaction,
    name: str,
    tour: Optional[str] = "pga",
):
    await interaction.response.defer()

    try:
        # Pull field updates (position, scores) and live predictions in parallel
        field_fut = asyncio.to_thread(_fetch_field, tour)
        live_fut = asyncio.to_thread(pull_live_predictions, None, tour)
        field_data, live_data = await asyncio.gather(field_fut, live_fut)
    except Exception as e:
        await interaction.followup.send(f"Data pull failed: {e}")
        return

    # Fuzzy-match player name against field
    from difflib import SequenceMatcher

    def _best_match(query: str, players: dict) -> tuple[str, dict] | None:
        query_lower = query.lower().strip()
        best_key, best_score = None, 0.0
        for key, info in players.items():
            score = SequenceMatcher(None, query_lower, key.lower()).ratio()
            if score > best_score:
                best_key, best_score = key, score
            # Also check display name
            score2 = SequenceMatcher(None, query_lower, info["name"].lower()).ratio()
            if score2 > best_score:
                best_key, best_score = key, score2
        if best_key and best_score >= 0.55:
            return best_key, players[best_key]
        return None

    match = _best_match(name, field_data["players"])
    if not match:
        await interaction.followup.send(f"Could not find **{name}** in the field.")
        return

    pkey, player = match

    # Find live probabilities for this player
    live_probs = {}
    if live_data:
        for p in live_data:
            pname = (p.get("player_name") or "").lower().strip()
            if SequenceMatcher(None, pkey.lower(), pname).ratio() >= 0.55:
                live_probs = p
                break

    # Build embed
    pos_display = player["pos_str"] or "—"
    status = player["status"]

    embed = discord.Embed(
        title=f"{player['name']}",
        description=f"**{field_data['event_name']}** — Round {field_data['current_round']}",
        color=0x3498DB,
        timestamp=datetime.now(),
    )

    # Position & scores
    rounds = []
    for rnd in ("r1", "r2", "r3", "r4"):
        val = player.get(rnd)
        if val is not None:
            rounds.append(f"R{rnd[1]}: {val}")
    total = player.get("total")
    total_str = f"{total:+d}" if isinstance(total, (int, float)) and total != 0 else str(total or "—")

    score_lines = f"**Position:** {pos_display}"
    if status not in ("active",):
        score_lines += f" ({status.upper()})"
    score_lines += f"\n**Overall:** {total_str}"
    if rounds:
        score_lines += f"\n{' | '.join(rounds)}"

    embed.add_field(name="Scoring", value=score_lines, inline=False)

    # Live probabilities
    if live_probs:
        prob_lines = []
        for label, keys in [
            ("Win", ["win"]),
            ("Top 5", ["top_5", "t5"]),
            ("Top 10", ["top_10", "t10"]),
            ("Top 20", ["top_20", "t20"]),
            ("Make Cut", ["make_cut", "mc"]),
        ]:
            val = None
            for k in keys:
                val = live_probs.get(k)
                if val is not None:
                    break
            if val is not None:
                prob_lines.append(f"**{label}:** {val * 100:.1f}%")
        if prob_lines:
            embed.add_field(
                name="Finish Probabilities (DG Live)",
                value="\n".join(prob_lines),
                inline=False,
            )
    else:
        embed.add_field(
            name="Finish Probabilities",
            value="No live model data available",
            inline=False,
        )

    await interaction.followup.send(embed=embed)


def _fetch_field(tour: str) -> dict:
    """Fetch field updates and return parsed dict."""
    from src.pipeline.pull_results import fetch_results
    return fetch_results(tour=tour)


# ---------------------------------------------------------------------------
# /settle
# ---------------------------------------------------------------------------
@bot.tree.command(name="settle", description="Auto-settle unsettled bets")
@app_commands.describe(
    tournament_id="Tournament UUID (optional — defaults to this week's bets)",
    tour="Tour (default: pga)",
)
async def cmd_settle(
    interaction: discord.Interaction,
    tournament_id: Optional[str] = None,
    tour: Optional[str] = "pga",
):
    await interaction.response.defer()

    try:
        result = await asyncio.to_thread(_run_settlement, tournament_id, tour)
    except Exception as e:
        await interaction.followup.send(f"Settlement failed: {e}")
        return

    bets, settled, skipped, total_pnl, bankroll = result

    if not bets:
        await interaction.followup.send("No unsettled bets found.")
        return

    embed = discord.Embed(
        title="Settlement Results",
        color=0x2ECC71 if total_pnl >= 0 else 0xE74C3C,
    )
    embed.add_field(name="Settled", value=str(len(settled)), inline=True)
    embed.add_field(name="Skipped", value=str(skipped), inline=True)
    embed.add_field(name="Session P&L", value=f"${total_pnl:+,.2f}", inline=True)
    embed.add_field(name="Bankroll", value=f"${bankroll:,.2f}", inline=False)

    if settled:
        lines = []
        for s in settled:
            emoji = "+" if s["pnl"] >= 0 else "-"
            name = s["player"][:18]
            lines.append(
                f"[{emoji}] {name:<18} {s['outcome']:<5} "
                f"${s['pnl']:>+7,.0f} {s['rule']}"
            )
        embed.add_field(
            name="Details",
            value=f"```\n" + "\n".join(lines) + "\n```",
            inline=False,
        )

    await interaction.followup.send(embed=embed)


def _run_settlement(tournament_id: str | None, tour: str):
    """Run auto-settlement (blocking)."""
    if tournament_id:
        bets = db.get_unsettled_bets(tournament_id)
    else:
        all_bets = db.get_open_bets_for_week()
        bets = [b for b in all_bets if b.get("outcome") is None]

    if not bets:
        return ([], [], 0, 0, db.get_bankroll())

    # Pull results
    results = None
    try:
        results = fetch_results(tour=tour)
        bets = match_bets_to_results(bets, results)
    except Exception:
        pass  # Will skip auto-settle for unmatched

    settled = []
    skipped = 0
    total_pnl = 0

    for bet in bets:
        pr = bet.get("player_result")
        if not pr or not bet.get("auto_settleable"):
            skipped += 1
            continue

        market = bet["market_type"]
        result = None

        if market in ("win", "t5", "t10", "t20", "make_cut"):
            result = _auto_settle_placement(bet, pr, results)
        elif market in ("tournament_matchup", "round_matchup"):
            or_ = bet.get("opponent_result")
            if or_:
                result = _auto_settle_matchup(bet, pr, or_)
        elif market == "3_ball":
            or_ = bet.get("opponent_result")
            o2r = bet.get("opponent_2_result")
            if or_ and o2r:
                result = _auto_settle_3ball(bet, pr, or_, o2r)

        if result is None:
            skipped += 1
            continue

        db.settle_bet(
            bet_id=bet["id"],
            outcome=result["outcome"],
            settlement_rule=result["settlement_rule"],
            payout=result["payout"],
            pnl=result["pnl"],
            actual_finish=result.get("actual_finish"),
            opponent_finish=result.get("opponent_finish"),
        )

        total_pnl += result["pnl"]
        settled.append({
            "player": bet["player_name"],
            "outcome": result["outcome"],
            "pnl": result["pnl"],
            "rule": result["settlement_rule"],
        })

    bankroll = db.get_bankroll()
    return (bets, settled, skipped, total_pnl, bankroll)


def _auto_settle_placement(bet, pr, results):
    """Auto-settle a placement bet."""
    market = bet["market_type"]
    threshold = {"win": 1, "t5": 5, "t10": 10, "t20": 20, "make_cut": 999}.get(market)
    if threshold is None:
        return None

    status = pr["status"]
    pos = pr["pos"]
    pos_str = pr["pos_str"]

    if status in ("wd", "dq"):
        rule = db.get_book_rule(bet["book"], market)
        wd_rule = rule.get("wd_rule", "void") if rule else "void"
        if wd_rule == "void":
            return {"outcome": "void", "settlement_rule": "void_wd",
                    "payout": round(bet["stake"], 2), "pnl": 0.0,
                    "actual_finish": status.upper()}
        else:
            return {"outcome": "loss", "settlement_rule": "wd_loss",
                    "payout": 0.0, "pnl": round(-bet["stake"], 2),
                    "actual_finish": status.upper()}

    if status == "cut":
        return {"outcome": "loss", "settlement_rule": "missed_cut",
                "payout": 0.0, "pnl": round(-bet["stake"], 2),
                "actual_finish": "MC"}

    if pos is None:
        return None

    if market == "make_cut":
        result = settle_placement_bet(pos, 999, bet["stake"], bet["odds_at_bet_decimal"])
        result["actual_finish"] = pos_str
        return result

    # Check for dead-heat at cutoff
    tied = 1
    if pos == threshold and pos_str and pos_str.startswith("T"):
        if results:
            count = 0
            for p in results["players"].values():
                if p["pos"] == threshold:
                    count += 1
            tied = count if count > 0 else 1
        else:
            return None  # Can't determine tie count

    rule = db.get_book_rule(bet["book"], market)
    tie_rule = rule.get("tie_rule", "dead_heat") if rule else "dead_heat"

    result = settle_placement_bet(
        pos, threshold, bet["stake"], bet["odds_at_bet_decimal"],
        tied_at_cutoff=tied, tie_rule=tie_rule,
    )
    result["actual_finish"] = pos_str
    return result


def _auto_settle_matchup(bet, pr, or_):
    """Auto-settle a matchup bet."""
    from src.core.settlement import settle_matchup_bet

    p_pos = pr["pos"] if pr["status"] == "active" else None
    o_pos = or_["pos"] if or_["status"] == "active" else None

    rule = db.get_book_rule(bet["book"], bet["market_type"])
    tie_rule = rule.get("tie_rule", "push") if rule else "push"
    wd_rule = rule.get("wd_rule", "void") if rule else "void"

    # Round matchups: compare round scores
    if bet["market_type"] == "round_matchup" and bet.get("round_number"):
        rnd_key = f"r{bet['round_number']}"
        p_score = pr.get(rnd_key) if pr["status"] not in ("wd", "dq") else None
        o_score = or_.get(rnd_key) if or_["status"] not in ("wd", "dq") else None

        if p_score is not None and o_score is not None:
            if p_score < o_score:
                payout = bet["stake"] * bet["odds_at_bet_decimal"]
                return {"outcome": "win", "settlement_rule": "standard",
                        "payout": round(payout, 2),
                        "pnl": round(payout - bet["stake"], 2),
                        "actual_finish": str(p_score),
                        "opponent_finish": str(o_score)}
            elif p_score > o_score:
                return {"outcome": "loss", "settlement_rule": "standard",
                        "payout": 0.0, "pnl": round(-bet["stake"], 2),
                        "actual_finish": str(p_score),
                        "opponent_finish": str(o_score)}
            else:
                if tie_rule == "push":
                    return {"outcome": "push", "settlement_rule": "push",
                            "payout": round(bet["stake"], 2), "pnl": 0.0,
                            "actual_finish": str(p_score),
                            "opponent_finish": str(o_score)}

    result = settle_matchup_bet(
        p_pos, o_pos, bet["stake"], bet["odds_at_bet_decimal"],
        tie_rule=tie_rule, wd_rule=wd_rule,
    )
    result["actual_finish"] = pr["pos_str"]
    result["opponent_finish"] = or_["pos_str"]
    return result


def _auto_settle_3ball(bet, pr, o1r, o2r):
    """Auto-settle a 3-ball bet."""
    from src.core.settlement import settle_3ball_bet

    rnd = bet.get("round_number")
    if not rnd:
        return None

    rnd_key = f"r{rnd}"
    p_score = pr.get(rnd_key) if pr["status"] not in ("wd", "dq") else None
    o1_score = o1r.get(rnd_key) if o1r["status"] not in ("wd", "dq") else None
    o2_score = o2r.get(rnd_key) if o2r["status"] not in ("wd", "dq") else None

    rule = db.get_book_rule(bet["book"], "3_ball")
    tie_rule = rule.get("tie_rule", "dead_heat") if rule else "dead_heat"
    wd_rule = rule.get("wd_rule", "void") if rule else "void"

    result = settle_3ball_bet(
        p_score, o1_score, o2_score,
        bet["stake"], bet["odds_at_bet_decimal"],
        tie_rule=tie_rule, wd_rule=wd_rule,
    )
    result["actual_finish"] = str(p_score) if p_score else "WD"
    result["opponent_finish"] = str(o1_score) if o1_score else "WD"
    return result


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def run():
    """Start the bot."""
    token = config.DISCORD_BOT_TOKEN
    if not token:
        raise ValueError("DISCORD_BOT_TOKEN not set in .env")

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )
    bot.run(token)
