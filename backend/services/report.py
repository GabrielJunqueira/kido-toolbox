"""
AOI Report Generator Service
Fetches visitor data from Kido API and generates PDF reports with charts.
"""

import io
import os
import json
import base64
from datetime import datetime
from typing import List, Dict, Any, Optional, Tuple
from concurrent.futures import ThreadPoolExecutor, as_completed

import pandas as pd
import requests
import numpy as np
import matplotlib
matplotlib.use('Agg')  # Non-interactive backend
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from matplotlib.patches import Patch
from matplotlib.backends.backend_pdf import PdfPages
from dateutil.relativedelta import relativedelta


# ── Color palette ──────────────────────────────────────────────────────────────
CORES = ['#E63946', '#F77F00', '#FCBF49', '#06A77D', '#118AB2', '#073B4C',
         '#D62828', '#F4A261', '#2A9D8F', '#E76F51', '#8338EC', '#3A86FF']


def _paleta(n):
    if n <= len(CORES):
        return CORES[:n]
    cmap = plt.cm.get_cmap('tab20')
    return [matplotlib.colors.rgb2hex(cmap(i)) for i in np.linspace(0, 1, n)]


def _grid_layout(n):
    for rows, cols in [(1, 1), (1, 2), (2, 2), (2, 3), (3, 3), (3, 4), (4, 4)]:
        if rows * cols >= n:
            return rows, cols
    return int(np.ceil(n / 4)), 4


# ══════════════════════════════════════════════════════════════════════════════
# 1. DATA FETCHING
# ══════════════════════════════════════════════════════════════════════════════

def _get_data(token: str, root_url: str, project_id: str, aoi_id: str,
              start_date: str, end_date: str, dataset: str,
              session: Optional[requests.Session] = None) -> Optional[pd.DataFrame]:
    """Fetch a single dataset from the Kido API."""
    base_url = root_url.replace('/v1/', '/v2/').replace('/v1', '/v2')
    if not base_url.endswith('/'):
        base_url += '/'

    url = (f"{base_url}areas_of_interest/{project_id}/"
           f"dashboard/visitors/{aoi_id}/{start_date}/{end_date}/csv/{dataset}")
    headers = {
        'accept': 'application/json',
        'Authorization': f'Bearer {token}'
    }
    params = {'metric': 'wanderers', 'alt_engine': 'false'}

    http = session or requests
    try:
        response = http.get(url, headers=headers, params=params, timeout=90)
        if response.status_code == 200:
            csv_text = response.json() if response.text.startswith('"') else response.text
            if isinstance(csv_text, str) and csv_text.startswith('"'):
                try:
                    csv_text = json.loads(csv_text)
                except:
                    pass
            df = pd.read_csv(io.StringIO(csv_text))
            return df
        else:
            print(f"  ❌ Error ({response.status_code}) in {dataset} [{start_date}]: {response.text[:200]}")
            return None
    except Exception as e:
        print(f"  ❌ Exception in {dataset} [{start_date}]: {e}")
        return None


def _fetch_month(token: str, root_url: str, project_id: str, aoi_id: str,
                 month: str, session: requests.Session) -> dict:
    """Fetch all datasets for a single month. Designed to run inside a thread."""
    dt = datetime.strptime(month, "%Y-%m")
    start_date = dt.replace(day=1).strftime("%Y-%m-%d")
    last_day = (dt + relativedelta(months=1) - relativedelta(days=1))
    end_date = last_day.strftime("%Y-%m-%d")

    print(f"  📆 Processing {month} ({start_date} → {end_date})...")

    df_daily = _get_data(token, root_url, project_id, aoi_id,
                         start_date, end_date, "visitors_by_date_level", session)
    df_uv = _get_data(token, root_url, project_id, aoi_id,
                      start_date, end_date, "unique_visitors", session)
    df_uvs = _get_data(token, root_url, project_id, aoi_id,
                       start_date, end_date, "unique_visits", session)

    uv_val = None
    if df_uv is not None:
        if "visitors" in df_uv.columns:
            uv_val = df_uv["visitors"].sum()
        elif "visits" in df_uv.columns:
            uv_val = df_uv["visits"].sum()

    uvs_val = None
    if df_uvs is not None:
        if "visits" in df_uvs.columns:
            uvs_val = df_uvs["visits"].sum()
        elif "visitors" in df_uvs.columns:
            uvs_val = df_uvs["visitors"].sum()

    return {
        "month": month,
        "df_daily": df_daily,
        "unique_visitors": uv_val,
        "unique_visits": uvs_val
    }


def fetch_all_data(token: str, root_url: str, project_id: str, aoi_id: str,
                   months: List[str]) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """
    Fetch daily and monthly visitor data for all selected months in parallel.

    Returns:
        (df_daily, df_monthly) DataFrames
    """
    daily_frames = []
    monthly_rows = []
    unique_months = sorted(set(months))

    # Use a session for connection pooling + ThreadPool for parallelism
    session = requests.Session()
    adapter = requests.adapters.HTTPAdapter(pool_connections=10, pool_maxsize=10)
    session.mount('https://', adapter)
    session.mount('http://', adapter)

    with ThreadPoolExecutor(max_workers=min(6, len(unique_months))) as executor:
        futures = {
            executor.submit(_fetch_month, token, root_url, project_id, aoi_id, m, session): m
            for m in unique_months
        }
        results = {}
        for future in as_completed(futures):
            result = future.result()
            results[result["month"]] = result

    # Reassemble in sorted order
    for month in unique_months:
        result = results[month]
        if result["df_daily"] is not None:
            daily_frames.append(result["df_daily"])
        monthly_rows.append({
            "month": month,
            "unique_visitors": result["unique_visitors"],
            "unique_visits": result["unique_visits"]
        })

    session.close()

    # Consolidate daily data
    if daily_frames:
        df_daily_final = pd.concat(daily_frames, ignore_index=True)
        if 'date' in df_daily_final.columns:
            df_daily_final['date'] = pd.to_datetime(df_daily_final['date'])
            col_metric = 'visitors' if 'visitors' in df_daily_final.columns else 'visits'
            if col_metric in df_daily_final.columns:
                df_daily_final = (
                    df_daily_final.groupby('date')[col_metric].sum()
                    .reset_index().sort_values('date')
                )
                df_daily_final.rename(columns={col_metric: 'visitors'}, inplace=True)
    else:
        df_daily_final = pd.DataFrame(columns=['date', 'visitors'])

    df_monthly_final = pd.DataFrame(monthly_rows)

    return df_daily_final, df_monthly_final


# ══════════════════════════════════════════════════════════════════════════════
# 2. CHART GENERATION (preserving original style)
# ══════════════════════════════════════════════════════════════════════════════

def _prepare(data: pd.DataFrame) -> pd.DataFrame:
    df = data[['date', 'visitors']].copy()
    df['date'] = pd.to_datetime(df['date'])
    df = df.sort_values('date').reset_index(drop=True)
    df['year_month'] = df['date'].dt.to_period('M')
    df['is_weekend'] = df['date'].dt.dayofweek >= 5
    return df


def _chart_daily_bars(df: pd.DataFrame, cmap: dict, figsize=(20, 6), dpi=150):
    """Daily visitors bar chart with moving average."""
    df = df.copy()
    df['color'] = df['year_month'].astype(str).map(cmap)

    fig, ax = plt.subplots(figsize=figsize, dpi=dpi)
    ax.bar(df['date'], df['visitors'], width=0.8, color=df['color'],
           edgecolor='none', alpha=0.85)

    ma7 = df['visitors'].rolling(7, center=True).mean()
    ax.plot(df['date'], ma7, lw=2.5, color='black', linestyle='--',
            alpha=0.7, label='7-day Moving Avg')

    n = len(df)
    interval = 3 if n <= 60 else (7 if n <= 120 else 14)
    ax.xaxis.set_major_formatter(mdates.DateFormatter('%d/%b'))
    ax.xaxis.set_major_locator(mdates.DayLocator(interval=interval))
    plt.setp(ax.xaxis.get_majorticklabels(), rotation=45, ha='right')

    ax.set_ylabel('Number of Visitors', fontsize=12, fontweight='bold')
    ax.set_xlabel('Date', fontsize=12, fontweight='bold')
    ax.set_title(
        f"Daily Visitors ({df['date'].min().strftime('%b/%Y')} to "
        f"{df['date'].max().strftime('%b/%Y')})",
        fontsize=14, fontweight='bold', pad=15
    )
    ax.grid(True, alpha=0.3, axis='y', linestyle='--')

    legend = [Patch(facecolor=cmap[str(ym)],
                    label=pd.Period(ym).strftime('%b/%y'), alpha=0.85)
              for ym in sorted(df['year_month'].unique())]
    legend.append(plt.Line2D([0], [0], color='black', lw=2.5,
                             linestyle='--', label='7-day Moving Avg'))
    ax.legend(handles=legend, loc='upper right',
              ncol=min(len(legend), 8), framealpha=0.95)

    plt.tight_layout()
    return fig


def _chart_monthly_panels(df: pd.DataFrame, cmap: dict, dpi=150):
    """Monthly breakdown panels with consistent Y scale."""
    unique_months = sorted(df['year_month'].unique())
    n = len(unique_months)
    rows, cols = _grid_layout(n)
    figsize = (6 * cols, 4.5 * rows)
    fig, axes = plt.subplots(rows, cols, figsize=figsize, dpi=dpi)
    axes = np.array([axes]).flatten() if n == 1 else np.array(axes).flatten()

    y_max = df['visitors'].max() * 1.05

    for idx, ym in enumerate(unique_months):
        ax = axes[idx]
        dm = df[df['year_month'] == ym].copy()
        cor = cmap[str(ym)]

        ax.bar(dm['date'], dm['visitors'], width=0.7, color=cor,
               edgecolor='black', lw=0.5, alpha=0.8)

        media = dm['visitors'].mean()
        ax.axhline(media, color='red', linestyle='--', lw=2, alpha=0.7,
                   label=f'Mean: {media:,.0f}')

        fds = dm[dm['is_weekend']]
        if len(fds):
            ax.scatter(fds['date'], fds['visitors'], color='darkred',
                       s=80, zorder=5, alpha=0.6, marker='o', label='Weekend')

        ax.set_title(pd.Period(ym).strftime('%B %Y'),
                     fontsize=13, fontweight='bold', pad=10)
        ax.set_ylabel('Visitors', fontsize=10, fontweight='bold')
        ax.set_xlabel('Day', fontsize=10, fontweight='bold')
        ax.set_ylim(0, y_max)
        ax.xaxis.set_major_formatter(mdates.DateFormatter('%d'))
        ax.xaxis.set_major_locator(
            mdates.DayLocator(interval=5 if len(dm) > 28 else 3))
        ax.grid(True, alpha=0.3, axis='y', linestyle='--')
        ax.legend(loc='upper right', fontsize=8, framealpha=0.9)

        ax.text(0.02, 0.98,
                f"Max: {dm['visitors'].max():,.0f}\nMin: {dm['visitors'].min():,.0f}",
                transform=ax.transAxes, fontsize=8, va='top',
                bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.5))

    for idx in range(n, len(axes)):
        axes[idx].set_visible(False)

    fig.suptitle(
        f"Daily Visitors by Month "
        f"({df['date'].min().strftime('%b/%Y')} to "
        f"{df['date'].max().strftime('%b/%Y')}) — Same Scale",
        fontsize=16, fontweight='bold', y=0.995
    )
    plt.tight_layout()
    return fig


def _build_statistics_text(df: pd.DataFrame, df_monthly: pd.DataFrame) -> str:
    """Build statistics summary as formatted text."""
    lines = []
    sep = "=" * 60

    lines.append(f"GENERAL STATISTICS")
    lines.append(sep)
    lines.append(f"Period      : {df['date'].min().strftime('%d/%m/%Y')} to {df['date'].max().strftime('%d/%m/%Y')}")
    lines.append(f"Total days  : {len(df)}")
    lines.append(f"Daily mean  : {df['visitors'].mean():>12,.0f}")
    lines.append(f"Median      : {df['visitors'].median():>12,.0f}")
    lines.append(f"Std. dev.   : {df['visitors'].std():>12,.0f}")
    cv = df['visitors'].std() / df['visitors'].mean() * 100 if df['visitors'].mean() > 0 else 0
    lines.append(f"Coeff. var. : {cv:>11.1f}%")
    lines.append(f"Maximum     : {df['visitors'].max():,.0f}  ({df.loc[df['visitors'].idxmax(), 'date'].strftime('%d/%m/%Y')})")
    lines.append(f"Minimum     : {df['visitors'].min():,.0f}  ({df.loc[df['visitors'].idxmin(), 'date'].strftime('%d/%m/%Y')})")

    lines.append("")
    lines.append(f"MONTHLY STATISTICS")
    lines.append(sep)

    for ym in sorted(df['year_month'].unique()):
        dm = df[df['year_month'] == ym]
        lbl = pd.Period(ym).strftime('%B %Y').upper()
        wd = dm[~dm['is_weekend']]['visitors'].mean()
        we = dm[dm['is_weekend']]['visitors'].mean()

        lines.append(f"\n{lbl} ({len(dm)} days)")
        lines.append(f"  Mean        : {dm['visitors'].mean():>10,.0f}")
        lines.append(f"  Median      : {dm['visitors'].median():>10,.0f}")
        lines.append(f"  Maximum     : {dm['visitors'].max():>10,.0f}  ({dm.loc[dm['visitors'].idxmax(), 'date'].strftime('%d/%m')})")
        lines.append(f"  Minimum     : {dm['visitors'].min():>10,.0f}  ({dm.loc[dm['visitors'].idxmin(), 'date'].strftime('%d/%m')})")
        if not (pd.isna(wd) or pd.isna(we) or we == 0):
            lines.append(f"  Weekday avg : {wd:>10,.0f}")
            lines.append(f"  Weekend avg : {we:>10,.0f}  ({(wd - we) / we * 100:+.1f}%)")

    if df_monthly is not None and not df_monthly.empty:
        lines.append("")
        lines.append(f"MONTHLY DATA (unique_visitors / unique_visits)")
        lines.append(sep)
        for _, row in df_monthly.iterrows():
            uv = f"{row['unique_visitors']:,.0f}" if pd.notna(row.get('unique_visitors')) else "N/A"
            uvs = f"{row['unique_visits']:,.0f}" if pd.notna(row.get('unique_visits')) else "N/A"
            lines.append(f"  {row['month']}  →  Visitors: {uv}  |  Visits: {uvs}")

    return "\n".join(lines)


def _chart_stats_page(df: pd.DataFrame, df_monthly: pd.DataFrame, dpi=150):
    """Create a statistics summary page as a matplotlib figure."""
    text = _build_statistics_text(df, df_monthly)

    fig, ax = plt.subplots(figsize=(12, 8), dpi=dpi)
    ax.axis('off')
    ax.text(0.05, 0.95, text,
            transform=ax.transAxes, fontsize=9,
            verticalalignment='top',
            fontfamily='monospace',
            bbox=dict(boxstyle='round', facecolor='#f8f9fa', alpha=0.9, pad=1))
    fig.suptitle("Statistical Summary", fontsize=16, fontweight='bold', y=0.98)
    plt.tight_layout()
    return fig


def _chart_title_page(project_id: str, aoi_id: str, months: List[str], dpi=150):
    """Create a title page for the PDF."""
    fig, ax = plt.subplots(figsize=(12, 8), dpi=dpi)
    ax.axis('off')

    # Title
    ax.text(0.5, 0.70, "Visitor Analysis Report",
            transform=ax.transAxes, fontsize=24, fontweight='bold',
            ha='center', va='center', color='#1a1a2e')

    ax.text(0.5, 0.62, "Kido Dynamics",
            transform=ax.transAxes, fontsize=16,
            ha='center', va='center', color='#6366f1')

    # Info box
    info = (
        f"Project ID:  {project_id}\n"
        f"AOI ID:      {aoi_id}\n"
        f"Period:      {months[0]} to {months[-1]}\n"
        f"Months:      {len(months)}\n"
        f"Generated:   {datetime.now().strftime('%d/%m/%Y %H:%M')}"
    )
    ax.text(0.5, 0.40, info,
            transform=ax.transAxes, fontsize=12,
            ha='center', va='center',
            fontfamily='monospace',
            bbox=dict(boxstyle='round,pad=1', facecolor='#f0f0ff',
                      edgecolor='#6366f1', alpha=0.8))

    plt.tight_layout()
    return fig


# ══════════════════════════════════════════════════════════════════════════════
# 3. HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def _fig_to_base64(fig, dpi=150) -> str:
    """Convert a matplotlib figure to a base64-encoded PNG string."""
    buf = io.BytesIO()
    fig.savefig(buf, format='png', dpi=dpi, bbox_inches='tight',
                facecolor='white', edgecolor='none')
    buf.seek(0)
    return base64.b64encode(buf.getvalue()).decode('utf-8')


def _build_monthly_stats(df: pd.DataFrame) -> List[dict]:
    """Build per-month statistics as structured data."""
    stats = []
    for ym in sorted(df['year_month'].unique()):
        dm = df[df['year_month'] == ym]
        wd = dm[~dm['is_weekend']]['visitors'].mean()
        we = dm[dm['is_weekend']]['visitors'].mean()
        s = {
            "month": pd.Period(ym).strftime('%B %Y'),
            "days": int(len(dm)),
            "mean": round(float(dm['visitors'].mean()), 0),
            "median": round(float(dm['visitors'].median()), 0),
            "max": round(float(dm['visitors'].max()), 0),
            "min": round(float(dm['visitors'].min()), 0),
            "max_date": dm.loc[dm['visitors'].idxmax(), 'date'].strftime('%d/%m'),
            "min_date": dm.loc[dm['visitors'].idxmin(), 'date'].strftime('%d/%m'),
            "weekday_mean": round(float(wd), 0) if not pd.isna(wd) else None,
            "weekend_mean": round(float(we), 0) if not pd.isna(we) else None,
        }
        stats.append(s)
    return stats


# ══════════════════════════════════════════════════════════════════════════════
# 4. PDF + INLINE IMAGE GENERATION
# ══════════════════════════════════════════════════════════════════════════════

def generate_pdf_report(token: str, root_url: str, project_id: str,
                        aoi_id: str, months: List[str]) -> Tuple[bytes, dict]:
    """
    Generate a complete PDF report + inline chart images.

    Returns:
        (pdf_bytes, summary_dict_with_images)
    """
    print(f"📊 Starting report generation for {project_id} / {aoi_id}")
    print(f"   Months: {', '.join(months)}")

    # 1. Fetch data
    df_daily, df_monthly = fetch_all_data(token, root_url, project_id, aoi_id, months)

    if df_daily.empty:
        raise ValueError("No daily data was returned from the API. "
                         "Check if the project is processed and the AOI ID is correct.")

    # 2. Prepare data
    df = _prepare(df_daily)
    ums = sorted(df['year_month'].unique())
    cmap = {str(ym): c for ym, c in zip(ums, _paleta(len(ums)))}

    # 3. Generate charts and capture as base64
    chart_images = {}

    fig_bars = _chart_daily_bars(df, cmap)
    chart_images['daily_chart'] = _fig_to_base64(fig_bars)

    fig_monthly_panels = _chart_monthly_panels(df, cmap)
    chart_images['monthly_chart'] = _fig_to_base64(fig_monthly_panels)

    # 4. Generate PDF
    pdf_buffer = io.BytesIO()
    with PdfPages(pdf_buffer) as pdf:
        # Title page
        fig_title = _chart_title_page(project_id, aoi_id, months)
        pdf.savefig(fig_title, bbox_inches='tight')
        plt.close(fig_title)

        # Daily bars (reuse)
        pdf.savefig(fig_bars, bbox_inches='tight')
        plt.close(fig_bars)

        # Monthly panels (reuse)
        pdf.savefig(fig_monthly_panels, bbox_inches='tight')
        plt.close(fig_monthly_panels)

        # Statistics page
        fig_stats = _chart_stats_page(df, df_monthly)
        pdf.savefig(fig_stats, bbox_inches='tight')
        plt.close(fig_stats)

    pdf_bytes = pdf_buffer.getvalue()

    # 5. Build CSV base64 for download
    csv_daily_buf = io.StringIO()
    df_daily.to_csv(csv_daily_buf, index=False)
    csv_daily_b64 = base64.b64encode(csv_daily_buf.getvalue().encode('utf-8')).decode('utf-8')

    csv_monthly_buf = io.StringIO()
    df_monthly.to_csv(csv_monthly_buf, index=False)
    csv_monthly_b64 = base64.b64encode(csv_monthly_buf.getvalue().encode('utf-8')).decode('utf-8')

    # 6. Build structured summary
    cv = df['visitors'].std() / df['visitors'].mean() * 100 if df['visitors'].mean() > 0 else 0

    summary = {
        "total_days": int(len(df)),
        "months_processed": len(months),
        "daily_mean": round(float(df['visitors'].mean()), 0),
        "daily_median": round(float(df['visitors'].median()), 0),
        "daily_max": round(float(df['visitors'].max()), 0),
        "daily_min": round(float(df['visitors'].min()), 0),
        "daily_std": round(float(df['visitors'].std()), 0),
        "daily_cv": round(float(cv), 1),
        "max_date": df.loc[df['visitors'].idxmax(), 'date'].strftime('%d/%m/%Y'),
        "min_date": df.loc[df['visitors'].idxmin(), 'date'].strftime('%d/%m/%Y'),
        "period_start": df['date'].min().strftime('%d/%m/%Y'),
        "period_end": df['date'].max().strftime('%d/%m/%Y'),
        "monthly_stats": _build_monthly_stats(df),
        "monthly_data": df_monthly.to_dict(orient='records') if not df_monthly.empty else [],
        "pdf_size_kb": round(len(pdf_bytes) / 1024, 1),
        "charts": chart_images,
        "csv_daily": csv_daily_b64,
        "csv_monthly": csv_monthly_b64
    }

    print(f"✅ Report generated: {summary['pdf_size_kb']} KB, {summary['total_days']} days")
    return pdf_bytes, summary
