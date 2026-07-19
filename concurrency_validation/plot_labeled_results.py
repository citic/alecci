#!/usr/bin/env python3
"""
plot_labeled_results.py
Clustered stacked horizontal bar chart of labeled-benchmark detection results,
grouped by dataset (ClassExamples / DataRaceBench / DeepRace) and broken down
by concurrency issue type.

Each bar represents one (dataset, issue_type) combination.
Three stacked segments (left → right):
  Correct   : correct_detection  – expected and detected
  Unexpected: detected but not expected (false positive)
  Missed    : expected but not detected (false negative, hatched)

Usage:
  python3 concurrency_validation/plot_labeled_results.py
  python3 concurrency_validation/plot_labeled_results.py --color
  python3 concurrency_validation/plot_labeled_results.py --color --lang es
  python3 concurrency_validation/plot_labeled_results.py \\
      --csv path/to/issue_breakdown_labeled_results.csv \\
      --output path/to/chart.png
"""

import argparse
from pathlib import Path

import matplotlib.pyplot as plt
import matplotlib.ticker as ticker
import pandas as pd

plt.rcParams.update({
    'font.family':      'STIXGeneral',
    'mathtext.fontset': 'stix',
})

# ── colour palettes ───────────────────────────────────────────────────────────
PALETTE_GS = dict(
    correct     = '#575353',
    unexpected  = '#999999',
    missed      = '#bbbbbb',
    missed_edge = '#777777',
    text_dark   = '#333333',
)
# Soft/desaturated variants of the Alecci syntax-highlighting colours:
#   correct    ← SteelBlue  (control-flow keywords, class 1)
#   unexpected ← MediumOrchid (concurrency-primitive keywords, class 3)
#   missed     ← Peru        (built-in function keywords, class 4)
PALETTE_C = dict(
    correct     = '#5B8FB8',
    unexpected  = '#A870BA',
    missed      = '#CB9050',
    missed_edge = '#8A5C20',
    text_dark   = '#4A2800',
)

BAR_HEIGHT = 0.38
INTRA_GAP  = 0.12
INTER_GAP  = 0.65

DATASET_ORDER = ['ClassExamples', 'DataRaceBench', 'DeepRace']

ISSUE_LABELS = {
    'en': {
        'data_race':           'Data Race',
        'deadlock':            'Deadlock',
        'thread_leak':         'Thread Leak',
        'mutex_destruction':   'Mutex Destr.',
        'atomicity_violation': 'Atomicity Viol.',
    },
    'es': {
        'data_race':           'Condición de carrera',
        'deadlock':            'Bloqueo mutuo',
        'thread_leak':         'Fuga de hilos',
        'mutex_destruction':   'Destrucción mutex',
        'atomicity_violation': 'Viol. atomicidad',
    },
}

STRINGS = {
    'en': dict(
        title        = 'Labeled Benchmarks — Detections by Issue Type',
        xlabel       = 'Number of (test, issue type) instances',
        lbl_correct  = 'Expected',
        lbl_unexp    = 'Unexpected',
        lbl_missed   = 'Missed',
        ft_instances = 'Instances',
        ft_detected  = 'Detected',
        ft_unexp     = 'Unexpected',
        ft_missed    = 'Missed',
    ),
    'es': dict(
        title        = 'Bancos de prueba etiquetados — Detecciones por Tipo de Problema',
        xlabel       = 'Número de instancias (prueba, tipo de problema)',
        lbl_correct  = 'Esperados',
        lbl_unexp    = 'Inesperados',
        lbl_missed   = 'No detectados',
        ft_instances = 'Instancias',
        ft_detected  = 'Detectados',
        ft_unexp     = 'Inesperados',
        ft_missed    = 'No detectados',
    ),
}


# ── data loading ──────────────────────────────────────────────────────────────

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

def build_layout(counts: pd.DataFrame, lang: str):
    issue_map = ISSUE_LABELS[lang]
    bar_specs = []
    clusters  = []
    y = 0.0

    for ds in DATASET_ORDER:
        if ds not in counts.index.get_level_values('dataset'):
            continue

        ds_data = counts.loc[ds].copy()
        ds_data['_total'] = ds_data.sum(axis=1)
        ds_data = ds_data.sort_values('_total', ascending=True)

        y_lo = y
        for issue_type, row in ds_data.iterrows():
            bar_specs.append(dict(
                y       = y,
                label   = issue_map.get(issue_type, issue_type),
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

def plot(counts: pd.DataFrame, output: Path, *, color: bool = False, lang: str = 'en') -> None:
    pal = PALETTE_C if color else PALETTE_GS
    s   = STRINGS[lang]
    bar_specs, clusters = build_layout(counts, lang)

    x_max = max(b['c'] + b['u'] + b['m'] for b in bar_specs)
    fig_h = max(4.0, len(bar_specs) * (BAR_HEIGHT + INTRA_GAP) + len(clusters) * INTER_GAP + 0.5)
    fig, ax = plt.subplots(figsize=(9, fig_h))

    seen_correct = seen_unexp = seen_missed = False

    for b in bar_specs:
        left = 0.0
        y, c, u, m = b['y'], b['c'], b['u'], b['m']

        if c > 0:
            lbl = s['lbl_correct'] if not seen_correct else ''
            seen_correct = True
            ax.barh(y, c, height=BAR_HEIGHT, left=left,
                    color=pal['correct'], label=lbl)
            if c >= 4:
                ax.text(left + c / 2, y, str(c), va='center', ha='center',
                        fontsize=8.5, color='white', fontweight='bold')
            left += c

        if u > 0:
            lbl = s['lbl_unexp'] if not seen_unexp else ''
            seen_unexp = True
            ax.barh(y, u, height=BAR_HEIGHT, left=left,
                    color=pal['unexpected'], label=lbl)
            if u >= 2:
                ax.text(left + u / 2, y, str(u), va='center', ha='center',
                        fontsize=8.5, color='white', fontweight='bold')
            left += u

        if m > 0:
            lbl = s['lbl_missed'] if not seen_missed else ''
            seen_missed = True
            ax.barh(y, m, height=BAR_HEIGHT, left=left,
                    color=pal['missed'], hatch='///', edgecolor=pal['missed_edge'], label=lbl)
            if m >= 2:
                ax.text(left + m / 2, y, str(m), va='center', ha='center',
                        fontsize=8.5, color=pal['text_dark'], fontweight='bold')
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
        ax.text(-0.18, y_mid, cl['name'],
                va='center', ha='center', fontsize=11, fontweight='bold',
                rotation=90, transform=ax.get_yaxis_transform())
        if cl is not clusters[-1]:
            sep_y = cl['y_hi'] + INTER_GAP / 2 + INTRA_GAP / 2
            ax.axhline(sep_y, color='#cccccc', linewidth=0.8, linestyle='--')

    # ── axes decoration ───────────────────────────────────────────────────────
    ax.set_title(s['title'], fontsize=13, fontweight='bold', pad=10)
    ax.set_xlabel(s['xlabel'], fontsize=11)
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
        f"{s['ft_instances']}: {total_c + total_u + total_m}   ·   "
        f"{s['ft_detected']}: {total_c}   ·   "
        f"{s['ft_unexp']}: {total_u}   ·   "
        f"{s['ft_missed']}: {total_m}"
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
    parser.add_argument('--csv', type=Path,
        default=here / 'results' / 'issue_breakdown_labeled_results.csv')
    parser.add_argument('--output', type=Path, default=None,
        help='Output image path (auto-named from --color/--lang if omitted)')
    parser.add_argument('--color', action='store_true',
        help='Use Alecci syntax-highlighting color palette instead of grayscale')
    parser.add_argument('--lang', choices=['en', 'es'], default='en',
        help='Label language (default: en)')
    args = parser.parse_args()

    if args.output is None:
        stem = 'labeled_detection_chart'
        if args.color:
            stem += '_color'
        if args.lang == 'es':
            stem += '_es'
        args.output = here / 'results' / f'{stem}.png'

    if not args.csv.exists():
        print(f"Error: CSV not found: {args.csv}")
        raise SystemExit(1)

    counts = load(args.csv)
    plot(counts, args.output, color=args.color, lang=args.lang)


if __name__ == '__main__':
    main()
