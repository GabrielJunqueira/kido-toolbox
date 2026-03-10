import os
import json
import uuid
import requests
import asyncio
import io
import zipfile
import re
import pandas as pd
from datetime import datetime
import calendar
import logging
from typing import Dict, Optional, Set

logger = logging.getLogger(__name__)

# Check sklearn availability
SKLEARN_AVAILABLE = False
try:
    from sklearn.preprocessing import StandardScaler
    from sklearn.cluster import KMeans
    SKLEARN_AVAILABLE = True
except ImportError:
    SKLEARN_AVAILABLE = False

# ─── Robust CSV reader ───────────────────────────────────────────────
def read_csv_robust(filepath_or_buffer, numeric_columns=None):
    """Read a CSV with automatic delimiter detection and <10 value handling."""
    try:
        df = pd.read_csv(filepath_or_buffer, sep=None, engine='python')
        if numeric_columns:
            for col in numeric_columns:
                if col in df.columns:
                    df[col] = df[col].astype(str).str.replace('<10', '5', regex=False)
                    df[col] = pd.to_numeric(df[col].astype(str).str.replace(',', '', regex=False), errors='coerce')
        return df
    except Exception as e:
        logger.warning(f"read_csv_robust failed: {e}")
        return None


# ─── Paths ────────────────────────────────────────────────────────────
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEMPLATE_PATH = os.path.join(BASE_DIR, "data", "dashboard_template.html")
TEMP_DIR = os.path.join(BASE_DIR, "data", "temp_reports")

# Ensure temp dir exists
os.makedirs(TEMP_DIR, exist_ok=True)

# In-memory registry of generated files (file_id -> filepath)
_generated_files: Dict[str, str] = {}


def get_generated_file(file_id: str) -> Optional[str]:
    """Return the filepath for a generated report, or None."""
    return _generated_files.get(file_id)


# ─── SSE helpers ──────────────────────────────────────────────────────
def _sse(payload: dict) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


def emit(progress: int, message: str, level: str = "info") -> str:
    return _sse({"status": "processing", "progress": progress, "message": message, "level": level})


def emit_error(message: str) -> str:
    return _sse({"status": "error", "message": message})


def emit_success(filename: str, file_id: str, summary: dict) -> str:
    return _sse({
        "status": "success",
        "filename": filename,
        "file_id": file_id,
        "summary": summary,
    })


# ─── Feature extraction (mirrors OXXO analyze_12_stores logic) ───────
def _extract_features(data: dict, code: str, name: str) -> Optional[dict]:
    """Extract summary features from a set of CSV DataFrames for one polygon."""
    try:
        total_unique_visitors = float(data['unique_visitors']['visitors'].values[0])
        total_unique_visits = float(data['unique_visits']['visits'].values[0])
        visits_per_visitor = total_unique_visits / total_unique_visitors if total_unique_visitors > 0 else 0

        visitors_by_level = data['daily_visitors_weekday'].groupby('visitor_level')['visitors'].sum()
        total_visitors = visitors_by_level.sum()

        social_total = data['social_class'].groupby('social_class')['visitors'].sum()

        weekday_total = data['daily_visitors_weekday'].groupby('day_of_week')['visitors'].sum()
        weekday_avg = weekday_total[weekday_total.index.isin([1, 2, 3, 4, 5])].mean()
        weekend_avg = weekday_total[weekday_total.index.isin([6, 7])].mean()
        if pd.isna(weekday_avg): weekday_avg = 0
        if pd.isna(weekend_avg): weekend_avg = 0

        pct = lambda part, whole: round(float(part / whole * 100), 1) if whole > 0 else 0.0

        return {
            'store_code': code,
            'Loja': name,
            'Visitantes': total_unique_visitors,
            'Taxa_Retorno': round(visits_per_visitor, 2),
            'Pct_Local': pct(visitors_by_level.get('local', 0), total_visitors),
            'Pct_Regional': pct(visitors_by_level.get('regional', 0), total_visitors),
            'Pct_Nacional': pct(visitors_by_level.get('national', 0), total_visitors),
            'Pct_Internacional': pct(visitors_by_level.get('international', 0), total_visitors),
            'Pct_Classe_AB': pct(social_total[social_total.index.isin(['A', 'B'])].sum(), social_total.sum()),
            'Indice_FDS': round(float(weekend_avg / weekday_avg) if weekday_avg > 0 else 0, 2),
            'Status_Real': 'Unknown',
        }
    except Exception as e:
        logger.error(f"Feature extraction failed for {name} ({code}): {e}")
        return None


def _extract_detailed(data: dict) -> dict:
    """Extract detailed chart data for a polygon."""
    return {
        'ageGender':      data['age_gender'].to_dict('records')   if data.get('age_gender')   is not None else [],
        'socialClass':    data['social_class'].to_dict('records') if data.get('social_class') is not None else [],
        'visitorLevel':   data['residence'].to_dict('records')    if data.get('residence')    is not None else [],
        'presenceByHour': data['presence_hour'].to_dict('records') if data.get('presence_hour') is not None else [],
    }


# ─── Main generator ──────────────────────────────────────────────────
async def generate_retail_report_stream(token: str, root_url: str, project_id: str, months: list):
    """Generates the HTML report, yielding SSE progress events.
    On success, writes the HTML to a temp file and emits a download link.
    """
    try:
        base_url = root_url.rstrip('/') + '/'
        v2_url = base_url.replace('/v1/', '/v2/')
        headers = {
            'accept': 'application/json',
            'Authorization': f'Bearer {token}',
        }

        # ── 1. Fetch project attributes for display-name mapping ─────
        yield emit(10, "Fetching project attributes...")
        attr_url = f"{base_url}projects/{project_id}/attributes?alt_engine=false"
        response = requests.get(attr_url, headers=headers, timeout=30)
        if response.status_code != 200:
            yield emit_error(f"Failed to fetch attributes: {response.status_code} {response.text[:200]}")
            return

        attr_data = response.json()

        # Build a lookup: code -> display_name from all attribute dimensions
        display_name_lookup: Dict[str, str] = {}
        if 'movement' in attr_data:
            for dim in attr_data['movement']:
                for val in dim.get('values', []):
                    raw = val['name']
                    display_name_lookup[raw] = val['display_name']
                    # also store cleaned versions
                    for prefix in ('MUN-', 'AOI-', 'CP-'):
                        if raw.startswith(prefix):
                            display_name_lookup[raw[len(prefix):]] = val['display_name']

        # ── 2. Date range ────────────────────────────────────────────
        months.sort()
        sm_year, sm_month = map(int, months[0].split('-'))
        em_year, em_month = map(int, months[-1].split('-'))
        start_date = f"{sm_year}-{sm_month:02d}-01"
        _, last_day = calendar.monthrange(em_year, em_month)
        end_date = f"{em_year}-{em_month:02d}-{last_day}"

        # ── 3. Download ZIP ──────────────────────────────────────────
        yield emit(20, f"Downloading project data for {start_date} to {end_date} (this may take a while)...")
        zip_url = f"{v2_url}areas_of_interest/{project_id}/dashboard/visitors/all/{start_date}/{end_date}/zip?alt_engine=false"

        zip_response = requests.get(zip_url, headers=headers, stream=True, timeout=300)
        if zip_response.status_code != 200:
            yield emit_error(f"Failed to download data zip: {zip_response.status_code}")
            return

        zip_bytes = io.BytesIO()
        for chunk in zip_response.iter_content(chunk_size=8192):
            if chunk:
                zip_bytes.write(chunk)
        zip_bytes.seek(0)

        yield emit(40, "Data downloaded. Extracting zip contents...")

        # ── 4. Extract and process each polygon ──────────────────────
        with zipfile.ZipFile(zip_bytes) as z:
            file_names = z.namelist()

            # Discover polygon codes from filenames like: some_table__AOI-1090473.csv
            discovered_codes: Set[str] = set()
            for fn in file_names:
                m = re.search(r'__AOI-([^\.]+)\.csv$', fn)
                if m:
                    discovered_codes.add(m.group(1))

            if not discovered_codes:
                sample = ", ".join(file_names[:8]) if file_names else "Empty zip"
                yield emit_error(f"No valid data tables found in ZIP. Sample files: {sample}")
                return

            total_polys = len(discovered_codes)
            yield emit(45, f"Found {total_polys} polygons to process.")

            def load_df(keyword: str, aoi_code: str):
                exact = f'{keyword}__AOI-{aoi_code}.csv'
                # check exact match first (handles nested folders too)
                for fn in file_names:
                    if fn.endswith(exact) or fn == exact:
                        with z.open(fn) as fh:
                            return read_csv_robust(io.BytesIO(fh.read()), numeric_columns=['visitors', 'visits'])
                # fuzzy fallback
                for fn in file_names:
                    if keyword in fn and aoi_code in fn and fn.endswith('.csv'):
                        with z.open(fn) as fh:
                            return read_csv_robust(io.BytesIO(fh.read()), numeric_columns=['visitors', 'visits'])
                return None

            all_features = []
            detailed_data = {}
            successful = 0
            failed = 0

            for idx, code in enumerate(sorted(discovered_codes), 1):
                # Resolve human name
                clean = code.replace('MUN-', '').replace('AOI-', '')
                name = display_name_lookup.get(code,
                       display_name_lookup.get(clean,
                       display_name_lookup.get(f'AOI-{code}', f"Location {code}")))

                if idx % 10 == 0 or idx == total_polys:
                    pct = 45 + int((idx / total_polys) * 35)
                    yield emit(pct, f"Processing polygon {idx}/{total_polys}...")
                    await asyncio.sleep(0)

                data = {
                    'daily_visitors_weekday': load_df('daily_visitors_by_weekday', code),
                    'presence_hour':          load_df('presence_at_hour', code),
                    'unique_visitors':        load_df('unique_visitors', code),
                    'unique_visits':          load_df('unique_visits', code),
                    'age_gender':             load_df('visitors_by_age_gender', code),
                    'residence':              load_df('visitors_by_residence_level', code),
                    'social_class':           load_df('visitors_by_social_class', code),
                    'arrival_hour':           load_df('visits_by_arrival_hour', code),
                }

                # Must have at least the critical tables
                critical = ['daily_visitors_weekday', 'unique_visitors', 'unique_visits', 'age_gender', 'social_class']
                if any(data.get(k) is None for k in critical):
                    failed += 1
                    continue

                features = _extract_features(data, code, name)
                if features is None:
                    failed += 1
                    continue

                all_features.append(features)
                detailed_data[name] = _extract_detailed(data)
                successful += 1

        if not all_features:
            yield emit_error(f"Failed to process data for any polygons ({failed} failed).")
            return

        # ── 5. ML Clustering ─────────────────────────────────────────
        yield emit(82, "Clustering locations...")
        features_df = pd.DataFrame(all_features)

        if SKLEARN_AVAILABLE and len(features_df) >= 3:
            feat_cols = ['Visitantes', 'Taxa_Retorno', 'Pct_Local', 'Pct_Classe_AB', 'Indice_FDS']
            features_df[feat_cols] = features_df[feat_cols].fillna(0)
            X = features_df[feat_cols].values
            X_scaled = StandardScaler().fit_transform(X)
            kmeans = KMeans(n_clusters=min(3, len(features_df)), random_state=42, n_init=10)
            features_df['cluster'] = kmeans.fit_predict(X_scaled)

            cluster_means = features_df.groupby('cluster')['Visitantes'].mean().sort_values(ascending=False)
            labels_map = {}
            label_names = ['Alto Potencial', 'Médio Potencial', 'Baixo Potencial']
            for i, cid in enumerate(cluster_means.index):
                labels_map[cid] = label_names[i] if i < len(label_names) else f"Cluster {cid}"
            features_df['Cluster_ML'] = features_df['cluster'].map(labels_map)
            features_df.drop(columns=['cluster'], inplace=True)
        elif len(features_df) >= 3:
            features_df['Cluster_ML'] = pd.cut(
                features_df['Visitantes'], bins=3,
                labels=['Baixo Potencial', 'Médio Potencial', 'Alto Potencial']
            ).astype(str)
        else:
            features_df['Cluster_ML'] = 'N/A'

        # ── 6. Build the final JSON blob ─────────────────────────────
        summary_records = features_df.to_dict('records')
        embedded_json = json.dumps({
            "summary": summary_records,
            "detailed": detailed_data,
        }, ensure_ascii=False)

        # ── 7. Inject into template and save ─────────────────────────
        yield emit(90, "Generating final HTML dashboard...")

        if not os.path.exists(TEMPLATE_PATH):
            yield emit_error(f"Dashboard template not found at {TEMPLATE_PATH}")
            return

        with open(TEMPLATE_PATH, 'r', encoding='utf-8') as f:
            html_content = f.read()

        # Replace the placeholder
        placeholder = '{{{EMBEDDED_JSON}}}'
        if placeholder not in html_content:
            yield emit_error("Dashboard template is missing the data placeholder. Please re-run prepare_template.py.")
            return

        html_content = html_content.replace(placeholder, embedded_json)

        # Sanity check: the result must still start with <!DOCTYPE
        if not html_content.strip().startswith('<!DOCTYPE'):
            yield emit_error("Internal error: generated HTML is malformed after data injection.")
            return

        # Write to a temp file
        file_id = str(uuid.uuid4())
        filename = f"Dashboard_{project_id[:8]}_{months[0]}_to_{months[-1]}.html"
        filepath = os.path.join(TEMP_DIR, f"{file_id}.html")

        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(html_content)

        _generated_files[file_id] = filepath

        yield emit(100, "Dashboard ready for download!")
        yield emit_success(filename, file_id, {
            "polygons": successful,
            "failed": failed,
        })

    except Exception as e:
        import traceback
        traceback.print_exc()
        logger.exception("Error during retail report generation")
        yield emit_error(f"Internal server error: {str(e)}")
