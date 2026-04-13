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
    build_field_status_lookup,
    filter_stale_matchups,
)
from src.pipeline.pull_kalshi import (
    pull_kalshi_outrights, pull_kalshi_matchups,
    merge_kalshi_into_outrights, merge_kalshi_into_matchups,
)
from src.pipeline.pull_polymarket import (
    pull_polymarket_outrights,
    merge_polymarket_into_outrights,
)
from src.pipeline.pull_prophetx import (
    pull_prophetx_outrights, pull_prophetx_matchups,
    merge_prophetx_into_outrights, merge_prophetx_into_matchups,
)
from src.pipeline.pull_live import pull_live_predictions
from src.pipeline.pull_live_edges import pull_live_edges
from src.pipeline.pull_results import (
    fetch_results, fetch_archived_results, match_bets_to_results,
)
from src.core.arb import (
    detect_matchup_arbs, detect_3ball_arbs, format_arb_table, size_arb,
)
from src.core.settlement import settle_placement_bet
import config

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import tempfile

log = logging.getLogger("pga-ev-bot")


def _render_candidates_image(candidates, title: str, arbs=None) -> str:
    """Render candidate bets (and optional arbs) as a PNG table image.

    Returns the path to the saved PNG file.
    """
    # Build candidate table data
    cand_data = []
    for i, c in enumerate(candidates, 1):
        if c.opponent_name:
            name = f"{c.player_name.split(',')[0]} v {c.opponent_name.split(',')[0]}"
        else:
            name = c.player_name
        name = name[:34]

        mkt = c.market_type
        if c.round_number:
            mkt = f"R{c.round_number}H2H" if c.market_type != "3_ball" else f"R{c.round_number}3B"

        qualifies = getattr(c, "qualifies", True)
        bet_min = getattr(c, "bet_min_edge", 0.0)
        stake_str = f"${c.suggested_stake:.0f}" if qualifies else "—"

        cand_data.append([
            str(i), name, mkt[:8], c.best_book[:10],
            c.best_odds_american,
            f"{c.your_prob*100:.1f}%", f"{c.best_implied_prob*100:.1f}%",
            f"{c.edge*100:.1f}%", f"{bet_min*100:.0f}%", stake_str,
        ])

    # Build arb table data
    arb_data = []
    if arbs:
        for j, arb in enumerate(arbs, 1):
            size_arb(arb, config.ARB_DEFAULT_RETURN)
            total_outlay = sum(leg.stake for leg in arb.legs)
            profit = config.ARB_DEFAULT_RETURN - total_outlay
            names = " v ".join(leg.player.split(",")[0][:14] for leg in arb.legs)
            legs = " / ".join(f"{leg.book[:8]}" for leg in arb.legs)
            # Escape $ so matplotlib mathtext doesn't treat "$...$" as math mode
            stakes = " / ".join(f"\\${leg.stake:.2f}" for leg in arb.legs)
            warn = "*" if arb.settlement_warning else ""
            arb_data.append([
                str(j), names[:28], arb.market_type[:8], legs[:20],
                f"{arb.margin*100:.1f}%", stakes, f"${profit:.2f}{warn}",
            ])

    cand_columns = ["#", "Player", "Market", "Book", "Odds", "Model", "Book%", "Edge", "Min", "Stake"]
    cand_widths =  [0.04, 0.28,     0.08,     0.11,   0.08,   0.08,    0.08,    0.08,   0.06,  0.08]
    arb_columns = ["#", "Players", "Market", "Books", "Margin", "Stakes", "Profit"]
    arb_widths =  [0.04, 0.30,     0.10,     0.20,    0.08,     0.16,     0.12]

    # Calculate figure height
    n_cand = max(len(cand_data), 1)  # at least 1 row for "no candidates" message
    n_arb = len(arb_data)
    total_rows = n_cand + (n_arb + 2 if n_arb else 0)  # +2 for arb header gap
    fig_height = max(3, total_rows * 0.42 + 1.5)

    fig, axes = plt.subplots(
        nrows=2 if arb_data else 1, ncols=1,
        figsize=(10, fig_height),
        gridspec_kw={'height_ratios': [n_cand, n_arb + 1] if arb_data else [1]},
    )
    if not arb_data:
        axes = [axes]

    # --- Candidates table ---
    ax_cand = axes[0]
    ax_cand.axis('off')
    ax_cand.set_title(title, fontsize=13, fontweight='bold', pad=12, loc='left')

    if cand_data:
        table = ax_cand.table(cellText=cand_data, colLabels=cand_columns,
                              colWidths=cand_widths,
                              cellLoc='center', loc='center')
        table.auto_set_font_size(False)
        table.set_fontsize(8.5)
        table.scale(1, 1.35)

        edge_col = cand_columns.index("Edge")
        player_col = cand_columns.index("Player")

        for j in range(len(cand_columns)):
            table[0, j].set_facecolor('#2C3E50')
            table[0, j].set_text_props(color='white', fontweight='bold')

        for i in range(1, len(cand_data) + 1):
            bg = '#F8F9FA' if i % 2 == 0 else 'white'
            for j in range(len(cand_columns)):
                table[i, j].set_facecolor(bg)

            c = candidates[i - 1]
            qualifies = getattr(c, "qualifies", True)
            edge_val = float(cand_data[i - 1][edge_col].replace('%', ''))

            if not qualifies:
                # Sub-threshold: gold edge, dim the whole row so the user
                # clearly sees they don't clear the placement bar.
                table[i, edge_col].set_text_props(color='#F39C12', fontweight='bold')
                for j in range(len(cand_columns)):
                    if j != edge_col:
                        table[i, j].set_text_props(color='#7F8C8D')
            else:
                # Qualifies: green edge, deeper green for the high-alert tier.
                color = '#1E8449' if edge_val >= config.ALERT_HIGH_EDGE_THRESHOLD * 100 else '#27AE60'
                table[i, edge_col].set_text_props(color=color, fontweight='bold')

            table[i, player_col].set_text_props(ha='left')
            table[i, player_col]._loc = 'left'
        table[0, player_col]._loc = 'left'
    else:
        ax_cand.text(0.5, 0.4, "No +EV candidates above threshold",
                     ha='center', va='center', fontsize=12, color='#95A5A6',
                     transform=ax_cand.transAxes)

    # --- Arbs table ---
    if arb_data:
        ax_arb = axes[1]
        ax_arb.axis('off')
        ax_arb.set_title(f"{len(arb_data)} Arbitrage Opportunities",
                         fontsize=11, fontweight='bold', pad=8, loc='left')

        arb_table = ax_arb.table(cellText=arb_data, colLabels=arb_columns,
                                  colWidths=arb_widths,
                                  cellLoc='center', loc='center')
        arb_table.auto_set_font_size(False)
        arb_table.set_fontsize(8.5)
        arb_table.scale(1, 1.35)

        for j in range(len(arb_columns)):
            arb_table[0, j].set_facecolor('#8E44AD')
            arb_table[0, j].set_text_props(color='white', fontweight='bold')

        for i in range(1, len(arb_data) + 1):
            bg = '#F8F9FA' if i % 2 == 0 else 'white'
            for j in range(len(arb_columns)):
                arb_table[i, j].set_facecolor(bg)
            arb_table[i, 1].set_text_props(ha='left')
            arb_table[i, 1]._loc = 'left'
        arb_table[0, 1]._loc = 'left'

    plt.tight_layout()
    path = tempfile.mktemp(suffix='.png', prefix='ev_scan_')
    plt.savefig(path, dpi=150, bbox_inches='tight', facecolor='white', edgecolor='none')
    plt.close(fig)
    return path

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
        self._edge_gone_task: asyncio.Task | None = None
        self._live_monitor_task: asyncio.Task | None = None
        self._live_monitor_active: bool = False
        self._live_alerted_keys: set[str] = set()  # Avoid duplicate alerts
        # Edge-gone tracking: list of (candidate, channel_id, alert_time)
        self._alerted_candidates: list[tuple[CandidateBet, int, datetime]] = []
        # Tournament IDs for which we've already posted a summary
        self._summary_posted_for: set[str] = set()

    async def setup_hook(self):
        await self.tree.sync()
        log.info("Slash commands synced")
        if config.ALERT_ENABLED:
            self._alert_task = self.loop.create_task(self._scheduled_alerts())
            self._edge_gone_task = self.loop.create_task(self._edge_gone_loop())
            log.info("Scheduled alerts enabled (channel %s)", config.DISCORD_ALERT_CHANNEL_ID)

        # Auto-resume live monitoring on boot during tournament hours so a
        # restart (manual or auto-sync triggered) doesn't silently disable
        # the live scans the user was relying on.
        if getattr(config, "LIVE_MONITOR_AUTOSTART", False):
            self.loop.create_task(self._maybe_autostart_live_monitor())

    async def _maybe_autostart_live_monitor(self):
        """Start the live monitor if we're inside a tournament window.

        Tournament rounds run Thu-Sun (R1-R4), and the live monitor itself
        only acts between LIVE_MONITOR_START_HOUR and LIVE_MONITOR_END_HOUR
        ET — we mirror that gating here so we don't spawn a no-op task
        during off-hours / off-days.
        """
        await self.wait_until_ready()
        now_et = datetime.now(ET)
        weekday = now_et.weekday()  # 0=Mon … 6=Sun
        if weekday not in (3, 4, 5, 6):
            log.info("Live monitor autostart skipped: %s is not a tournament day",
                     now_et.strftime("%A"))
            return
        if now_et.hour < config.LIVE_MONITOR_START_HOUR or now_et.hour >= config.LIVE_MONITOR_END_HOUR:
            log.info("Live monitor autostart skipped: %s ET outside %d-%d window",
                     now_et.strftime("%H:%M"),
                     config.LIVE_MONITOR_START_HOUR, config.LIVE_MONITOR_END_HOUR)
            return
        round_number = weekday - 2  # Thu→1, Fri→2, Sat→3, Sun→4
        log.info("Live monitor autostart: R%d (%s ET)",
                 round_number, now_et.strftime("%H:%M"))
        await self.start_live_monitor(tour="pga", round_number=round_number)

    async def on_ready(self):
        log.info(f"Bot ready: {self.user} ({self.user.id})")

    # ------------------------------------------------------------------
    # Scheduled alert loop
    # ------------------------------------------------------------------
    async def _scheduled_alerts(self):
        """Background loop that fires scans at configured times."""
        await self.wait_until_ready()
        log.info("Alert scheduler started")

        # Track which scheduled tasks have fired today to prevent duplicates
        # and enable catch-up on restart
        fired_today: set[str] = set()  # e.g. {"preround_2026-04-11", "settlement_2026-04-11"}

        # Catch-up: if we start after the pre-round hour on a tournament day,
        # fire the scan immediately
        now_et = datetime.now(ET)
        weekday = now_et.weekday()
        if (weekday in (3, 4, 5, 6)
                and now_et.hour > config.ALERT_PREROUND_HOUR
                and now_et.hour < config.LIVE_MONITOR_END_HOUR):
            date_key = f"preround_{now_et.date()}"
            log.info("Catch-up: missed pre-round scan, running now")
            round_number = weekday - 2
            await self._run_and_alert("preround", round_number=round_number)
            fired_today.add(date_key)

        # Catch-up: on every startup, run settlement once. If the previous
        # scheduled Sun 10pm ET run was missed (bot down or restarted), this
        # is what closes out last week's tournament. Safe as a no-op when
        # there are no unsettled bets or the event hasn't finished yet —
        # _run_settlement just skips anything it can't match.
        try:
            log.info("Catch-up: running settlement sweep on startup")
            await self._run_scheduled_settlement()
        except Exception as e:
            log.error("Startup settlement catch-up failed: %s", e)

        while not self.is_closed():
            now_et = datetime.now(ET)
            weekday = now_et.weekday()  # 0=Mon … 6=Sun
            today = str(now_et.date())

            # Wednesday 6 PM ET → pre-tournament scan
            if weekday == 2 and now_et.hour == config.ALERT_PRETOURNAMENT_HOUR:
                key = f"pretournament_{today}"
                if key not in fired_today:
                    await self._run_and_alert("pretournament")
                    fired_today.add(key)

            # Thu(3)-Sun(6) at configured hour → pre-round scan
            if weekday in (3, 4, 5, 6) and now_et.hour == config.ALERT_PREROUND_HOUR:
                key = f"preround_{today}"
                if key not in fired_today:
                    round_number = weekday - 2  # Thu=R1, Fri=R2, Sat=R3, Sun=R4
                    await self._run_and_alert("preround", round_number=round_number)
                    fired_today.add(key)

            # Thu(3)-Sun(6) at 10 PM ET → auto-settlement
            if weekday in (3, 4, 5, 6) and now_et.hour == config.ALERT_SETTLEMENT_HOUR:
                key = f"settlement_{today}"
                if key not in fired_today:
                    await self._run_scheduled_settlement()
                    fired_today.add(key)

            # Sunday 8 PM ET → post-tournament summary
            if weekday == 6 and now_et.hour == 20:
                key = f"summary_{today}"
                if key not in fired_today:
                    if self.last_scan_tournament_id:
                        await self._post_tournament_summary(self.last_scan_tournament_id)
                    fired_today.add(key)

            # Clear old keys at midnight
            fired_today = {k for k in fired_today if today in k}

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

        if result is None:
            embed = discord.Embed(
                title=f"Scheduled Scan Skipped",
                description=(
                    "Tournament is live — DG baseline model not available.\n"
                    "Use `/monitor start` for live edge detection instead."
                ),
                color=0x95A5A6,
                timestamp=datetime.now(),
            )
            await channel.send(embed=embed)
            return

        # Unpack — arbs added in later versions, default to empty
        if len(result) == 7:
            candidates, tournament_id, tournament_name, bankroll, weekly_exp, tourn_exp, arbs = result
        else:
            candidates, tournament_id, tournament_name, bankroll, weekly_exp, tourn_exp = result
            arbs = []

        # Cache for /place
        self.last_scan = candidates
        self.last_scan_tournament_id = tournament_id
        self.last_scan_time = datetime.now()

        if not candidates and not arbs:
            embed = discord.Embed(
                title=f"Scheduled Scan — {tournament_name}",
                description="No +EV candidates or arbs found.",
                color=0x95A5A6,
                timestamp=datetime.now(),
            )
            await channel.send(embed=embed)
            return

        # Build the alert embed
        qualifying = [c for c in candidates if getattr(c, "qualifies", True)]
        sub_threshold = len(candidates) - len(qualifying)
        high_edge = [c for c in qualifying if c.edge >= config.ALERT_HIGH_EDGE_THRESHOLD]
        color = 0xE74C3C if high_edge else (0xE67E22 if qualifying else 0x95A5A6)

        weekly_limit = bankroll * config.MAX_WEEKLY_EXPOSURE_PCT
        tourn_limit = bankroll * config.MAX_TOURNAMENT_EXPOSURE_PCT

        sub_text = f", {sub_threshold} info-only" if sub_threshold else ""
        embed = discord.Embed(
            title=f"Scheduled Scan — {tournament_name}",
            description=(
                f"**{len(qualifying)}** bet-threshold candidates"
                f" ({len(high_edge)} high-edge{sub_text})\n"
                f"✓ clears market min edge · sub-threshold shown ≥"
                f"{config.DISPLAY_MIN_EDGE*100:.0f}% for visibility\n"
                f"Bankroll: ${bankroll:,.2f} | "
                f"Weekly: ${weekly_exp:,.0f}/${weekly_limit:,.0f} | "
                f"Tournament: ${tourn_exp:,.0f}/${tourn_limit:,.0f}"
            ),
            color=color,
            timestamp=datetime.now(),
        )

        # Render candidates as image
        img_path = await asyncio.to_thread(
            _render_candidates_image, candidates,
            f"Scheduled Scan — {tournament_name}", arbs,
        )
        img_file = discord.File(img_path, filename="scan_results.png")
        embed.set_image(url="attachment://scan_results.png")

        # Arbitrage section
        if arbs:
            arb_lines = [f"{len(arbs)} cross-book arb(s):"]
            for j, arb in enumerate(arbs, 1):
                size_arb(arb, config.ARB_DEFAULT_RETURN)
                total_outlay = sum(leg.stake for leg in arb.legs)
                profit = config.ARB_DEFAULT_RETURN - total_outlay
                legs_str = " + ".join(
                    f"{leg.player.split(',')[0][:10]}@{leg.book[:6]}"
                    f"({leg.odds_decimal:.2f})${leg.stake:.0f}"
                    for leg in arb.legs
                )
                warn = " *" if arb.settlement_warning else ""
                arb_lines.append(
                    f"{j}. {legs_str} = {arb.margin*100:.1f}% "
                    f"${profit:.2f}{warn}"
                )
            arb_text = "\n".join(arb_lines)
            if len(arb_text) > 1000:
                arb_text = arb_text[:997] + "..."
            embed.add_field(
                name="Arbitrage",
                value=f"```\n{arb_text}\n```",
                inline=False,
            )

        embed.set_footer(text="Use /place <number> to log a bet")

        # Mention role for high-edge alerts
        mention = ""
        if high_edge and config.DISCORD_ALERT_ROLE_ID:
            mention = f"<@&{config.DISCORD_ALERT_ROLE_ID}> "

        await channel.send(
            content=f"{mention}{len(high_edge)} high-edge bet(s) found!" if mention else None,
            embed=embed, file=img_file,
        )

        # Track for edge-gone re-check (qualifying candidates only)
        now = datetime.now()
        for c in qualifying:
            self._alerted_candidates.append((c, channel.id, now))

    # ------------------------------------------------------------------
    # Edge-gone re-check loop
    # ------------------------------------------------------------------
    async def _edge_gone_loop(self):
        """Periodically re-check alerted edges and notify if they've moved."""
        await self.wait_until_ready()
        log.info("Edge-gone checker started")

        while not self.is_closed():
            await asyncio.sleep(30 * 60)  # Check every 30 minutes

            if not self._alerted_candidates:
                continue

            # Only re-check candidates from the last 12 hours
            cutoff = datetime.now() - timedelta(hours=12)
            active = [(c, ch_id, t) for c, ch_id, t in self._alerted_candidates
                      if t > cutoff]
            self._alerted_candidates = active

            if not active:
                continue

            try:
                result = await asyncio.to_thread(_run_pretournament_scan, "pga")
            except Exception as e:
                log.error("Edge-gone re-check failed: %s", e)
                continue

            if result is None:
                # Tournament is live — skip re-check
                continue

            fresh_candidates, *_ = result

            # Build lookup of fresh candidates by player+market+book
            fresh_lookup: dict[str, CandidateBet] = {}
            for fc in fresh_candidates:
                key = f"{fc.player_name}|{fc.market_type}|{fc.best_book}"
                fresh_lookup[key] = fc

            # Find edges that are gone or significantly reduced
            gone: list[tuple[CandidateBet, str]] = []
            seen_keys: set[str] = set()

            for c, ch_id, alert_time in active:
                key = f"{c.player_name}|{c.market_type}|{c.best_book}"
                if key in seen_keys:
                    continue
                seen_keys.add(key)

                fresh = fresh_lookup.get(key)
                if fresh is None:
                    gone.append((c, "edge gone"))
                elif fresh.edge < c.edge * 0.5:
                    gone.append((c, f"edge shrunk {c.edge*100:.1f}% -> {fresh.edge*100:.1f}%"))

            if not gone:
                continue

            # Post edge-gone alert to the first channel we alerted
            ch_id = active[0][1]
            channel = self.get_channel(ch_id)
            if not channel:
                continue

            embed = discord.Embed(
                title="Edge Movement Alert",
                description=f"**{len(gone)}** previously-alerted edge(s) have moved",
                color=0x95A5A6,
                timestamp=datetime.now(),
            )

            lines = []
            for c, reason in gone[:10]:
                name = c.player_name[:20]
                lines.append(f"{name:<20} {c.market_type:<6} {c.best_book:<10} {reason}")
            embed.add_field(
                name="Details",
                value=f"```\n" + "\n".join(lines) + "\n```",
                inline=False,
            )
            embed.set_footer(text="Re-check odds before placing")

            await channel.send(embed=embed)

            # Remove gone edges from tracking
            gone_keys = {f"{c.player_name}|{c.market_type}|{c.best_book}" for c, _ in gone}
            self._alerted_candidates = [
                (c, ch_id, t) for c, ch_id, t in self._alerted_candidates
                if f"{c.player_name}|{c.market_type}|{c.best_book}" not in gone_keys
            ]

    # ------------------------------------------------------------------
    # Post-tournament summary
    # ------------------------------------------------------------------
    async def _post_tournament_summary(self, tournament_id: str, channel=None):
        """Post a tournament performance recap if all bets are settled."""
        if tournament_id in self._summary_posted_for:
            return

        if channel is None:
            channel = self.get_channel(config.DISCORD_ALERT_CHANNEL_ID)
        if not channel:
            return

        try:
            embed = await asyncio.to_thread(_build_tournament_summary, tournament_id)
        except Exception as e:
            log.error("Tournament summary failed: %s", e)
            return

        if embed is None:
            return  # Not fully settled yet or no bets

        await channel.send(embed=embed)
        self._summary_posted_for.add(tournament_id)
        log.info("Posted tournament summary for %s", tournament_id)

    # ------------------------------------------------------------------
    # Scheduled settlement
    # ------------------------------------------------------------------
    async def _run_scheduled_settlement(self, channel=None):
        """Run auto-settlement and post results to alert channel."""
        if channel is None:
            channel = self.get_channel(config.DISCORD_ALERT_CHANNEL_ID)
        if not channel:
            return

        log.info("Running scheduled settlement")
        try:
            result = await asyncio.to_thread(
                _run_settlement, self.last_scan_tournament_id, "pga"
            )
        except Exception as e:
            log.error("Scheduled settlement failed: %s", e)
            await channel.send(f"Scheduled settlement failed: {e}")
            return

        bets, settled, skipped, total_pnl, bankroll = result

        if not bets:
            await channel.send(
                embed=discord.Embed(
                    title="Scheduled Settlement",
                    description="No unsettled bets found.",
                    color=0x95A5A6,
                    timestamp=datetime.now(),
                )
            )
            return

        embed = discord.Embed(
            title="Scheduled Settlement",
            color=0x2ECC71 if total_pnl >= 0 else 0xE74C3C,
            timestamp=datetime.now(),
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

        await channel.send(embed=embed)
        log.info("Settlement: %d settled, %d skipped, P&L $%.2f",
                 len(settled), skipped, total_pnl)

        # Trigger tournament summary if all bets now settled
        tid = self.last_scan_tournament_id
        if tid:
            await self._post_tournament_summary(tid, channel=channel)

    # ------------------------------------------------------------------
    # Live round monitoring
    # ------------------------------------------------------------------
    async def start_live_monitor(self, channel=None, tour: str = "pga",
                                  round_number: int | None = None):
        """Start the live monitoring loop."""
        if self._live_monitor_active:
            return False  # Already running
        self._live_monitor_active = True
        self._live_alerted_keys.clear()
        self._live_monitor_task = self.loop.create_task(
            self._live_monitor_loop(channel, tour, round_number)
        )
        log.info("Live monitor started (R%s)", round_number or "?")
        return True

    async def stop_live_monitor(self):
        """Stop the live monitoring loop."""
        self._live_monitor_active = False
        if self._live_monitor_task and not self._live_monitor_task.done():
            self._live_monitor_task.cancel()
        self._live_alerted_keys.clear()
        log.info("Live monitor stopped")

    async def _live_monitor_loop(self, channel, tour: str, round_number: int | None):
        """Poll for live edges at configured interval.

        Posts a heartbeat scan image to the channel every cycle during
        tournament hours so it's obvious the monitor is still alive — even
        when there are no new qualifying edges. Role mentions still only
        fire on *new* high-edge qualifying candidates.
        """
        await self.wait_until_ready()

        if channel is None:
            channel = self.get_channel(config.DISCORD_ALERT_CHANNEL_ID)
        if not channel:
            log.warning("No channel for live monitor")
            self._live_monitor_active = False
            return

        interval = config.LIVE_MONITOR_INTERVAL_MIN * 60

        while self._live_monitor_active and not self.is_closed():
            now_et = datetime.now(ET)

            # Only run during tournament hours — stay silent overnight.
            if now_et.hour < config.LIVE_MONITOR_START_HOUR or now_et.hour >= config.LIVE_MONITOR_END_HOUR:
                log.info("Live monitor outside hours (%s ET), sleeping", now_et.strftime("%H:%M"))
                await asyncio.sleep(interval)
                continue

            try:
                candidates, tournament_name, stats = await asyncio.to_thread(
                    pull_live_edges, tour=tour, round_number=round_number,
                )
            except Exception as e:
                log.error("Live monitor scan failed: %s", e)
                try:
                    await channel.send(
                        f":warning: Live monitor scan failed: "
                        f"`{type(e).__name__}: {str(e)[:200]}` "
                        f"(retry in {config.LIVE_MONITOR_INTERVAL_MIN}min)"
                    )
                except Exception:
                    pass
                await asyncio.sleep(interval)
                continue

            if candidates:
                db.persist_candidates(
                    candidates, stats.get("tournament_id"), "live",
                )

            # Identify NEW qualifying edges. Sub-threshold rows still appear
            # in the image but never gate the role mention.
            new_qualifying = []
            for c in candidates:
                if not getattr(c, "qualifies", True):
                    continue
                key = f"{c.player_name}|{c.market_type}|{c.best_book}"
                if key not in self._live_alerted_keys:
                    self._live_alerted_keys.add(key)
                    new_qualifying.append(c)

            # Cache every cycle so /place always sees the latest scan,
            # not just the last one with new edges.
            self.last_scan = candidates
            self.last_scan_tournament_id = stats.get("tournament_id")
            self.last_scan_time = datetime.now()

            high_edge = [c for c in new_qualifying if c.edge >= config.ALERT_HIGH_EDGE_THRESHOLD]
            qualifying_total = sum(1 for c in candidates if getattr(c, "qualifies", True))
            sub_threshold = sum(1 for c in candidates if not getattr(c, "qualifies", True))

            if high_edge:
                color = 0xE74C3C   # red — new high-edge
                heading = f"LIVE Edge Alert — {tournament_name}"
                desc_lead = (f"**{len(new_qualifying)}** new bet-threshold edge(s)"
                             f" ({len(high_edge)} high-edge)")
            elif new_qualifying:
                color = 0xF39C12   # orange — new normal
                heading = f"LIVE Edge Alert — {tournament_name}"
                desc_lead = f"**{len(new_qualifying)}** new bet-threshold edge(s)"
            else:
                color = 0x5865F2   # blurple — heartbeat, no new edges
                heading = f"LIVE Scan — {tournament_name}"
                desc_lead = (
                    f"No new edges this cycle · {qualifying_total} qualifying tracked"
                    if qualifying_total else "No qualifying edges this cycle"
                )

            sub_text = f" · {sub_threshold} info-only" if sub_threshold else ""
            embed = discord.Embed(
                title=heading,
                description=(
                    f"{desc_lead}{sub_text}\n"
                    f"DG live model: {stats.get('live_players', '?')} players | "
                    f"Matched: {stats.get('matched', '?')}\n"
                    f"Bankroll: ${stats.get('bankroll', 0):,.2f}"
                ),
                color=color,
                timestamp=datetime.now(),
            )

            img_path = await asyncio.to_thread(
                _render_candidates_image, candidates, heading,
            )
            img_file = discord.File(img_path, filename="live_edges.png")
            embed.set_image(url="attachment://live_edges.png")
            embed.set_footer(
                text=f"Next check in {config.LIVE_MONITOR_INTERVAL_MIN}min · /monitor stop to disable"
            )

            content = None
            if high_edge and config.DISCORD_ALERT_ROLE_ID:
                content = f"<@&{config.DISCORD_ALERT_ROLE_ID}> LIVE: {len(new_qualifying)} new edge(s)!"

            try:
                await channel.send(content=content, embed=embed, file=img_file)
            except Exception as e:
                log.error("Live monitor send failed: %s", e)

            await asyncio.sleep(interval)

        self._live_monitor_active = False


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
# /monitor — live round monitoring
# ---------------------------------------------------------------------------
@bot.tree.command(name="monitor", description="Start/stop live round monitoring")
@app_commands.describe(
    action="Start or stop live monitoring",
    round_number="Current round number (1-4)",
    tour="Tour (default: pga)",
)
@app_commands.choices(action=[
    app_commands.Choice(name="Start monitoring", value="start"),
    app_commands.Choice(name="Stop monitoring", value="stop"),
    app_commands.Choice(name="Run one live scan now", value="once"),
    app_commands.Choice(name="Show monitor status", value="status"),
])
async def cmd_monitor(
    interaction: discord.Interaction,
    action: app_commands.Choice[str],
    round_number: Optional[int] = None,
    tour: Optional[str] = "pga",
):
    await interaction.response.defer()

    if action.value == "status":
        status_lines = [
            f"**Active:** {bot._live_monitor_active}",
            f"**Interval:** {config.LIVE_MONITOR_INTERVAL_MIN} min",
            f"**Hours:** {config.LIVE_MONITOR_START_HOUR}:00-{config.LIVE_MONITOR_END_HOUR}:00 ET",
            f"**Alerted edges this session:** {len(bot._live_alerted_keys)}",
        ]
        if bot.last_scan_time:
            status_lines.append(
                f"**Last scan:** {bot.last_scan_time.strftime('%H:%M')} "
                f"({len(bot.last_scan)} candidates)"
            )
        embed = discord.Embed(
            title="Live Monitor Status",
            description="\n".join(status_lines),
            color=0x2ECC71 if bot._live_monitor_active else 0x95A5A6,
        )
        await interaction.followup.send(embed=embed)
        return

    if action.value == "stop":
        if not bot._live_monitor_active:
            await interaction.followup.send("Live monitor is not running.")
            return
        await bot.stop_live_monitor()
        await interaction.followup.send("Live monitor stopped.")
        return

    if action.value == "start":
        if bot._live_monitor_active:
            await interaction.followup.send("Live monitor is already running.")
            return
        started = await bot.start_live_monitor(
            channel=interaction.channel,
            tour=tour,
            round_number=round_number,
        )
        if started:
            await interaction.followup.send(
                f"Live monitor started — scanning every "
                f"{config.LIVE_MONITOR_INTERVAL_MIN} min "
                f"(R{round_number or '?'}, {config.LIVE_MONITOR_START_HOUR}:00-"
                f"{config.LIVE_MONITOR_END_HOUR}:00 ET). "
                f"Use `/monitor stop` to stop."
            )
        return

    if action.value == "once":
        await interaction.followup.send("Running one-time live edge scan...")
        try:
            candidates, tournament_name, stats = await asyncio.to_thread(
                pull_live_edges, tour=tour, round_number=round_number,
            )
        except Exception as e:
            await interaction.followup.send(f"Live scan failed: {e}")
            return

        if not candidates:
            embed = discord.Embed(
                title=f"Live Scan — {tournament_name}",
                description=(
                    f"No live edges found.\n"
                    f"DG live model: {stats.get('live_players', 0)} players | "
                    f"Matched to books: {stats.get('matched', 0)}"
                ),
                color=0x95A5A6,
                timestamp=datetime.now(),
            )
            await interaction.followup.send(embed=embed)
            return

        db.persist_candidates(candidates, stats.get("tournament_id"), "live")

        # Cache for /place
        bot.last_scan = candidates
        bot.last_scan_tournament_id = stats.get("tournament_id")
        bot.last_scan_time = datetime.now()

        qualifying = [c for c in candidates if getattr(c, "qualifies", True)]
        sub_threshold = len(candidates) - len(qualifying)
        high_edge = [c for c in qualifying if c.edge >= config.ALERT_HIGH_EDGE_THRESHOLD]

        bankroll = stats.get("bankroll", 0)
        sub_text = f", {sub_threshold} info-only" if sub_threshold else ""
        embed = discord.Embed(
            title=f"Live Scan — {tournament_name}",
            description=(
                f"**{len(qualifying)}** bet-threshold edges"
                f" ({len(high_edge)} high-edge{sub_text})\n"
                f"✓ clears market min edge · sub-threshold shown ≥"
                f"{config.DISPLAY_MIN_EDGE*100:.0f}% for visibility\n"
                f"DG live: {stats.get('live_players', 0)} players | "
                f"Matched: {stats.get('matched', 0)} | "
                f"Bankroll: ${bankroll:,.2f}"
            ),
            color=0xE67E22,
            timestamp=datetime.now(),
        )

        img_path = await asyncio.to_thread(
            _render_candidates_image, candidates,
            f"Live Scan — {tournament_name}",
        )
        img_file = discord.File(img_path, filename="live_scan.png")
        embed.set_image(url="attachment://live_scan.png")

        embed.set_footer(text="Use /place <number> to log a bet | VERIFY ODDS BEFORE PLACING")
        await interaction.followup.send(embed=embed, file=img_file)


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

    if result is None:
        await interaction.followup.send(
            "Tournament is live — DG baseline model not available. "
            "Use `/monitor once` for a live edge scan instead."
        )
        return

    # Unpack — arbs added in later versions, default to empty
    if len(result) == 7:
        candidates, tournament_id, tournament_name, bankroll, weekly_exp, tourn_exp, arbs = result
    else:
        candidates, tournament_id, tournament_name, bankroll, weekly_exp, tourn_exp = result
        arbs = []

    # Cache for /place
    bot.last_scan = candidates
    bot.last_scan_tournament_id = tournament_id
    bot.last_scan_time = datetime.now()

    if not candidates and not arbs:
        embed = discord.Embed(
            title=f"Scan — {tournament_name}",
            description="No +EV candidates or arbs found.",
            color=0x95A5A6,
        )
        await interaction.followup.send(embed=embed)
        return

    weekly_limit = bankroll * config.MAX_WEEKLY_EXPOSURE_PCT
    tourn_limit = bankroll * config.MAX_TOURNAMENT_EXPOSURE_PCT

    qualifying = [c for c in candidates if getattr(c, "qualifies", True)]
    sub_threshold = len(candidates) - len(qualifying)
    high_edge = [c for c in qualifying if c.edge >= config.ALERT_HIGH_EDGE_THRESHOLD]

    desc_parts = []
    if candidates:
        sub_text = f", {sub_threshold} info-only" if sub_threshold else ""
        desc_parts.append(
            f"**{len(qualifying)}** bet-threshold candidates"
            f" ({len(high_edge)} high-edge{sub_text})"
        )
        desc_parts.append(
            f"✓ clears market min edge · sub-threshold shown ≥"
            f"{config.DISPLAY_MIN_EDGE*100:.0f}% for visibility"
        )
    if arbs:
        desc_parts.append(f"**{len(arbs)}** arb(s)")
    desc_parts.append(
        f"Bankroll: ${bankroll:,.2f} | "
        f"Weekly: ${weekly_exp:,.0f}/${weekly_limit:,.0f} | "
        f"Tournament: ${tourn_exp:,.0f}/${tourn_limit:,.0f}"
    )

    embed = discord.Embed(
        title=f"Scan — {tournament_name}",
        description="\n".join(desc_parts),
        color=0xE67E22,
        timestamp=datetime.now(),
    )

    file_to_send = None
    if candidates or arbs:
        img_path = await asyncio.to_thread(
            _render_candidates_image, candidates,
            f"Scan — {tournament_name}", arbs,
        )
        file_to_send = discord.File(img_path, filename="scan_results.png")
        embed.set_image(url="attachment://scan_results.png")

    embed.set_footer(text="Use /place <number> to log a bet")
    await interaction.followup.send(embed=embed, file=file_to_send)


def _run_pretournament_scan(tour: str):
    """Run pretournament scan (blocking — called via to_thread).

    Returns None if the tournament is live (stale odds guard).
    Otherwise returns (candidates, tournament_id, tournament_name,
                       bankroll, weekly_exposure, tournament_exposure).
    """
    bankroll = db.get_bankroll()
    existing_bets = db.get_open_bets_for_week()
    weekly_exposure = sum(b.get("stake", 0) for b in existing_bets)

    outrights = pull_all_outrights(None, tour)

    # Staleness guard: abort if DG says the tournament is live
    if outrights.get("_is_live"):
        log.warning("Pre-tournament scan aborted: tournament is live (%s)",
                     outrights.get("_notes", ""))
        return None

    matchups = pull_tournament_matchups(None, tour)

    # Detect tournament
    tournament_name = outrights.get("_event_name", "Unknown")
    tournament_id = None
    is_signature = False
    dg_event_id = None

    if tournament_name == "Unknown":
        # Fallback: try first player record or field-updates API
        if outrights.get("win") and isinstance(outrights["win"], list) and outrights["win"]:
            first = outrights["win"][0]
            tournament_name = first.get("event_name", tournament_name)
            dg_event_id = str(first.get("event_id", "")) or None
    if tournament_name == "Unknown":
        try:
            from src.api.datagolf import DataGolfClient
            dg = DataGolfClient()
            field_resp = dg.get_field_updates(tour=tour)
            if field_resp["status"] == "ok":
                tournament_name = field_resp["data"].get("event_name", tournament_name)
        except Exception:
            pass

    # Resolve DG event ID for DB lookup
    if not dg_event_id and tournament_name != "Unknown":
        try:
            from src.api.datagolf import DataGolfClient
            dg_event_id = DataGolfClient().resolve_event_id(tournament_name, tour)
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

    # Date range for prediction market matching
    today = datetime.now().strftime("%Y-%m-%d")
    end_date = (datetime.now() + timedelta(days=4)).strftime("%Y-%m-%d")

    # Pull and merge Kalshi odds
    try:
        if tournament_name != "Unknown":
            kalshi_outrights = pull_kalshi_outrights(
                tournament_name, today, end_date)
            if any(len(v) > 0 for v in kalshi_outrights.values()):
                merge_kalshi_into_outrights(outrights, kalshi_outrights)
            kalshi_matchup_data = pull_kalshi_matchups(
                tournament_name, today, end_date)
            if kalshi_matchup_data:
                merge_kalshi_into_matchups(matchups, kalshi_matchup_data)
    except Exception as e:
        log.warning("Kalshi unavailable: %s", e)

    # Pull and merge Polymarket odds
    if config.POLYMARKET_ENABLED:
        try:
            poly_outrights = pull_polymarket_outrights(
                tournament_name, today, end_date)
            if any(len(v) > 0 for v in poly_outrights.values()):
                merge_polymarket_into_outrights(outrights, poly_outrights)
        except Exception as e:
            log.warning("Polymarket unavailable: %s", e)

    # Pull and merge ProphetX odds
    if config.PROPHETX_ENABLED:
        try:
            px_outrights = pull_prophetx_outrights(
                tournament_name, today, end_date)
            if any(len(v) > 0 for v in px_outrights.values()):
                merge_prophetx_into_outrights(outrights, px_outrights)
            px_matchups = pull_prophetx_matchups(
                tournament_name, today, end_date)
            if px_matchups:
                merge_prophetx_into_matchups(matchups, px_matchups)
        except Exception as e:
            log.warning("ProphetX unavailable: %s", e)

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
            win_outrights_data=outrights.get("win"),
            display_min_edge=config.DISPLAY_MIN_EDGE,
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
            outrights_data=outrights.get("win"),
            display_min_edge=config.DISPLAY_MIN_EDGE,
        )
        all_candidates.extend(edges)

    all_candidates.sort(key=lambda c: c.edge, reverse=True)

    if all_candidates:
        resolve_candidates(all_candidates, source="datagolf")
        db.persist_candidates(all_candidates, tournament_id, "pretournament")

    # Arbitrage scan on matchups
    arbs = detect_matchup_arbs(matchups, market_type="tournament_matchup") if matchups else []

    tournament_exposure = sum(
        b.get("stake", 0) for b in existing_bets
        if b.get("tournament_id") == tournament_id
    )

    return (all_candidates, tournament_id, tournament_name,
            bankroll, weekly_exposure, tournament_exposure, arbs)


def _build_tournament_summary(tournament_id: str) -> discord.Embed | None:
    """Build a post-tournament performance recap embed.

    Returns None if the tournament has no bets or is not fully settled yet.
    Blocking — call via asyncio.to_thread.
    """
    bets = db.get_bets_for_tournament(tournament_id)
    if not bets:
        return None

    # All bets must be settled
    if any(b.get("outcome") is None for b in bets):
        return None

    # Tournament name
    tournament = db.get_tournament_by_id(tournament_id)
    name = tournament.get("tournament_name", "Unknown") if tournament else "Unknown"

    # --- Aggregates ---
    total_staked = sum(b.get("stake", 0) for b in bets)
    total_pnl = sum(b.get("pnl", 0) for b in bets)
    roi = (total_pnl / total_staked * 100) if total_staked > 0 else 0.0

    # Win-Loss-Push record
    wins = sum(1 for b in bets if b.get("outcome") in ("win", "half_win"))
    losses = sum(1 for b in bets if b.get("outcome") in ("loss", "half_loss"))
    pushes = len(bets) - wins - losses

    # By market type
    by_market: dict[str, dict] = {}
    for b in bets:
        mt = b.get("market_type", "other")
        entry = by_market.setdefault(mt, {"count": 0, "pnl": 0.0, "w": 0, "l": 0})
        entry["count"] += 1
        entry["pnl"] += b.get("pnl", 0)
        if b.get("outcome") in ("win", "half_win"):
            entry["w"] += 1
        elif b.get("outcome") in ("loss", "half_loss"):
            entry["l"] += 1

    # By book
    by_book: dict[str, dict] = {}
    for b in bets:
        book = b.get("book", "unknown")
        entry = by_book.setdefault(book, {"count": 0, "pnl": 0.0})
        entry["count"] += 1
        entry["pnl"] += b.get("pnl", 0)

    # Edge calibration
    edges = [b.get("edge", 0) for b in bets if b.get("edge") is not None]
    avg_edge = sum(edges) / len(edges) * 100 if edges else 0.0
    clvs = [b.get("clv", 0) for b in bets if b.get("clv") is not None]
    avg_clv = sum(clvs) / len(clvs) * 100 if clvs else 0.0

    # Season totals
    roi_data = db.get_roi_by_market()
    season_bets = sum(r.get("total_bets", 0) for r in roi_data) if roi_data else 0
    season_staked = sum(r.get("total_staked", 0) for r in roi_data) if roi_data else 0
    season_pnl = sum(r.get("total_pnl", 0) for r in roi_data) if roi_data else 0
    season_roi = (season_pnl / season_staked * 100) if season_staked > 0 else 0.0
    bankroll = db.get_bankroll()

    # --- Build embed ---
    embed = discord.Embed(
        title=f"Tournament Recap \u2014 {name}",
        color=0x2ECC71 if total_pnl >= 0 else 0xE74C3C,
        timestamp=datetime.now(),
    )

    embed.add_field(name="P&L", value=f"${total_pnl:+,.2f}", inline=True)
    embed.add_field(name="ROI", value=f"{roi:+.1f}%", inline=True)
    record = f"{wins}-{losses}"
    if pushes:
        record += f"-{pushes}"
    embed.add_field(name="Record", value=f"{record} (W-L{'P' if pushes else ''})", inline=True)

    # By market table
    if by_market:
        lines = [f"{'Market':<14} {'Bets':>4} {'P&L':>9} {'W-L':>5}"]
        for mt, d in sorted(by_market.items(), key=lambda x: x[1]["pnl"], reverse=True):
            lines.append(
                f"{mt:<14} {d['count']:>4} ${d['pnl']:>+8,.0f} {d['w']}-{d['l']}"
            )
        embed.add_field(
            name="By Market",
            value=f"```\n" + "\n".join(lines) + "\n```",
            inline=False,
        )

    # By book table
    if by_book:
        lines = [f"{'Book':<14} {'Bets':>4} {'P&L':>9}"]
        for book, d in sorted(by_book.items(), key=lambda x: x[1]["pnl"], reverse=True):
            lines.append(f"{book:<14} {d['count']:>4} ${d['pnl']:>+8,.0f}")
        embed.add_field(
            name="By Book",
            value=f"```\n" + "\n".join(lines) + "\n```",
            inline=False,
        )

    # Edge calibration
    embed.add_field(
        name="Edge Calibration",
        value=f"Avg Edge: {avg_edge:.1f}%  |  Actual ROI: {roi:+.1f}%  |  Avg CLV: {avg_clv:+.1f}%",
        inline=False,
    )

    # Season footer
    embed.set_footer(
        text=(
            f"Season: {season_bets} bets | ${season_staked:,.0f} staked | "
            f"${season_pnl:+,.0f} P&L | {season_roi:+.1f}% ROI | "
            f"Bankroll: ${bankroll:,.2f}"
        ),
    )

    return embed


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

    # Drop matchups whose players have already teed off / been cut / WD'd.
    field_lookup = build_field_status_lookup(tour=tour)
    if round_matchups:
        round_matchups = filter_stale_matchups(round_matchups, field_lookup, n_players=2)
    if three_balls:
        three_balls = filter_stale_matchups(three_balls, field_lookup, n_players=3)

    all_candidates = []

    if round_matchups:
        edges = calculate_matchup_edges(
            round_matchups, bankroll=bankroll,
            existing_bets=existing_bets,
            market_type="round_matchup",
            display_min_edge=config.DISPLAY_MIN_EDGE,
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
            display_min_edge=config.DISPLAY_MIN_EDGE,
        )
        all_candidates.extend(edges)

    all_candidates.sort(key=lambda c: c.edge, reverse=True)

    if all_candidates:
        resolve_candidates(all_candidates, source="datagolf")
        db.persist_candidates(all_candidates, tournament_id, "preround")

    # Arbitrage scan
    arbs = []
    if round_matchups:
        arbs.extend(detect_matchup_arbs(
            round_matchups, market_type="round_matchup",
            round_number=round_number))
    if three_balls:
        arbs.extend(detect_3ball_arbs(three_balls, round_number=round_number))
    arbs.sort(key=lambda a: a.margin, reverse=True)

    tournament_exposure = sum(
        b.get("stake", 0) for b in existing_bets
        if b.get("tournament_id") == tournament_id
    ) if tournament_id else 0

    rnd_str = f" R{round_number}" if round_number else ""
    display_name = f"{tournament_name}{rnd_str}"

    return (all_candidates, tournament_id, display_name,
            bankroll, weekly_exposure, tournament_exposure, arbs)


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

    # Block sub-threshold candidates unless user overrides stake explicitly
    bet_min = getattr(c, "bet_min_edge", 0.0)
    if not getattr(c, "qualifies", True) and actual_edge < bet_min and stake is None:
        await interaction.followup.send(
            f"⚠️ Candidate #{number} is **info-only** (edge {actual_edge*100:.1f}% "
            f"< {c.market_type} bet threshold {bet_min*100:.0f}%). "
            f"No Kelly stake was computed. "
            f"If you still want to place it, re-run `/place {number} stake:<amount>`."
        )
        return

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
            candidate_id=getattr(c, "candidate_id", None),
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

    # Post tournament summary if all bets are now settled
    tid = tournament_id or bot.last_scan_tournament_id
    if tid:
        await bot._post_tournament_summary(tid, channel=interaction.channel)


def _results_for_tournament(tournament_id: str | None, tour: str) -> dict | None:
    """Resolve a results dict for a given tournament.

    Prefers the DG historical archive (authoritative once the event
    completes and still available after field-updates rolls to the
    next week). Falls back to live field-updates for in-progress
    tournaments. Returns None if neither path has usable data.
    """
    if tournament_id:
        t = db.get_tournament_by_id(tournament_id)
        if t and t.get("dg_event_id") and t.get("season"):
            archived = fetch_archived_results(
                event_id=t["dg_event_id"], year=t["season"], tour=tour,
            )
            if archived:
                return archived

    try:
        return fetch_results(tour=tour)
    except Exception:
        return None


def _run_settlement(tournament_id: str | None, tour: str):
    """Run auto-settlement (blocking).

    Groups unsettled bets by tournament so completed tournaments can
    settle against the historical archive even after the live DG event
    has rolled over to the next week.
    """
    if tournament_id:
        bets = db.get_unsettled_bets(tournament_id)
    else:
        all_bets = db.get_open_bets_for_week()
        bets = [b for b in all_bets if b.get("outcome") is None]

    if not bets:
        return ([], [], 0, 0, db.get_bankroll())

    from collections import defaultdict
    bets_by_tid: dict[str | None, list] = defaultdict(list)
    for b in bets:
        bets_by_tid[b.get("tournament_id")].append(b)

    all_bets_processed: list = []
    settled: list = []
    skipped = 0
    total_pnl = 0.0

    for tid, tbets in bets_by_tid.items():
        results = _results_for_tournament(tid, tour)
        if not results:
            skipped += len(tbets)
            all_bets_processed.extend(tbets)
            continue

        tbets = match_bets_to_results(tbets, results)
        all_bets_processed.extend(tbets)

        for bet in tbets:
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
    return (all_bets_processed, settled, skipped, total_pnl, bankroll)


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

    # Cut handling — settle_matchup_bet (via wd_rule) would void on a
    # None finish, which is wrong for cut players: making it to Friday
    # and missing the cut is a normal tournament result, not a WD.
    # A cut player loses the matchup to any active opponent.
    p_cut = pr["status"] == "cut"
    o_cut = or_["status"] == "cut"
    if p_cut or o_cut:
        if p_cut and o_cut:
            return {"outcome": "push", "settlement_rule": "both_missed_cut",
                    "payout": round(bet["stake"], 2), "pnl": 0.0,
                    "actual_finish": "MC", "opponent_finish": "MC"}
        if p_cut:
            return {"outcome": "loss", "settlement_rule": "missed_cut",
                    "payout": 0.0, "pnl": round(-bet["stake"], 2),
                    "actual_finish": "MC", "opponent_finish": or_["pos_str"]}
        payout = bet["stake"] * bet["odds_at_bet_decimal"]
        return {"outcome": "win", "settlement_rule": "opponent_missed_cut",
                "payout": round(payout, 2),
                "pnl": round(payout - bet["stake"], 2),
                "actual_finish": pr["pos_str"], "opponent_finish": "MC"}

    p_pos = pr["pos"] if pr["status"] == "active" else None
    o_pos = or_["pos"] if or_["status"] == "active" else None
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
# /coursefit
# ---------------------------------------------------------------------------
@bot.tree.command(name="coursefit",
                  description="Show a player's course-fit SG breakdown")
@app_commands.describe(
    player="Player name (e.g., Scheffler)",
    tournament="Tournament name override (default: current event)",
)
async def cmd_coursefit(
    interaction: discord.Interaction,
    player: str,
    tournament: Optional[str] = None,
):
    await interaction.response.defer()

    try:
        result = await asyncio.to_thread(
            _run_coursefit_lookup, player, tournament
        )
    except Exception as e:
        await interaction.followup.send(f"Course-fit lookup failed: {e}")
        return

    if isinstance(result, str):
        await interaction.followup.send(result)
        return

    embed = discord.Embed(
        title=f"Course-Fit: {result['player_name']}",
        description=result.get("conditions_desc", ""),
        color=0x2ECC71,
    )

    # Form window (ball-striking)
    form_parts = []
    for label, key in [("OTT", "sg_ott"), ("APP", "sg_app"), ("T2G", "sg_t2g")]:
        val = result.get(key)
        if val is not None:
            sign = "+" if val >= 0 else ""
            form_parts.append(f"SG:{label} {sign}{val:.2f}")
    form_rds = result.get("form_rounds", "?")
    embed.add_field(name=f"Form ({form_rds}r)",
                    value=" | ".join(form_parts) or "N/A", inline=False)

    # Baseline window (short game)
    base_parts = []
    for label, key in [("ARG", "sg_arg"), ("P", "sg_p")]:
        val = result.get(key)
        if val is not None:
            sign = "+" if val >= 0 else ""
            base_parts.append(f"SG:{label} {sign}{val:.2f}")
    base_rds = result.get("baseline_rounds", "?")
    embed.add_field(name=f"Baseline ({base_rds}r)",
                    value=" | ".join(base_parts) or "N/A", inline=False)

    comp = result.get("sg_composite")
    rank = result.get("sg_rank", "?")
    field = result.get("field_size", "?")
    if comp is not None:
        sign = "+" if comp >= 0 else ""
        embed.add_field(name="Weighted Composite",
                        value=f"{sign}{comp:.2f}", inline=True)
    embed.add_field(name="Field Rank", value=f"{rank}/{field}", inline=True)

    await interaction.followup.send(embed=embed)


def _run_coursefit_lookup(player_name: str, tournament_override: str | None):
    """Blocking coursefit lookup."""
    from src.core.coursefit import (
        pull_coursefit_data, match_betsperts_to_dg, _PROFILES, _normalize,
    )

    tournament = tournament_override
    if not tournament:
        outrights = pull_all_outrights(tour="pga")
        tournament = outrights.get("_event_name", "")
    if not tournament:
        return "Could not determine current tournament."

    raw = pull_coursefit_data(tournament)
    if not raw:
        return "No Betsperts data available for this tournament."

    # Find player by fuzzy match
    matched = match_betsperts_to_dg(list(raw.values()), [player_name])
    if not matched:
        target = _normalize(player_name)
        for bp_name, bp_data in raw.items():
            if target in _normalize(bp_name):
                matched = {player_name: bp_data}
                break
    if not matched:
        return f"Player '{player_name}' not found in field."

    bp_data = list(matched.values())[0]
    display_name = bp_data.get("playerName", player_name)

    # Compute rank by composite
    all_comp = sorted(
        [(n, d["sg_composite"]) for n, d in raw.items() if d.get("sg_composite") is not None],
        key=lambda x: x[1], reverse=True,
    )
    rank = next(
        (i + 1 for i, (n, _) in enumerate(all_comp) if n == bp_data["playerName"]),
        None,
    )

    profile = _PROFILES.get(tournament, {})
    if profile:
        difficulties = [f"OTT:{profile.get('sg_ott','?')}", f"APP:{profile.get('sg_app','?')}",
                        f"ARG:{profile.get('sg_arg','?')}", f"P:{profile.get('sg_p','?')}"]
        cond_desc = f"{tournament}\nWeights: {', '.join(difficulties)}"
    else:
        cond_desc = f"{tournament} — default weights"

    return {
        "player_name": display_name,
        "conditions_desc": cond_desc,
        "sg_ott": bp_data.get("sg_ott"),
        "sg_app": bp_data.get("sg_app"),
        "sg_arg": bp_data.get("sg_arg"),
        "sg_p": bp_data.get("sg_p"),
        "sg_t2g": bp_data.get("sg_t2g"),
        "form_rounds": bp_data.get("form_rounds"),
        "baseline_rounds": bp_data.get("baseline_rounds"),
        "sg_composite": bp_data.get("sg_composite"),
        "sg_rank": rank,
        "field_size": len(all_comp),
    }


# ---------------------------------------------------------------------------
# /fieldsg
# ---------------------------------------------------------------------------
@bot.tree.command(name="fieldsg",
                  description="Top/bottom 10 by condition-filtered SG:TOT")
@app_commands.describe(
    tournament="Tournament name override (default: current event)",
)
async def cmd_fieldsg(
    interaction: discord.Interaction,
    tournament: Optional[str] = None,
):
    await interaction.response.defer()

    try:
        result = await asyncio.to_thread(_run_fieldsg, tournament)
    except Exception as e:
        await interaction.followup.send(f"Field SG lookup failed: {e}")
        return

    if isinstance(result, str):
        await interaction.followup.send(result)
        return

    embed = discord.Embed(
        title=f"Field SG:TOT — {result['tournament']}",
        description=result.get("conditions_desc", ""),
        color=0x3498DB,
    )

    embed.add_field(name="Top 10", value=f"```\n{result['top']}\n```", inline=False)
    embed.add_field(name="Bottom 10", value=f"```\n{result['bottom']}\n```", inline=False)

    await interaction.followup.send(embed=embed)


def _run_fieldsg(tournament_override: str | None):
    """Blocking field SG lookup."""
    from src.core.coursefit import pull_coursefit_data, _PROFILES

    tournament = tournament_override
    if not tournament:
        outrights = pull_all_outrights(tour="pga")
        tournament = outrights.get("_event_name", "")
    if not tournament:
        return "Could not determine current tournament."

    raw = pull_coursefit_data(tournament)
    if not raw:
        return "No Betsperts data available."

    all_comp = sorted(
        [(n, d["sg_composite"], d.get("form_rounds") or 0)
         for n, d in raw.items() if d.get("sg_composite") is not None],
        key=lambda x: x[1], reverse=True,
    )

    def fmt_list(items):
        lines = []
        for i, (name, sg, rds) in enumerate(items, 1):
            sign = "+" if sg >= 0 else ""
            lines.append(f"{i:>2}. {name[:20]:<20} {sign}{sg:.2f}  ({rds}r)")
        return "\n".join(lines)

    profile = _PROFILES.get(tournament, {})
    if profile:
        difficulties = [f"OTT:{profile.get('sg_ott','?')}", f"APP:{profile.get('sg_app','?')}",
                        f"ARG:{profile.get('sg_arg','?')}", f"P:{profile.get('sg_p','?')}"]
        cond_desc = f"Weighted: {', '.join(difficulties)}"
    else:
        cond_desc = "Default equal weights"

    return {
        "tournament": tournament,
        "conditions_desc": cond_desc,
        "top": fmt_list(all_comp[:10]),
        "bottom": fmt_list(all_comp[-10:][::-1]),
    }


# ---------------------------------------------------------------------------
# /expertpicks
# ---------------------------------------------------------------------------
@bot.tree.command(name="expertpicks",
                  description="Fetch and analyze expert picks for current tournament")
@app_commands.describe(
    tournament="Tournament name override (default: current event)",
)
async def cmd_expertpicks(
    interaction: discord.Interaction,
    tournament: Optional[str] = None,
):
    await interaction.response.defer()

    try:
        result = await asyncio.to_thread(_run_expert_picks, tournament)
    except Exception as e:
        await interaction.followup.send(f"Expert picks failed: {e}")
        return

    if isinstance(result, str):
        await interaction.followup.send(result)
        return

    embed = discord.Embed(
        title=f"Expert Picks — {result['tournament']}",
        description=result.get("sources_desc", ""),
        color=0x9B59B6,
    )

    if result.get("bullish"):
        embed.add_field(
            name="Bullish",
            value=f"```\n{result['bullish']}\n```",
            inline=False,
        )
    if result.get("fades"):
        embed.add_field(
            name="Fades",
            value=f"```\n{result['fades']}\n```",
            inline=False,
        )
    if not result.get("bullish") and not result.get("fades"):
        embed.add_field(name="Result", value="No explicit picks found.", inline=False)

    embed.set_footer(text=f"Sources: {result.get('source_count', 0)} | "
                          f"Picks: {result.get('pick_count', 0)}")

    await interaction.followup.send(embed=embed)


def _run_expert_picks(tournament_override: str | None):
    """Blocking expert picks analysis."""
    from src.api.experts import fetch_all_expert_content
    from src.core.expert_picks import (
        extract_all_picks, compute_expert_signals, format_expert_summary,
        SIGNAL_LABELS,
    )

    tournament = tournament_override
    if not tournament:
        outrights = pull_all_outrights(tour="pga")
        tournament = outrights.get("_event_name", "")
    if not tournament:
        return "Could not determine current tournament."

    # Fetch content
    content = fetch_all_expert_content(tournament)
    if not content:
        return f"No expert content found for {tournament}."

    # Extract picks
    picks = extract_all_picks(content)
    if not picks:
        return (f"Found {len(content)} sources but no explicit picks extracted. "
                f"Sources: {', '.join(c.author for c in content)}")

    # Get field names for matching
    outrights = pull_all_outrights(tour="pga")
    field_names = []
    for mkt_data in outrights.values():
        if isinstance(mkt_data, list):
            for p in mkt_data:
                name = p.get("player_name", "")
                if name and name not in field_names:
                    field_names.append(name)

    signals = compute_expert_signals(picks, field_names)

    # Format output
    sorted_players = sorted(
        signals.items(), key=lambda x: x[1]["score"], reverse=True,
    )
    bullish = [(n, s) for n, s in sorted_players if s["score"] > 0]
    fades = [(n, s) for n, s in sorted_players if s["score"] < 0]

    def fmt_list(items):
        lines = []
        for name, sig in items[:10]:
            label = SIGNAL_LABELS.get(sig["signal"], "")
            authors = ", ".join(p["author"] for p in sig["picks"])
            lines.append(f"{name[:20]:<20} {sig['pick_count']}x "
                         f"score:{sig['score']:+.1f} {label} ({authors[:30]})")
        return "\n".join(lines)

    sources = list({c.author for c in content})

    return {
        "tournament": tournament,
        "sources_desc": f"{len(content)} sources analyzed",
        "bullish": fmt_list(bullish) if bullish else None,
        "fades": fmt_list(fades) if fades else None,
        "source_count": len(content),
        "pick_count": len(picks),
    }


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
