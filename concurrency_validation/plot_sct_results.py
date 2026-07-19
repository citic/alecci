#!/usr/bin/env python3
"""
plot_sct_results.py
Generate a stacked bar chart of SCTBench detection results by signal type.

Each bar represents one detection mechanism (Data Race, Deadlock, Crash, Timeout).
The stack shows:
  - Correct  : expected detections  (program labeled 'bug' and signal triggered)
  - Unexpected: detected but not expected (program labeled 'none' = false positive)

A program can appear in multiple bars if multiple signals fired (e.g. din_phil_sat
triggers both TSan data_race and TSan deadlock).

Usage:
  python3 concurrency_validation/plot_sct_results.py
  python3 concurrency_validation/plot_sct_results.py --color
  python3 concurrency_validation/plot_sct_results.py --color --lang es
  python3 concurrency_validation/plot_sct_results.py --csv path/to/sct_results.csv
  python3 concurrency_validation/plot_sct_results.py --output path/to/chart.png
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
    expected    = '#575353',
    unexpected  = '#999999',
    missed      = '#bbbbbb',
    missed_edge = '#777777',
    text_dark   = '#333333',
)
# Soft/desaturated variants of the Alecci syntax-highlighting colours:
#   expected   ← SteelBlue   (control-flow keywords, class 1)
#   unexpected ← MediumOrchid (concurrency-primitive keywords, class 3)
#   missed     ← Peru         (built-in function keywords, class 4)
PALETTE_C = dict(
    expected    = '#5B8FB8',
    unexpected  = '#A870BA',
    missed      = '#CB9050',
    missed_edge = '#8A5C20',
    text_dark   = '#4A2800',
)

BAR_HEIGHT = 0.35

SIGNAL_KEYS = ['data_race', 'deadlock', 'crash', 'timeout']

SIGNAL_LABELS = {
    'en': {
        'data_race': 'Data Race\n(TSan)',
        'deadlock':  'Deadlock\n(TSan)',
        'crash':     'Crash\n(Assert / Abort)',
        'timeout':   'Timeout\n(Hung / Deadlock)',
    },
    'es': {
        'data_race': 'Condición de carrera\n(TSan)',
        'deadlock':  'Bloqueo mutuo\n(TSan)',
        'crash':     'Fallo\n(Assert / Abort)',
        'timeout':   'Tiempo agotado\n(Posible bloqueo)',
    },
}

STRINGS = {
    'en': dict(
        title        = 'SCTBench — Detections by Signal Type',
        xlabel       = 'Number of Programs',
        lbl_expected = 'Expected',
        lbl_unexp    = 'Unexpected',
        lbl_missed   = 'Missed',
        missed_ytick = 'Missed\n(not detected)',
        footer       = 'Total: {total} benchmarks   ·   Buggy: {buggy} (detected {det}, missed {miss})   ·   Correct: {correct}',
    ),
    'es': dict(
        title        = 'SCTBench — Detecciones por Tipo de Señal',
        xlabel       = 'Número de programas',
        lbl_expected = 'Esperados',
        lbl_unexp    = 'Inesperados',
        lbl_missed   = 'No detectados',
        missed_ytick = 'No detectados\n(sin detectar)',
        footer       = 'Total: {total} benchmarks   ·   Con error: {buggy} (detectados {det}, no detectados {miss})   ·   Correctos: {correct}',
    ),
}


# ── data helpers ──────────────────────────────────────────────────────────────

def parse_pipe(cell: str) -> set:
    """Split a pipe-separated cell into a set, dropping the 'none' sentinel."""
    return {x.strip() for x in str(cell).split('|') if x.strip() not in ('none', '')}


def load(csv_path: Path) -> pd.DataFrame:
    df = pd.read_csv(csv_path)
    df['detected_set'] = df['detected_issues'].apply(parse_pipe)
    df['is_buggy']   = df['expected_issues'] == 'bug'
    df['is_correct'] = df['expected_issues'] == 'none'
    df['crash']      = df['crash_occurred']  == 'yes'
    df['timed_out']  = df['timeout_occurred'] == 'yes'
    return df


def count_signal(df: pd.DataFrame, signal: str):
    """Return (expected, unexpected) program counts for a detection signal."""
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

def plot(df: pd.DataFrame, output: Path, *, color: bool = False, lang: str = 'en') -> None:
    pal = PALETTE_C if color else PALETTE_GS
    s   = STRINGS[lang]
    sig_labels = SIGNAL_LABELS[lang]

    total_buggy   = int(df['is_buggy'].sum())
    total_correct = int(df['is_correct'].sum())
    n_missed      = int((df['is_buggy'] & (df['status'] == 'MISS')).sum())
    detected      = total_buggy - n_missed

    labels       = [sig_labels[k] for k in SIGNAL_KEYS]
    exp_counts   = []
    unexp_counts = []
    for key in SIGNAL_KEYS:
        e, u = count_signal(df, key)
        exp_counts.append(e)
        unexp_counts.append(u)

    n         = len(labels)
    y_signals = list(range(n))
    y_missed  = n + 0.6

    x_max = max(
        max(e + u for e, u in zip(exp_counts, unexp_counts)),
        n_missed,
    )

    fig, ax = plt.subplots(figsize=(8, 4.5))

    # ── detection signal bars ─────────────────────────────────────────────────
    seen_exp = seen_unexp = False
    for i, (e, u) in enumerate(zip(exp_counts, unexp_counts)):
        if e > 0:
            lbl = s['lbl_expected'] if not seen_exp else ''
            seen_exp = True
            ax.barh(i, e, height=BAR_HEIGHT, left=0,
                    color=pal['expected'], label=lbl)
        if u > 0:
            lbl = s['lbl_unexp'] if not seen_unexp else ''
            seen_unexp = True
            ax.barh(i, u, height=BAR_HEIGHT, left=e,
                    color=pal['unexpected'], label=lbl)

        total = e + u
        if total > 0:
            ax.text(total + 0.25, i, str(total),
                    va='center', ha='left', fontsize=10, fontweight='bold')
        if e > 0 and u > 0:
            ax.text(e / 2, i, str(e),
                    va='center', ha='center', fontsize=9,
                    color='white', fontweight='bold')

    # ── missed bar ────────────────────────────────────────────────────────────
    lbl_missed = s['lbl_missed']
    ax.barh(y_missed, n_missed, height=BAR_HEIGHT,
            color=pal['missed'], hatch='///', edgecolor=pal['missed_edge'], label=lbl_missed)
    ax.text(n_missed + 0.25, y_missed, str(n_missed),
            va='center', ha='left', fontsize=10, fontweight='bold')

    # ── axes formatting ───────────────────────────────────────────────────────
    all_y      = y_signals + [y_missed]
    all_labels = labels    + [s['missed_ytick']]

    ax.set_title(s['title'], fontsize=13, fontweight='bold', pad=10)
    ax.set_xlabel(s['xlabel'], fontsize=11)
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
    ax.axhline(n + 0.1, color='#cccccc', linewidth=0.8, linestyle=':')
    ax.legend(fontsize=11, loc='upper right', framealpha=0.9)

    # ── footer ────────────────────────────────────────────────────────────────
    footer = s['footer'].format(
        total=total_buggy + total_correct,
        buggy=total_buggy,
        det=detected,
        miss=n_missed,
        correct=total_correct,
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
        description='Plot SCTBench detection results as a stacked bar chart.'
    )
    parser.add_argument('--csv', type=Path,
        default=here / 'results' / 'sct_results.csv',
        help='Path to sct_results.csv')
    parser.add_argument('--output', type=Path, default=None,
        help='Output image path (auto-named from --color/--lang if omitted)')
    parser.add_argument('--color', action='store_true',
        help='Use Alecci syntax-highlighting color palette instead of grayscale')
    parser.add_argument('--lang', choices=['en', 'es'], default='en',
        help='Label language (default: en)')
    args = parser.parse_args()

    if args.output is None:
        stem = 'sct_detection_chart'
        if args.color:
            stem += '_color'
        if args.lang == 'es':
            stem += '_es'
        args.output = here / 'results' / f'{stem}.png'

    if not args.csv.exists():
        print(f"Error: CSV not found: {args.csv}", flush=True)
        raise SystemExit(1)

    df = load(args.csv)
    plot(df, args.output, color=args.color, lang=args.lang)


if __name__ == '__main__':
    main()
