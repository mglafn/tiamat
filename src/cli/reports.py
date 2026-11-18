"""
src/cli/reports.py
------------------
Consolidated Rich/plain-stdout report renderers for backtest, live market scan,
buyer dip radar, and CPCV verification scorecards.
"""

import pandas as pd

from src.cli.console import (
    HAS_RICH,
    Panel,
    Table,
    Text,
    box,
    console,
    print_banner,
    print_msg,
)
from src.config import MODEL_CONFIG


def _render_trade_blotter(
    trades: list[dict], title: str, header_style: str, metric_style: str
) -> None:
    table = Table(
        title=title,
        box=box.ROUNDED,
        border_style="bright_black",
        header_style=header_style,
        expand=True,
    )
    table.add_column("Execution Date", style="dim")
    table.add_column("Card SKU / Name", style="bold white")
    table.add_column("Set", justify="center", style="cyan")
    table.add_column("Finish", justify="center", style="yellow")
    table.add_column("Units", justify="right", style="bold white")
    table.add_column("Cost Basis", justify="right")
    table.add_column("Realized Exit", justify="right")
    table.add_column("Net Profit", justify="right", style=metric_style)
    table.add_column("Net ROI", justify="right", style=metric_style)

    for row in trades:
        table.add_row(
            row["price_date"],
            row["name"],
            row["set_code"],
            row["finish"].upper(),
            str(row.get("allocated_units", 1)),
            f"${row['basis']:.2f}",
            f"${row['realized_exit_payout']:.2f}",
            f"${row['total_profit']:+,.2f}",
            f"{row['net_roi_pct']:+.1f}%",
        )
    console.print(table)
    console.print()


def render_terminal_scorecard(payload: dict) -> None:
    summary = payload["summary"]
    ablation = payload["ablation"]
    funnel = payload.get("funnel", {})
    top_trades = payload["top_trades"]
    worst_trades = payload.get("worst_trades", [])

    if not HAS_RICH:
        print(
            f"\nNet PnL: ${summary['total_net_profit']:+,.2f} | "
            f"ROI: {summary['portfolio_roi']:+.2f}% | "
            f"Trades: {summary['total_trades']}"
        )
        return

    print_banner(
        "CQR & Risk-Gated Backtest Engine",
        "Out-of-Time Chronological Execution Blotter • Asymmetric Loss Shield",
        [
            f"[dim white]Window: {summary['test_start_date']} → "
            f"{summary['test_end_date']}[/dim white]",
            f"[dim white]Universe: {summary['test_universe_count']:,} "
            "active candidate instances[/dim white]  "
            r"[bold green]\[Verified 14D Embargo][/bold green]",
        ],
        brand="TIAMAT QUANT ARBITRAGE TERMINAL",
    )

    if funnel:
        funnel_table = Table(
            box=box.ROUNDED,
            header_style="bold blue",
            border_style="bright_black",
            expand=True,
            title=(
                "[bold white]1. DEFENSIVE SIGNAL FUNNEL & "
                "MULTI-LAYERED GATE RETENTION[/bold white]"
            ),
        )
        funnel_table.add_column("Defensive Filter / Risk Gate", style="bold white")
        funnel_table.add_column("Passing Candidates", justify="right", style="cyan")
        funnel_table.add_column("Funnel Retention", justify="right", style="bold yellow")
        funnel_table.add_column("Filtration Function", style="dim")

        tot = summary["test_universe_count"]
        descriptions = {
            "Total Test Candidates": "Unfiltered out-of-time candidate universe",
            "Stage 1 Spike Mover (τ)": "Right-tail upward spike conviction (P >= tau)",
            "q10 Downside Floor Passed": (
                f"10th percentile return floor (q10 >= {MODEL_CONFIG['Q10_FLOOR_PCT']:.1f}%)"
            ),
            "Set Decay Filter Passed": (
                "Dynamic falling knife decay filter "
                f"(>= {MODEL_CONFIG['DECAY_VELOCITY_FLOOR_PCT']:.1f}%/day)"
            ),
            "Net ROI Hurdle Cleared": "Expected payout exceeds landed basis + fees",
        }
        for stage, count in funnel.items():
            pct = f"{(count / tot) * 100:.3f}%" if tot > 0 else "0%"
            desc = descriptions.get(stage, "Analytical risk filter")
            funnel_table.add_row(stage, f"{count:,}", pct, desc)

        console.print(funnel_table)
        console.print()

    pnl = summary["total_net_profit"]
    roi = summary["portfolio_roi"]
    win_rate = summary["win_rate"]
    pnl_color = "bold green" if pnl >= 0 else "bold red"
    roi_color = "bold green" if roi >= 0 else "bold red"

    score_table = Table(
        box=box.ROUNDED,
        show_header=True,
        header_style="bold cyan",
        border_style="bright_black",
        expand=True,
        title="[bold white]2. STRATEGY PERFORMANCE SCORECARD & CAPITAL EFFICIENCY[/bold white]",
    )
    score_table.add_column("Net Realized PnL ($)", justify="center")
    score_table.add_column("Portfolio ROI (%)", justify="center")
    score_table.add_column("Win Rate (W / L Count)", justify="center")
    score_table.add_column("Capital Committed ($)", justify="center")
    score_table.add_column("Ablation Loss Shield", justify="center", style="dim green")

    naive_loss_diff = ablation.get("naive_profit", 0.0) - pnl
    shield_msg = (
        f"+${abs(naive_loss_diff):,.2f} Preserved"
        if pnl >= ablation.get("naive_profit", 0.0)
        else "—"
    )

    score_table.add_row(
        f"[{pnl_color}]${pnl:+,.2f}[/{pnl_color}]",
        f"[{roi_color}]{roi:+.2f}%[/{roi_color}]",
        f"{win_rate:.1f}% ({summary['win_trades']}W / {summary['loss_trades']}L)",
        f"${summary['total_capital']:,.2f}",
        f"[bold green]{shield_msg}[/bold green]",
    )
    console.print(score_table)
    console.print()

    if len(top_trades) > 0:
        _render_trade_blotter(
            top_trades,
            f"[bold white]3. EXECUTED TRADES BLOTTER "
            f"(Showing Top {len(top_trades)} Alpha Executions)[/bold white]",
            header_style="bold green",
            metric_style="bold green",
        )
    else:
        print_msg(
            "[dim yellow]ℹ No trades passed all defensive gates in this evaluation window. "
            "(Capital 100% preserved)[/dim yellow]\n",
            "No trades passed all defensive gates in this evaluation window.",
        )

    if len(worst_trades) > 0:
        _render_trade_blotter(
            worst_trades,
            f"[bold white]4. DRAWDOWN & LOSS DIAGNOSTICS "
            f"(Showing Worst {len(worst_trades)} Positions)[/bold white]",
            header_style="bold red",
            metric_style="bold red",
        )


def render_market_scan_report(payload: dict) -> None:
    meta = payload["meta"]
    funnel = payload["funnel"]
    spatial_arbs = payload["spatial_arbitrage"]
    directional_alpha = payload["directional_alpha"]
    vetoed_traps = payload["vetoed_traps"]

    if not HAS_RICH:
        print(
            f"\nTIAMAT MARKET SCAN │ Date: {meta['latest_date']} │ "
            f"Universe: {meta['scanned_universe']:,} SKUs"
        )
        print(
            f"Spatial Arbs: {len(spatial_arbs)} | "
            f"Directional Alpha Signals: {len(directional_alpha)}"
        )
        return

    print_banner(
        "Live Market Opportunity Scanner",
        "Cross-Venue Spatial Arbitrage & CQR-Gated Directional Alpha",
        [
            f"[dim white]Market Date: {meta['latest_date']}[/dim white]",
            f"[dim white]Universe: {meta['scanned_universe']:,} Active SKUs[/dim white]  "
            r"[bold green]\[CQR Risk Shield Active][/bold green]",
        ],
        brand="TIAMAT QUANT ARBITRAGE TERMINAL",
    )

    funnel_table = Table(
        box=box.ROUNDED,
        header_style="bold blue",
        border_style="bright_black",
        expand=True,
        title="[bold white]1. LIVE DEFENSIVE SIGNAL FUNNEL[/bold white]",
    )
    funnel_table.add_column("Scanning / Vetting Stage", style="bold white")
    funnel_table.add_column("Passing Candidates", justify="right", style="cyan")
    funnel_table.add_column("Funnel Retention", justify="right", style="bold yellow")
    funnel_table.add_column("Gate Constraint", style="dim")

    tot = meta["scanned_universe"]
    roi_hurdle = meta.get("min_net_roi_pct", MODEL_CONFIG["DEFAULT_ROI_HURDLE_PCT"])
    descriptions = {
        "Total Scanned Active SKUs": "Unfiltered live active catalog records",
        "Stage 1 Spike Mover (τ)": (
            "Upward right-tail breakout probability "
            f"(P >= {meta.get('prob_threshold', 0.40):.2f})"
        ),
        "q10 Downside Floor Passed": (
            f"10th percentile return floor >= {MODEL_CONFIG['Q10_FLOOR_PCT']:.1f}%"
        ),
        "Set Decay Filter Passed": (
            "Price decay derivative >= "
            f"{MODEL_CONFIG['DECAY_VELOCITY_FLOOR_PCT']:.2f}%/day (Knife Filter)"
        ),
        "Net ROI Hurdle Cleared": f"Expected net ROI >= {roi_hurdle:.1f}%",
    }
    for stage, count in funnel.items():
        pct = f"{(count / tot) * 100:.3f}%" if tot > 0 else "0%"
        desc = descriptions.get(stage, "Analytical filter")
        funnel_table.add_row(stage, f"{count:,}", pct, desc)

    console.print(funnel_table)
    console.print()

    if len(spatial_arbs) > 0:
        arb_table = Table(
            title=(
                "[bold white]2. INSTANTANEOUS SPATIAL ARBITRAGE "
                f"(Showing Top {len(spatial_arbs)} Locked Spreads)[/bold white]"
            ),
            box=box.ROUNDED,
            border_style="bright_black",
            header_style="bold green",
            expand=True,
        )
        arb_table.add_column(
            "Card SKU / Name", style="bold white", max_width=26, overflow="ellipsis"
        )
        arb_table.add_column("Set", justify="center", style="cyan")
        arb_table.add_column("Finish", justify="center", style="yellow")
        arb_table.add_column("TCG Retail", justify="right")
        arb_table.add_column("Landed Cost", justify="right", style="dim")
        arb_table.add_column("CK Credit", justify="right", style="cyan")
        arb_table.add_column("Net Spread", justify="right", style="bold green")
        arb_table.add_column("Spread %", justify="right", style="bold green")

        for a in spatial_arbs:
            arb_table.add_row(
                a["name"],
                a["set_code"],
                a["finish"].upper(),
                f"${a['tcg_price']:.2f}",
                f"${a['total_acquisition_basis']:.2f}",
                f"${a['ck_store_credit_payout']:.2f}",
                f"+${a['price_spread']:.2f}",
                f"{a['spread_pct']:+.1f}%",
            )
        console.print(arb_table)
        console.print()
    else:
        print_msg(
            "[dim yellow]ℹ No spatial arbitrage spreads cleared acquisition basis "
            "and fee hurdles today.[/dim yellow]\n",
            "No spatial arbitrage spreads cleared acquisition basis and fee hurdles today.",
        )

    if len(directional_alpha) > 0:
        alpha_table = Table(
            title=(
                "[bold white]3. HIGH-CONVICTION CQR-GATED DIRECTIONAL ALPHA "
                f"(Showing Top {len(directional_alpha)})[/bold white]"
            ),
            box=box.ROUNDED,
            border_style="bright_black",
            header_style="bold cyan",
            expand=True,
        )
        alpha_table.add_column(
            "Card SKU / Name", style="bold white", max_width=24, overflow="ellipsis"
        )
        alpha_table.add_column("Set", justify="center", style="cyan")
        alpha_table.add_column("Finish", justify="center", style="yellow")
        alpha_table.add_column("Close", justify="right")
        alpha_table.add_column("Pred Gain", justify="right", style="yellow")
        alpha_table.add_column("CQR Floor", justify="right", style="green")
        alpha_table.add_column("E[Net ROI]", justify="right", style="bold green")
        alpha_table.add_column("Kelly Units", justify="right", style="bold white")
        alpha_table.add_column("Target Payout", justify="right", style="dim green")

        for d in directional_alpha:
            alpha_table.add_row(
                d["name"],
                d["set_code"],
                d["finish"].upper(),
                f"${d['current_price']:.2f}",
                f"{d['pred_magnitude']:+.1f}%",
                f"{d['cqr_lpb']:+.1f}%",
                f"{d['exp_net_roi_pct']:+.1f}%",
                f"{d['allocated_units']} units",
                f"${d['exp_exit_payout']:.2f}",
            )
        console.print(alpha_table)
        console.print()
    else:
        print_msg(
            "[dim green]🛡 Defensive Veto Active: No directional signals cleared CQR LPB "
            "& decay gates. (Capital 100% Preserved)[/dim green]\n",
            "Defensive Veto Active: No directional signals cleared CQR LPB & decay gates.",
        )

    if len(vetoed_traps) > 0:
        trap_table = Table(
            title=(
                "[bold white]4. TOP VETOED VALUE TRAPS "
                "(Active Friction & Crash Defense Proof)[/bold white]"
            ),
            box=box.ROUNDED,
            border_style="bright_black",
            header_style="bold magenta",
            expand=True,
        )
        trap_table.add_column(
            "Card SKU / Name", style="bold white", max_width=24, overflow="ellipsis"
        )
        trap_table.add_column("Set", justify="center", style="cyan")
        trap_table.add_column("Finish", justify="center", style="yellow")
        trap_table.add_column("Price", justify="right", style="dim")
        trap_table.add_column("ML Pred %", justify="right", style="yellow")
        trap_table.add_column("CQR Floor", justify="right", style="dim")
        trap_table.add_column("Defensive Veto Reason", style="bold magenta")

        for t in vetoed_traps:
            trap_table.add_row(
                t["name"],
                t["set_code"],
                t["finish"].upper(),
                f"${t['current_price']:.2f}",
                f"{t['pred_magnitude']:+.1f}%",
                f"{t['cqr_lpb']:+.1f}%",
                t["veto_reason"],
            )
        console.print(trap_table)
        console.print()


def render_buyer_report(
    total_df: pd.DataFrame,
    floor_df: pd.DataFrame,
    breakout_df: pd.DataFrame,
    knife_df: pd.DataFrame,
    min_discount: float,
    tau: float,
    top_n: int,
) -> None:
    del tau, top_n
    if not HAS_RICH:
        print(f"\n--- TIAMAT BUYER RADAR (Universe: {len(total_df):,} staples) ---")
        print(
            f"Confirmed Floors: {len(floor_df)} | "
            f"Pre-Spike Breakouts: {len(breakout_df)} | Falling Knives: {len(knife_df)}"
        )
        return

    header = Table.grid(expand=True)
    header.add_column(justify="left", ratio=3)
    header.add_column(justify="right", ratio=2)

    title = Text()
    title.append("TIAMAT QUANT TERMINAL", style="bold cyan")
    title.append(" │ ", style="dim white")
    title.append("Staple Floor & Dip Accumulator", style="bold green")
    title.append(
        "\nDeckbuilder Acquisition Radar • No Resale Friction • Mean-Reversion Timing",
        style="dim italic",
    )

    meta = Text()
    meta.append(f"Evaluated Staples: {len(total_df):,} SKUs\n", style="dim white")
    meta.append("Acquisition Drag: ", style="dim white")
    meta.append("0% Seller Fee (Direct Buy Mode)", style="bold green")
    header.add_row(title, meta)
    console.print(Panel(header, box=box.ROUNDED, border_style="green", padding=(0, 1)))
    console.print()

    if len(floor_df) > 0:
        table_floor = Table(
            title=(
                "[bold green]1. CONFIRMED LOCAL FLOORS "
                "(Bleed Stopped • Ready to Buy for Decks)[/bold green]"
            ),
            box=box.ROUNDED,
            border_style="bright_black",
            header_style="bold green",
            expand=True,
        )
        table_floor.add_column("Card Name", style="bold white", max_width=24, overflow="ellipsis")
        table_floor.add_column("Set", justify="center", style="cyan")
        table_floor.add_column("Finish", justify="center", style="yellow")
        table_floor.add_column("EDH Rank", justify="center", style="dim")
        table_floor.add_column("Current Ask", justify="right")
        table_floor.add_column("Landed Cost", justify="right", style="dim")
        table_floor.add_column("30D Baseline", justify="right", style="cyan")
        table_floor.add_column("Dip Discount", justify="right", style="bold green")
        table_floor.add_column("Dollar Savings", justify="right", style="bold green")
        table_floor.add_column("3D Velocity", justify="right", style="dim")

        for _, r in floor_df.iterrows():
            table_floor.add_row(
                r["name"],
                r["set_code"],
                r["finish"].upper(),
                f"#{int(r['edhrec_rank']):,}" if pd.notna(r["edhrec_rank"]) else "—",
                f"${r['current_price']:.2f}",
                f"${r['buyer_landed_cost']:.2f}",
                f"${r['sma_30']:.2f}",
                f"-{r['discount_sma30_pct']:.1f}%",
                f"+${r['dollar_savings']:.2f}",
                f"{r['price_decay_velocity_3d']:+.2f}%/d",
            )
        console.print(table_floor)
        console.print()
    else:
        print_msg(
            f"[dim yellow]ℹ No active staples have stabilized at >= "
            f"{min_discount:.1f}% discount today.[/dim yellow]\n",
            f"No active staples have stabilized at >= {min_discount:.1f}% discount today.",
        )

    if len(breakout_df) > 0:
        table_breakout = Table(
            title=(
                "[bold yellow]2. PRE-SPIKE BREAKOUT ALERTS "
                "(Buy Immediately • High Probability of Markup)[/bold yellow]"
            ),
            box=box.ROUNDED,
            border_style="bright_black",
            header_style="bold yellow",
            expand=True,
        )
        table_breakout.add_column(
            "Card Name", style="bold white", max_width=24, overflow="ellipsis"
        )
        table_breakout.add_column("Set", justify="center", style="cyan")
        table_breakout.add_column("Finish", justify="center", style="yellow")
        table_breakout.add_column("Current Price", justify="right")
        table_breakout.add_column("Breakout Prob (P)", justify="right", style="bold yellow")
        table_breakout.add_column("Predicted Spike", justify="right", style="bold green")
        table_breakout.add_column("Projected 7D Price", justify="right", style="cyan")
        table_breakout.add_column("Action Directive", style="bold white")

        for _, r in breakout_df.iterrows():
            proj_price = r["current_price"] * (1.0 + r["pred_spike_pct"] / 100.0)
            table_breakout.add_row(
                r["name"],
                r["set_code"],
                r["finish"].upper(),
                f"${r['current_price']:.2f}",
                f"{r['move_prob']:.1%}",
                f"+{r['pred_spike_pct']:.1f}%",
                f"${proj_price:.2f}",
                "[bold red]BUY BEFORE SPIKE[/bold red]",
            )
        console.print(table_breakout)
        console.print()
    else:
        print_msg(
            "[dim green]✔ No imminent buyout spikes detected across "
            "tracked staple universe.[/dim green]\n",
            "No imminent buyout spikes detected across tracked staple universe.",
        )

    if len(knife_df) > 0:
        table_knife = Table(
            title=(
                "[bold magenta]3. FALLING KNIFE VETO "
                "(Patience Shield • Bleed Still Accelerating)[/bold magenta]"
            ),
            box=box.ROUNDED,
            border_style="bright_black",
            header_style="bold magenta",
            expand=True,
        )
        table_knife.add_column("Card Name", style="bold white", max_width=24, overflow="ellipsis")
        table_knife.add_column("Set", justify="center", style="cyan")
        table_knife.add_column("Finish", justify="center", style="yellow")
        table_knife.add_column("Current Ask", justify="right")
        table_knife.add_column("Discount vs 30D", justify="right", style="magenta")
        table_knife.add_column("Decay Velocity", justify="right", style="bold red")
        table_knife.add_column("Advisory Recommendation", style="italic dim")

        for _, r in knife_df.iterrows():
            table_knife.add_row(
                r["name"],
                r["set_code"],
                r["finish"].upper(),
                f"${r['current_price']:.2f}",
                f"-{r['discount_sma30_pct']:.1f}%",
                f"{r['price_decay_velocity_3d']:.2f}%/d",
                "DO NOT BUY YET — Bleed active",
            )
        console.print(table_knife)
        console.print()


def render_cpcv_scorecard(
    total_instances: int,
    total_floor_entries: int,
    floor_acc: float,
    floor_avg: float,
    total_knife_vetoes: int,
    knife_acc: float,
    knife_avg: float,
    total_radar_alerts: int,
    radar_acc: float,
    radar_avg: float,
    buyer_alpha: float,
    dar: float,
    fir: float,
    cfg: dict,
) -> None:
    if not HAS_RICH:
        print(f"CPCV Results across {total_instances:,} instances:")
        print(
            f"Confirmed Floors: {total_floor_entries:,} "
            f"(Acc: {floor_acc:.1f}%, Avg: {floor_avg:+.2f}%)"
        )
        print(
            f"Knife Vetoes: {total_knife_vetoes:,} "
            f"(Acc: {knife_acc:.1f}%, Avg: {knife_avg:+.2f}%)"
        )
        if total_radar_alerts > 0:
            print(
                f"Radar Alerts: {total_radar_alerts:,} "
                f"(Acc: {radar_acc:.1f}%, Avg: {radar_avg:+.2f}%)"
            )
        print(f"Buyer Alpha: {buyer_alpha:.2f}% | DAR: {dar:.1f}% | FIR: {fir:.1f}%")
        return

    table = Table(
        title="[bold white]COMBINATORIAL PURGED CROSS-VALIDATION (CPCV) SCORECARD[/bold white]",
        box=box.ROUNDED,
        header_style="bold cyan",
        border_style="bright_black",
        expand=True,
    )
    table.add_column("Buyer Decision Signal", style="bold white")
    table.add_column("Trigger Count", justify="right", style="cyan")
    table.add_column("Ground Truth Target", style="dim")
    table.add_column("Empirical Acc (%)", justify="right", style="bold green")
    table.add_column("Avg 7D Realized Move", justify="right", style="bold yellow")

    table.add_row(
        "Confirmed Floor Entry",
        f"{total_floor_entries:,}",
        f"Card price held or bounced (Ret >= {cfg['SUPPORT_CUSHION_PCT']:.1f}%)",
        f"{floor_acc:.1f}%",
        f"{floor_avg:+.2f}%",
    )
    table.add_row(
        "Falling Knife Veto (Wait)",
        f"{total_knife_vetoes:,}",
        "Card continued bleeding (Ret < 0.0%)",
        f"{knife_acc:.1f}%",
        f"{knife_avg:+.2f}%",
    )
    if total_radar_alerts > 0:
        table.add_row(
            "Buyer Radar Breakout Alert",
            f"{total_radar_alerts:,}",
            f"Card realized upward spike (Ret >= +{MODEL_CONFIG['SPIKE_THRESHOLD_PCT']:.1f}%)",
            f"{radar_acc:.1f}%",
            f"{radar_avg:+.2f}%",
        )

    score_panel = Table(box=box.ROUNDED, border_style="green", expand=True)
    score_panel.add_column("Buyer Alpha (Savings vs 30D SMA)", justify="center", style="bold green")
    score_panel.add_column(
        f"Floor Integrity Rate (FIR >= {cfg['SUPPORT_CUSHION_PCT']}%)",
        justify="center",
        style="bold cyan",
    )
    score_panel.add_column(
        f"Drawdown Avoidance Rate (DAR > {cfg['DRAWDOWN_TOLERANCE_PCT']}%)",
        justify="center",
        style="bold white",
    )
    score_panel.add_row(f"+{buyer_alpha:.2f}%", f"{fir:.1f}%", f"{dar:.1f}%")

    console.print("\n")
    console.print(table)
    console.print()
    console.print(
        Panel(
            score_panel,
            title="[bold green]WHITE-PAPER SPECIFICATION PERFORMANCE METRICS[/bold green]",
            box=box.ROUNDED,
            border_style="green",
        )
    )
    console.print()
