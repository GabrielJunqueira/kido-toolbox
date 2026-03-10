import os
import json
import base64
import requests
import asyncio
import io
import zipfile
import pandas as pd
from datetime import datetime
import calendar

# Import data cleaning utilities used in KidoToolbox
try:
    from .calibration_storage import SKLEARN_AVAILABLE
except ImportError:
    SKLEARN_AVAILABLE = False
    
try:
    from sklearn.preprocessing import StandardScaler
    from sklearn.cluster import KMeans
    SKLEARN_AVAILABLE = True
except ImportError:
    SKLEARN_AVAILABLE = False

# Fallback for data_utils
def read_csv_robust(filepath_or_buffer, numeric_columns=None):
    try:
        # Use python engine to automatically detect the delimiter (comma, semicolon, etc)
        df = pd.read_csv(filepath_or_buffer, sep=None, engine='python')
        if numeric_columns:
            for col in numeric_columns:
                if col in df.columns:
                    # Clean <10 values from Kido Privacy policies
                    df[col] = df[col].astype(str).str.replace('<10', '5')
                    df[col] = pd.to_numeric(df[col].astype(str).str.replace(',', ''), errors='coerce')
        return df
    except Exception:
        return None

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEMPLATE_PATH = os.path.join(BASE_DIR, "data", "dashboard_template.html")

async def generate_retail_report_stream(token: str, root_url: str, project_id: str, months: list):
    """Generates the HTML report, yielding SSE progress."""
    def emit(progress, message, level="info"):
        data = json.dumps({"status": "processing", "progress": progress, "message": message, "level": level})
        return f"data: {data}\n\n"

    def emit_error(message):
        data = json.dumps({"status": "error", "message": message})
        return f"data: {data}\n\n"

    def emit_success(html_base64, filename, summary):
        data = json.dumps({
            "status": "success",
            "html_base64": html_base64,
            "filename": filename,
            "summary": summary
        })
        return f"data: {data}\n\n"

    try:
        base_url = root_url
        if not base_url.endswith('/'): base_url += '/'
        v2_url = base_url.replace('/v1/', '/v2/')

        headers = {
            'accept': 'application/json',
            'Authorization': f'Bearer {token}'
        }

        # 1. Fetch polygons from attributes
        yield emit(15, "Fetching project attributes...")
        attr_url = f"{base_url}projects/{project_id}/attributes?alt_engine=false"
        response = requests.get(attr_url, headers=headers, timeout=30)
        
        if response.status_code != 200:
            yield emit_error(f"Failed to fetch attributes: {response.status_code} {response.text}")
            return
            
        attr_data = response.json()
        if 'movement' in attr_data:
            # Flat list of all available values across any dimension for display_name fallback
            for item in attr_data['movement']:
                if 'values' in item:
                    polygons.extend(item['values'])
                    
        # Create a robust lookup dictionary for display names (by generic code, removing prefixes)
        display_name_lookup = {}
        for p in polygons:
            # Keys like MUN-3521002 or AOI-1234
            raw_name = p['name']
            clean_code = raw_name.replace('MUN-', '').replace('AOI-', '')
            display_name_lookup[clean_code] = p['display_name']
            display_name_lookup[raw_name] = p['display_name']
        
        # 2. Determine date range from selected months
        months.sort()
        start_month = months[0]
        end_month = months[-1]
        
        sm_year, sm_month = map(int, start_month.split('-'))
        em_year, em_month = map(int, end_month.split('-'))
        
        start_date = f"{sm_year}-{sm_month:02d}-01"
        _, last_day = calendar.monthrange(em_year, em_month)
        end_date = f"{em_year}-{em_month:02d}-{last_day}"
        
        # 3. Download ZIP for all polygons
        yield emit(30, f"Downloading project data for {start_date} to {end_date} (this may take a while)...")
        zip_url = f"{v2_url}areas_of_interest/{project_id}/dashboard/visitors/all/{start_date}/{end_date}/zip?alt_engine=false"
        
        zip_response = requests.get(zip_url, headers=headers, stream=True, timeout=300)
        if zip_response.status_code != 200:
            yield emit_error(f"Failed to download data zip: {zip_response.status_code}")
            return
            
        zip_bytes = io.BytesIO()
        for chunk in zip_response.iter_content(chunk_size=8192):
            if chunk:
                zip_bytes.write(chunk)
                
        yield emit(50, "Data downloaded. Extracting zip contents...")
        
        # 4. Extract and process
        with zipfile.ZipFile(zip_bytes) as z:
            file_names = z.namelist()
            
            # Dynamically discover all Location IDs from the zip file names
            # Files look like: visitors_by_age_gender__AOI-1090473.csv or presence_at_hour__AOI-MUN-3521002.csv
            import re
            discovered_codes = set()
            for fn in file_names:
                # Look for the pattern '__AOI-' followed by the code, ending in .csv
                match = re.search(r'__AOI-([^\.]+)\.csv$', fn)
                if match:
                    discovered_codes.add(match.group(1))
                    
            if not discovered_codes:
                sample_files = ", ".join(file_names[:8]) if file_names else "Empty zip"
                yield emit_error(f"No valid data tables found in the ZIP file. Sample files: {sample_files}")
                return
                
            yield emit(40, f"Discovered {len(discovered_codes)} valid locations in the zip file data.")
            
            def load_df(metric_keyword, aoi_code):
                # Try exact first
                exact = f'{metric_keyword}__AOI-{aoi_code}.csv'
                if exact in file_names:
                    with z.open(exact) as f:
                        return read_csv_robust(f, numeric_columns=['visitors', 'visits'])
                        
                # Fuzzy fallback matching
                for fn in file_names:
                    if metric_keyword in fn and aoi_code in fn and fn.endswith('.csv'):
                        with z.open(fn) as f:
                            return read_csv_robust(f, numeric_columns=['visitors', 'visits'])
                return None
                
            all_features = []
            detailed_data = {}
            successful_stores = 0
            failed_stores = 0
            
            total_polys = len(discovered_codes)
            count = 0
            
            for code in discovered_codes:
                count += 1
                
                # Try to map the code to a human readable name
                clean_code = code.replace('MUN-', '').replace('AOI-', '')
                name = display_name_lookup.get(code, display_name_lookup.get(clean_code, f"Location {code}"))
                if count % 10 == 0:
                    yield emit(50 + int((count/total_polys)*30), f"Processing polygon {count}/{total_polys}...")
                    # Allow async context to breathe
                    await asyncio.sleep(0)
                    
                data = {
                    'daily_visitors_weekday': load_df('daily_visitors_by_weekday', code),
                    'presence_hour': load_df('presence_at_hour', code),
                    'unique_visitors': load_df('unique_visitors', code),
                    'unique_visits': load_df('unique_visits', code),
                    'age_gender': load_df('visitors_by_age_gender', code),
                    'date_level': load_df('visitors_by_date_level', code),
                    'residence': load_df('visitors_by_residence_level', code),
                    'social_class': load_df('visitors_by_social_class', code),
                    'arrival_hour': load_df('visits_by_arrival_hour', code),
                }
                
                # Check if all critical files are present
                if any(v is None for k, v in data.items() if k in ['daily_visitors_weekday', 'unique_visitors', 'unique_visits', 'age_gender', 'social_class']):
                    failed_stores += 1
                    continue
                    
                try:
                    total_unique_visitors = float(data['unique_visitors']['visitors'].values[0])
                    total_unique_visits = float(data['unique_visits']['visits'].values[0])
                    visits_per_visitor = total_unique_visits / total_unique_visitors if total_unique_visitors > 0 else 0
                    
                    visitors_by_level = data['daily_visitors_weekday'].groupby('visitor_level')['visitors'].sum()
                    total_visitors = visitors_by_level.sum()
                    
                    gender_total = data['age_gender'].groupby('gender')['visitors'].sum()
                    social_total = data['social_class'].groupby('social_class')['visitors'].sum()
                    
                    weekday_total = data['daily_visitors_weekday'].groupby('day_of_week')['visitors'].sum()
                    weekday_avg = weekday_total[weekday_total.index.isin([1,2,3,4,5])].mean()
                    weekend_avg = weekday_total[weekday_total.index.isin([6,7])].mean()
                    
                    # Safe checks
                    if pd.isna(weekday_avg): weekday_avg = 0
                    if pd.isna(weekend_avg): weekend_avg = 0
                    
                    features = {
                        'store_code': code,
                        'Loja': name,
                        'Visitantes': total_unique_visitors,
                        'Taxa_Retorno': round(visits_per_visitor, 2),
                        'Pct_Local': round(float(visitors_by_level.get('local', 0) / total_visitors * 100) if total_visitors > 0 else 0, 1),
                        'Pct_Regional': round(float(visitors_by_level.get('regional', 0) / total_visitors * 100) if total_visitors > 0 else 0, 1),
                        'Pct_Nacional': round(float(visitors_by_level.get('national', 0) / total_visitors * 100) if total_visitors > 0 else 0, 1),
                        'Pct_Internacional': round(float(visitors_by_level.get('international', 0) / total_visitors * 100) if total_visitors > 0 else 0, 1),
                        'Pct_Classe_AB': round(float(social_total[social_total.index.isin(['A', 'B'])].sum() / social_total.sum() * 100) if social_total.sum() > 0 else 0, 1),
                        'Indice_FDS': round(float(weekend_avg / weekday_avg) if weekday_avg > 0 else 0, 2),
                        'Status_Real': 'Unknown'
                    }
                    
                    all_features.append(features)
                    detailed_data[name] = {
                        'ageGender': data['age_gender'].to_dict('records') if data['age_gender'] is not None else [],
                        'socialClass': data['social_class'].to_dict('records') if data['social_class'] is not None else [],
                        'visitorLevel': data['residence'].to_dict('records') if data['residence'] is not None else [],
                        'presenceByHour': data['presence_hour'].to_dict('records') if data['presence_hour'] is not None else []
                    }
                    successful_stores += 1
                except Exception as e:
                    logger.error(f"Error processing {name}: {e}")
                    failed_stores += 1

        if not all_features:
            sample_files = ", ".join(file_names[:8]) if file_names else "Empty zip"
            yield emit_error(f"Failed to process data for any polygons. Could not match mapping logic. Zip contents sample: {sample_files}")
            return

        yield emit(85, "Clustering results...")
        
        features_df = pd.DataFrame(all_features)
        
        # 5. ML Clustering
        if SKLEARN_AVAILABLE and len(features_df) >= 3:
            feature_cols = ['Visitantes', 'Taxa_Retorno', 'Pct_Local', 'Pct_Classe_AB', 'Indice_FDS']
            # fill na
            features_df[feature_cols] = features_df[feature_cols].fillna(0)
            X = features_df[feature_cols].values
            scaler = StandardScaler()
            X_scaled = scaler.fit_transform(X)
            
            kmeans = KMeans(n_clusters=3, random_state=42, n_init=10)
            features_df['cluster'] = kmeans.fit_predict(X_scaled)
            
            cluster_means = features_df.groupby('cluster')['Visitantes'].mean().sort_values(ascending=False)
            if len(cluster_means) == 3:
                cluster_labels = {cluster_means.index[0]: 'Alto Potencial', 
                                cluster_means.index[1]: 'Médio Potencial',
                                cluster_means.index[2]: 'Baixo Potencial'}
            else:
                 cluster_labels = {idx: f"Cluster {idx}" for idx in cluster_means.index}
                 
            features_df['Cluster_ML'] = features_df['cluster'].map(cluster_labels)
        else:
            if len(features_df) >= 3:
                features_df['Cluster_ML'] = pd.cut(
                    features_df['Visitantes'],
                    bins=3,
                    labels=['Baixo Potencial', 'Médio Potencial', 'Alto Potencial']
                )
            else:
                features_df['Cluster_ML'] = 'N/A'
                
        # Drop cluster col if exists
        if 'cluster' in features_df.columns:
            features_df = features_df.drop('cluster', axis=1)
            
        summary_data = features_df.to_dict('records')
        
        embedded_json = json.dumps({
            "summary": summary_data,
            "detailed": detailed_data
        }, ensure_ascii=False)
        
        yield emit(95, "Generating final HTML...")
        
        # 6. Read template and inject data
        if not os.path.exists(TEMPLATE_PATH):
            import prepare_template
            prepare_template.prepare_template()
            
        with open(TEMPLATE_PATH, 'r', encoding='utf-8') as f:
            html_content = f.read()
            
        # The template has a placeholder: {{{EMBEDDED_JSON}}}
        html_content = html_content.replace('{{{EMBEDDED_JSON}}}', embedded_json)
        
        html_base64 = base64.b64encode(html_content.encode('utf-8')).decode('utf-8')
        filename = f"Dashboard_{project_id[:8]}_{start_month}_to_{end_month}.html"
        
        yield emit_success(html_base64, filename, {
            "polygons": successful_stores,
            "failed": failed_stores
        })
        
    except Exception as e:
        logger.exception("Error during project report generation")
        yield emit_error(f"Internal server error: {str(e)}")
