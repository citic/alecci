#!/usr/bin/env python3
"""
plot_labeled_results.py
Clustered stacked horizontal bar chart of labeled-benchmark detection results,
grouped by dataset (ClassExamples / DataRaceBench / DeepRace) and broken down
by concurrency issue type.

Each bar represents one (dataset, issue_type) combination.
Three stacked segments (left → right):
  Dark grey   : correct_detection  – expected and detected
  Mid grey    : unexpected         – detected but not expected (false positive)
  Light/hatch : false_negative     – expected but not detected (missed)

Usage:
  python3 concurrency_validation/plot_labeled_results.py
  python3 concurrency_validation/plot_labeled_results.py \\
      --csv path/to/issue_breakdown_labeled_results.csv   \\
      --output path/to/chart.png
"""

import argparse
from pathlib import Path

import matplotlib.pyplot as plt
import matplotlib.ticker as ticker
import pandas as pd


# ── colours (grayscale) ───────────────────────────────────────────────────────
# ── LaTeX-like font ───────────────────────────────────────────────────────────
plt.rcParams.update({
    'font.family':      'STIXGeneral',
    'mathtext.fontset': 'stix',
})

COLOUR_CORRECT    = "#575353"
COLOUR_UNEXPECTED = '#999999'
COLOUR_MISSED     = '#bbbbbb'

BAR_HEIGHT  = 0.38
INTRA_GAP   = 0.12   # gap between bars within a cluster
INTER_GAP   = 0.65   # extra gap between dataset clusters

DATASET_ORDER = ['ClassExamples', 'DataRaceBench', 'DeepRace']

ISSUE_LABELS = {
    'data_race':           'Data Race',
    'deadlock':            'Deadlock',
    'thread_leak':         'Thread Leak',
    'mutex_destruction':   'Mutex Destr.',
    'atomicity_violation': 'Atomicity Viol.',
}


# ── data loading ─────────────────────────────────────────────────────────────

def load(csv_path: Path) -> pd.DataFrame:
    df = pd.read_csv(csv_path)
    counts = (
        df.groupby(['dataset', 'issue_type', 'outcome'])
        .size()
        .unstack(fill_value=0)
    )
    for col in ('correct_detection', 'unexpected', 'false_negative'):
        if col not in counts.columns:
            counts[col] = 0
    return counts[['correct_detection', 'unexpected', 'false_negative']]


# ── layout builder ────────────────────────────────────────────────────────────

def build_layout(counts: pd.DataFrame):
    """Return a list of bar specs and cluster metadata.

    bar_specs  : list of dicts with keys y, label, c, u, m, dataset
    clusters   : list of dicts with keys y_lo, y_hi, name
    """
    bar_specs = []
    clusters  = []
    y = 0.0

    for ds in DATASET_ORDER:
        if ds not in counts.index.get_level_values('dataset'):
            continue

        ds_data = counts.loc[ds].copy()
        ds_data['_total'] = ds_data.sum(axis=1)
        ds_data = ds_data.sort_values('_total', ascending=True)  # lowest at bottom of cluster

        y_lo = y
        for issue_type, row in ds_data.iterrows():
            bar_specs.append(dict(
                y       = y,
                label   = ISSUE_LABELS.get(issue_type, issue_type),
                c       = int(row['correct_detection']),
                u       = int(row['unexpected']),
                m       = int(row['false_negative']),
                dataset = ds,
            ))
            y += BAR_HEIGHT + INTRA_GAP

        y_hi = y - INTRA_GAP
        clusters.append(dict(y_lo=y_lo, y_hi=y_hi, name=ds))
        y += INTER_GAP

    return bar_specs, clusters


# ── plot ──────────────────────────────────────────────────────────────────────

def plot(counts: pd.DataFrame, output: Path) -> None:
    bar_specs, clusters = build_layout(counts)

    x_max = max(b['c'] + b['u'] + b['m'] for b in bar_specs)
    fig_h = max(4.0, len(bar_specs) * (BAR_HEIGHT + INTRA_GAP) + len(clusters) * INTER_GAP + 0.5)
    fig, ax = plt.subplots(figsize=(9, fig_h))

    seen_correct = seen_unexp = seen_missed = False

    for b in bar_specs:
        left = 0.0
        y, c, u, m = b['y'], b['c'], b['u'], b['m']

        if c > 0:
            lbl = 'Expected' if not seen_correct else ''
            seen_correct = True
            ax.barh(y, c, height=BAR_HEIGHT, left=left,
                    color=COLOUR_CORRECT, label=lbl)
            if c >= 4:
                ax.text(left + c / 2, y, str(c), va='center', ha='center',
                        fontsize=8.5, color='white', fontweight='bold')
            left += c

        if u > 0:
            lbl = 'Unexpected' if not seen_unexp else ''
            seen_unexp = True
            ax.barh(y, u, height=BAR_HEIGHT, left=left,
                    color=COLOUR_UNEXPECTED, label=lbl)
            if u >= 2:
                ax.text(left + u / 2, y, str(u), va='center', ha='center',
                        fontsize=8.5, color='white', fontweight='bold')
            left += u

        if m > 0:
            lbl = 'Missed' if not seen_missed else ''
            seen_missed = True
            ax.barh(y, m, height=BAR_HEIGHT, left=left,
                    color=COLOUR_MISSED, hatch='///', edgecolor='#777777', label=lbl)
            if m >= 2:
                ax.text(left + m / 2, y, str(m), va='center', ha='center',
                        fontsize=8.5, color='#333333', fontweight='bold')
            left += m

        total = c + u + m
        if total > 0:
            ax.text(total + 0.4, y, str(total), va='center', ha='left',
                    fontsize=9, fontweight='bold')

    # ── y-ticks: issue type labels ────────────────────────────────────────────
    ax.set_yticks([b['y'] for b in bar_specs])
    ax.set_yticklabels([b['label'] for b in bar_specs], fontsize=10)
    ax.set_ylim(-0.5, bar_specs[-1]['y'] + BAR_HEIGHT + 0.3)

    # ── cluster labels and separators ────────────────────────────────────────
    for cl in clusters:
        y_mid = (cl['y_lo'] + cl['y_hi']) / 2

        # Bold dataset name to the right of the issue-type tick labels,
        # drawn in the axes coordinate using a text box for clarity
        ax.text(-0.18, y_mid, cl['name'],
                va='center', ha='center', fontsize=11, fontweight='bold',
                rotation=90, transform=ax.get_yaxis_transform())

        # Faint separator between clusters (skip after the last one)
        if cl is not clusters[-1]:
            sep_y = cl['y_hi'] + INTER_GAP / 2 + INTRA_GAP / 2
            ax.axhline(sep_y, color='#cccccc', linewidth=0.8, linestyle='--')

    # ── axes decoration ───────────────────────────────────────────────────────
    ax.set_title('Labeled Benchmarks — Detections by Issue Type',
                 fontsize=13, fontweight='bold', pad=10)
    ax.set_xlabel('Number of (test, issue type) instances', fontsize=11)
    ax.set_xlim(-0.3, x_max + 5)
    ax.xaxis.set_major_locator(ticker.MaxNLocator(integer=True))
    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)
    ax.spines['left'].set_visible(False)
    ax.tick_params(left=False)
    ax.grid(axis='x', linestyle='--', linewidth=0.5, alpha=0.5)
    ax.set_axisbelow(True)
    ax.legend(fontsize=10, loc='lower right', framealpha=0.9)

    # ── footer ────────────────────────────────────────────────────────────────
    total_c = int(counts['correct_detection'].sum())
    total_u = int(counts['unexpected'].sum())
    total_m = int(counts['false_negative'].sum())
    footer = (
        f"Instances: {total_c + total_u + total_m}   ·   "
        f"Detected: {total_c}   ·   "
        f"Unexpected: {total_u}   ·   "
        f"Missed: {total_m}"
    )
    fig.text(0.5, 0.01, footer, ha='center', va='bottom', fontsize=11,
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
        description='Plot labeled-benchmark detection results by dataset and issue type.'
    )
    parser.add_argument(
        '--csv', type=Path,
        default=here / 'results' / 'issue_breakdown_labeled_results.csv',
    )
    parser.add_argument(
        '--output', type=Path,
        default=here / 'results' / 'labeled_detection_chart.png',
    )
    args = parser.parse_args()

    if not args.csv.exists():
        print(f"Error: CSV not found: {args.csv}")
        raise SystemExit(1)

    counts = load(args.csv)
    plot(counts, args.output)


if __name__ == '__main__':
    main()
