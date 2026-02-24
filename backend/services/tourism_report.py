"""
AOI Tourism Report Service
Fetches tourism data from Kido API and generates charts for visitors, tourists, and hikers.
"""

import io
import json
import base64
from datetime import datetime
from typing import List, Optional, Tuple
from concurrent.futures import ThreadPoolExecutor, as_completed

import pandas as pd
import requests
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from matplotlib.patches import Patch
from dateutil.relativedelta import relativedelta


# ── Color palettes per section ─────────────────────────────────────────────────
# Visitors (alternating dark/bright greens & teals for max contrast)
PALETTE_VISITORS = ['#047857', '#5eead4', '#065f46', '#2dd4bf', '#0d9488', '#a7f3d0',
                    '#134e4a', '#6ee7b7', '#0f766e', '#99f6e4', '#115e59', '#14b8a6']

# Tourists (alternating dark navy / bright sky / violet for max contrast)
PALETTE_TOURISTS = ['#1e3a8a', '#93c5fd', '#4338ca', '#60a5fa', '#1e40af', '#c7d2fe',
                    '#312e81', '#a5b4fc', '#1d4ed8', '#bfdbfe', '#3730a3', '#818cf8']

# Hikers (alternating deep red / bright orange / gold for max contrast)
PALETTE_HIKERS = ['#991b1b', '#fbbf24', '#dc2626', '#fb923c', '#b91c1c', '#fde68a',
                  '#9a3412', '#f59e0b', '#c2410c', '#fdba74', '#7c2d12', '#f97316']


def _pick_palette(section: str, n: int) -> list:
    """Pick n colors from the section palette, cycling if needed."""
    if section == 'visitors':
        base = PALETTE_VISITORS
    elif section == 'tourist':
        base = PALETTE_TOURISTS
    elif section == 'hiker':
        base = PALETTE_HIKERS
    else:
        base = PALETTE_VISITORS
    return [base[i % len(base)] for i in range(n)]


# ══════════════════════════════════════════════════════════════════════════════
# 1. DATA FETCHING
# ══════════════════════════════════════════════════════════════════════════════

def _get_tourism_data(token: str, root_url: str, project_id: str, aoi_id: str,
                      start_date: str, end_date: str,
                      session: Optional[requests.Session] = None) -> Optional[pd.DataFrame]:
    """Fetch tourism visitors_by_date_level dataset from the Kido API."""
    base_url = root_url.replace('/v1/', '/v2/').replace('/v1', '/v2')
    if not base_url.endswith('/'):
        base_url += '/'

    url = (f"{base_url}areas_of_interest/{project_id}/"
           f"dashboard/tourism/{aoi_id}/{start_date}/{end_date}/csv/visitors_by_date_level")
    headers = {
        'accept': 'application/json',
        'Authorization': f'Bearer {token}'
    }
    params = {'aoi_ref': 'AOI-REF', 'alt_engine': 'false'}

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
            print(f"  ❌ Error ({response.status_code}) tourism [{start_date}]: {response.text[:200]}")
            return None
    except Exception as e:
        print(f"  ❌ Exception tourism [{start_date}]: {e}")
        return None


def _fetch_month(token: str, root_url: str, project_id: str, aoi_id: str,
                 month: str, session: requests.Session) -> dict:
    """Fetch tourism data for a single month."""
    dt = datetime.strptime(month, "%Y-%m")
    start_date = dt.replace(day=1).strftime("%Y-%m-%d")
    last_day = (dt + relativedelta(months=1) - relativedelta(days=1))
    end_date = last_day.strftime("%Y-%m-%d")

    print(f"  📆 Processing tourism {month} ({start_date} → {end_date})...")

    df = _get_tourism_data(token, root_url, project_id, aoi_id,
                           start_date, end_date, session)

    return {"month": month, "df": df}


def fetch_all_tourism_data(token: str, root_url: str, project_id: str,
                           aoi_id: str, months: List[str]) -> pd.DataFrame:
    """
    Fetch tourism data for all selected months in parallel.
    Returns a consolidated DataFrame with columns: visitor_type, visitor_level, date, visitors
    """
    frames = []
    unique_months = sorted(set(months))

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

    for month in unique_months:
        result = results[month]
        if result["df"] is not None:
            frames.append(result["df"])

    session.close()

    if frames:
        df = pd.concat(frames, ignore_index=True)
        df['date'] = pd.to_datetime(df['date'])
        # Treat '<10' values as 2
        df['visitors'] = pd.to_numeric(df['visitors'].replace('<10', 2), errors='coerce').fillna(0)
        df = df.sort_values('date').reset_index(drop=True)
        return df
    else:
        return pd.DataFrame(columns=['visitor_type', 'visitor_level', 'date', 'visitors'])


# ══════════════════════════════════════════════════════════════════════════════
# 2. DATA PROCESSING
# ══════════════════════════════════════════════════════════════════════════════

def _build_series(df: pd.DataFrame) -> dict:
    """
    Build all 12 time series from the raw data.
    Returns dict with keys like 'visitors_total', 'tourist_local', 'hiker_international', etc.
    """
    levels = ['local', 'national', 'regional', 'international']
    series = {}

    for vtype in ['tourist', 'hiker']:
        mask = df['visitor_type'] == vtype
        # Total for this type
        total = df[mask].groupby('date')['visitors'].sum().reset_index()
        total.columns = ['date', 'visitors']
        series[f'{vtype}_total'] = total

        for level in levels:
            lvl_mask = mask & (df['visitor_level'] == level)
            s = df[lvl_mask].groupby('date')['visitors'].sum().reset_index()
            s.columns = ['date', 'visitors']
            series[f'{vtype}_{level}'] = s

    # Visitors = Tourist + Hiker
    visitors_total = df.groupby('date')['visitors'].sum().reset_index()
    visitors_total.columns = ['date', 'visitors']
    series['visitors_total'] = visitors_total

    for level in levels:
        lvl_mask = df['visitor_level'] == level
        s = df[lvl_mask].groupby('date')['visitors'].sum().reset_index()
        s.columns = ['date', 'visitors']
        series[f'visitors_{level}'] = s

    return series


# ══════════════════════════════════════════════════════════════════════════════
# 3. CHART GENERATION
# ══════════════════════════════════════════════════════════════════════════════

def _chart_bars(df: pd.DataFrame, title: str, section: str, figsize=(14, 5), dpi=130):
    """Generate a bar chart with thin colored bars (one color per month) and 7-day moving avg."""
    if df.empty:
        fig, ax = plt.subplots(figsize=figsize, dpi=dpi)
        ax.text(0.5, 0.5, 'No data available', transform=ax.transAxes,
                ha='center', va='center', fontsize=14, color='gray')
        ax.set_title(title, fontsize=13, fontweight='bold')
        plt.tight_layout()
        return fig

    df = df.copy().sort_values('date')
    df['year_month'] = df['date'].dt.to_period('M')

    unique_months = sorted(df['year_month'].unique())
    colors = _pick_palette(section, len(unique_months))
    cmap = {str(ym): c for ym, c in zip(unique_months, colors)}
    df['color'] = df['year_month'].astype(str).map(cmap)

    fig, ax = plt.subplots(figsize=figsize, dpi=dpi)

    ax.bar(df['date'], df['visitors'], width=0.8, color=df['color'],
           edgecolor='none', alpha=0.85)

    if len(df) >= 7:
        ma7 = df['visitors'].rolling(7, center=True).mean()
        ax.plot(df['date'], ma7, lw=2.5, color='black', linestyle='--',
                alpha=0.7, label='7-day Moving Avg')

    n = len(df)
    interval = 3 if n <= 60 else (7 if n <= 120 else 14)
    ax.xaxis.set_major_formatter(mdates.DateFormatter('%d/%b'))
    ax.xaxis.set_major_locator(mdates.DayLocator(interval=interval))
    plt.setp(ax.xaxis.get_majorticklabels(), rotation=45, ha='right')

    ax.set_ylabel('Visitors', fontsize=10, fontweight='bold')
    ax.set_xlabel('Date', fontsize=10, fontweight='bold')
    ax.set_title(title, fontsize=13, fontweight='bold', pad=12)
    ax.grid(True, alpha=0.3, axis='y', linestyle='--')

    # Month legend + moving avg
    legend_handles = [Patch(facecolor=cmap[str(ym)],
                            label=pd.Period(ym).strftime('%b/%y'), alpha=0.85)
                      for ym in unique_months]
    if len(df) >= 7:
        legend_handles.append(plt.Line2D([0], [0], color='black', lw=2.5,
                                         linestyle='--', label='7-day Moving Avg'))
    ax.legend(handles=legend_handles, loc='upper right',
              ncol=min(len(legend_handles), 8), fontsize=8, framealpha=0.95)

    # Stats annotation
    mean_val = df['visitors'].mean()
    max_val = df['visitors'].max()
    ax.text(0.02, 0.95,
            f"Mean: {mean_val:,.0f}\nMax: {max_val:,.0f}",
            transform=ax.transAxes, fontsize=8, va='top',
            bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.5))

    plt.tight_layout()
    return fig


def _fig_to_base64(fig, dpi=130) -> str:
    """Convert a matplotlib figure to a base64-encoded PNG string."""
    buf = io.BytesIO()
    fig.savefig(buf, format='png', dpi=dpi, bbox_inches='tight',
                facecolor='white', edgecolor='none')
    buf.seek(0)
    b64 = base64.b64encode(buf.getvalue()).decode('utf-8')
    plt.close(fig)
    return b64


# ══════════════════════════════════════════════════════════════════════════════
# 4. MAIN REPORT GENERATION
# ══════════════════════════════════════════════════════════════════════════════

def generate_tourism_report(token: str, root_url: str, project_id: str,
                            aoi_id: str, months: List[str]) -> dict:
    """
    Generate a tourism report with 12 charts.

    Returns:
        dict with chart images (base64), CSV data, and summary statistics
    """
    print(f"📊 Starting tourism report for {project_id} / {aoi_id}")
    print(f"   Months: {', '.join(months)}")

    # 1. Fetch data
    df = fetch_all_tourism_data(token, root_url, project_id, aoi_id, months)

    if df.empty:
        raise ValueError("No tourism data was returned from the API. "
                         "Check if the project has tourism data and the AOI ID is correct.")

    # 2. Build all series
    series = _build_series(df)

    # 3. Generate 12 charts
    chart_config = [
        # Visitors (section='visitors' → teal/green palette)
        ('visitors_total', 'Visitors — Total by Day', 'visitors'),
        ('visitors_national', 'Visitors — National by Day', 'visitors'),
        ('visitors_local', 'Visitors — Local by Day', 'visitors'),
        ('visitors_international', 'Visitors — International by Day', 'visitors'),
        # Tourists (section='tourist' → blue/indigo palette)
        ('tourist_total', 'Tourists — Total by Day', 'tourist'),
        ('tourist_national', 'Tourists — National by Day', 'tourist'),
        ('tourist_local', 'Tourists — Local by Day', 'tourist'),
        ('tourist_international', 'Tourists — International by Day', 'tourist'),
        # Hikers (section='hiker' → red/orange/amber palette)
        ('hiker_total', 'Hikers (Excursionistas) — Total by Day', 'hiker'),
        ('hiker_national', 'Hikers (Excursionistas) — National by Day', 'hiker'),
        ('hiker_local', 'Hikers (Excursionistas) — Local by Day', 'hiker'),
        ('hiker_international', 'Hikers (Excursionistas) — International by Day', 'hiker'),
    ]

    charts = {}
    for key, title, section in chart_config:
        s = series.get(key, pd.DataFrame(columns=['date', 'visitors']))
        fig = _chart_bars(s, title, section)
        charts[key] = _fig_to_base64(fig)

    # 4. Build CSV for download
    csv_buf = io.StringIO()
    df.to_csv(csv_buf, index=False)
    csv_b64 = base64.b64encode(csv_buf.getvalue().encode('utf-8')).decode('utf-8')

    # 5. Build summary statistics
    date_min = df['date'].min()
    date_max = df['date'].max()
    total_days = df['date'].nunique()

    visitors_total_series = series.get('visitors_total', pd.DataFrame())
    tourists_total_series = series.get('tourist_total', pd.DataFrame())
    hikers_total_series = series.get('hiker_total', pd.DataFrame())

    summary = {
        "total_days": int(total_days),
        "months_processed": len(months),
        "period_start": date_min.strftime('%d/%m/%Y'),
        "period_end": date_max.strftime('%d/%m/%Y'),
        "visitors_daily_mean": round(float(visitors_total_series['visitors'].mean()), 0) if not visitors_total_series.empty else 0,
        "visitors_daily_max": round(float(visitors_total_series['visitors'].max()), 0) if not visitors_total_series.empty else 0,
        "tourists_daily_mean": round(float(tourists_total_series['visitors'].mean()), 0) if not tourists_total_series.empty else 0,
        "hikers_daily_mean": round(float(hikers_total_series['visitors'].mean()), 0) if not hikers_total_series.empty else 0,
        "charts": charts,
        "csv_data": csv_b64,
    }

    print(f"✅ Tourism report generated: {total_days} days, 12 charts")
    return summary
