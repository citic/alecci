#!/usr/bin/env python3
"""
plot_sct_results.py
Generate a stacked bar chart of SCTBench detection results by signal type.

Each bar represents one detection mechanism (Data Race, Deadlock, Crash, Timeout).
The stack shows:
  - Blue  : expected detections  (program labeled 'bug' and signal triggered)
  - Orange: unexpected detections (program labeled 'none' but signal triggered = false positive)

A program can appear in multiple bars if multiple signals fired (e.g. din_phil_sat
triggers both TSan data_race and TSan deadlock).

Usage:
  python3 concurrency_validation/plot_sct_results.py
  python3 concurrency_validation/plot_sct_results.py --csv path/to/sct_results.csv
  python3 concurrency_validation/plot_sct_results.py --output path/to/chart.png
"""

import argparse
from pathlib import Path

import matplotlib.pyplot as plt
import matplotlib.ticker as ticker
import pandas as pd


# ── data helpers ──────────────────────────────────────────────────────────────

def parse_pipe(cell: str) -> set:
    """Split a pipe-separated cell into a set, dropping the 'none' sentinel."""
    return {x.strip() for x in str(cell).split('|') if x.strip() not in ('none', '')}


def load(csv_path: Path) -> pd.DataFrame:
    df = pd.read_csv(csv_path)
    df['detected_set'] = df['detected_issues'].apply(parse_pipe)
    df['is_buggy']  = df['expected_issues'] == 'bug'
    df['is_correct'] = df['expected_issues'] == 'none'
    df['crash']     = df['crash_occurred']  == 'yes'
    df['timed_out'] = df['timeout_occurred'] == 'yes'
    return df


def count_signal(df: pd.DataFrame, signal: str):
    """Return (expected, unexpected) program counts for a detection signal.

    'crash' and 'timeout' are read from their dedicated columns; all others
    are looked up in the detected_set (TSan-reported issue types).
    """
    if signal == 'crash':
        mask = df['crash']
    elif signal == 'timeout':
        mask = df['timed_out']
    else:
        mask = df['detected_set'].apply(lambda s: signal in s)

    triggered  = df[mask]
    expected   = int(triggered['is_buggy'].sum())
    unexpected = int(triggered['is_correct'].sum())
    return expected, unexpected


# ── plot ──────────────────────────────────────────────────────────────────────

SIGNALS = [
    ('data_race', 'Data Race\n(TSan)'),
    ('deadlock',  'Deadlock\n(TSan)'),
    ('crash',     'Crash\n(Assert / Abort)'),
    ('timeout',   'Timeout\n(Hung / Deadlock)'),
]

COLOUR_EXPECTED   = '#2d2d2d'   # dark grey
COLOUR_UNEXPECTED = '#999999'   # mid grey
COLOUR_MISSED     = '#bbbbbb'   # light grey (hatched to distinguish from unexpected)

BAR_HEIGHT = 0.35


def plot(df: pd.DataFrame, output: Path) -> None:
    total_buggy   = int(df['is_buggy'].sum())
    total_correct = int(df['is_correct'].sum())
    n_missed      = int((df['is_buggy'] & (df['status'] == 'MISS')).sum())
    detected      = total_buggy - n_missed

    labels       = [s[1] for s in SIGNALS]
    exp_counts   = []
    unexp_counts = []
    for key, _ in SIGNALS:
        e, u = count_signal(df, key)
        exp_counts.append(e)
        unexp_counts.append(u)

    # y positions: detection signals at 0..n-1, then a gap, then "Missed" at n+0.5
    n          = len(labels)
    y_signals  = list(range(n))
    y_missed   = n + 0.6          # extra gap separates it visually

    x_max = max(
        max(e + u for e, u in zip(exp_counts, unexp_counts)),
        n_missed,
    )

    fig, ax = plt.subplots(figsize=(8, 4.5))

    # ── detection signal bars ─────────────────────────────────────────────────
    seen_exp = seen_unexp = False
    for i, (e, u) in enumerate(zip(exp_counts, unexp_counts)):
        if e > 0:
            lbl = 'Expected' if not seen_exp else ''
            seen_exp = True
            ax.barh(i, e, height=BAR_HEIGHT, left=0,
                    color=COLOUR_EXPECTED, label=lbl)
        if u > 0:
            lbl = 'Unexpected' if not seen_unexp else ''
            seen_unexp = True
            ax.barh(i, u, height=BAR_HEIGHT, left=e,
                    color=COLOUR_UNEXPECTED, label=lbl)

        total = e + u
        # Count label to the right of the bar
        if total > 0:
            ax.text(total + 0.25, i, str(total),
                    va='center', ha='left', fontsize=10, fontweight='bold')
        # Sub-label for expected segment when there are also unexpected detections
        if e > 0 and u > 0:
            ax.text(e / 2, i, str(e),
                    va='center', ha='center', fontsize=9,
                    color='white', fontweight='bold')

    # ── missed bar ────────────────────────────────────────────────────────────
    ax.barh(y_missed, n_missed, height=BAR_HEIGHT,
            color=COLOUR_MISSED, hatch='///', edgecolor='#777777', label='Missed')
    ax.text(n_missed + 0.25, y_missed, str(n_missed),
            va='center', ha='left', fontsize=10, fontweight='bold')

    # ── axes formatting ───────────────────────────────────────────────────────
    all_y      = y_signals + [y_missed]
    all_labels = labels    + ['Missed\n(not detected)']

    ax.set_title('SCTBench — Detections by Signal Type', fontsize=13,
                 fontweight='bold', pad=10)
    ax.set_xlabel('Number of Programs', fontsize=11)
    ax.set_yticks(all_y)
    ax.set_yticklabels(all_labels, fontsize=11)
    ax.set_xlim(-0.3, x_max + 2.5)
    ax.set_ylim(-0.6, y_missed + 0.7)
    ax.xaxis.set_major_locator(ticker.MaxNLocator(integer=True))
    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)
    ax.spines['left'].set_visible(False)
    ax.tick_params(left=False)
    ax.grid(axis='x', linestyle='--', linewidth=0.5, alpha=0.5)
    ax.set_axisbelow(True)

    # Light separator line between signal bars and missed bar
    ax.axhline(n + 0.1, color='#cccccc', linewidth=0.8, linestyle=':')

    ax.legend(fontsize=10, loc='upper right', framealpha=0.9)

    # Summary footer
    footer = (
        f"Total: {total_buggy + total_correct} benchmarks   ·   "
        f"Buggy: {total_buggy} (detected {detected}, missed {n_missed})   ·   "
        f"Correct: {total_correct}"
    )
    fig.text(0.5, 0.01, footer, ha='center', va='bottom', fontsize=9,
             style='italic', color='#555555')

    plt.tight_layout(rect=[0, 0.04, 1, 1])
    output.parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(output, dpi=150, bbox_inches='tight')
    print(f"Chart saved to: {output}")
    plt.close()


# ── entry point ───────────────────────────────────────────────────────────────

def main():
    here = Path(__file__).parent
    parser = argparse.ArgumentParser(
        description='Plot SCTBench detection results as a stacked bar chart.'
    )
    parser.add_argument(
        '--csv', type=Path,
        default=here / 'results' / 'sct_results.csv',
        help='Path to sct_results.csv (default: results/sct_results.csv next to this script)',
    )
    parser.add_argument(
        '--output', type=Path,
        default=here / 'results' / 'sct_detection_chart.png',
        help='Output image path (default: results/sct_detection_chart.png)',
    )
    args = parser.parse_args()

    if not args.csv.exists():
        print(f"Error: CSV not found: {args.csv}", flush=True)
        raise SystemExit(1)

    df = load(args.csv)
    plot(df, args.output)


if __name__ == '__main__':
    main()
