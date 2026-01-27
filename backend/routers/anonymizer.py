from fastapi import APIRouter, UploadFile, File, Form, HTTPException
from fastapi.responses import StreamingResponse
import pandas as pd
import hashlib
import unicodedata
from io import BytesIO
import io

router = APIRouter(
    prefix="/api/anonymizer",
    tags=["anonymizer"]
)

# =============================
# HELPERS
# =============================
def read_table(file_content: bytes, filename: str) -> pd.DataFrame:
    if filename.lower().endswith(".csv"):
        return pd.read_csv(io.BytesIO(file_content))
    elif filename.lower().endswith((".xls", ".xlsx")):
        return pd.read_excel(io.BytesIO(file_content))
    else:
        raise ValueError("Formato não suportado (use CSV ou Excel).")


def normalize_colname(col: str) -> str:
    col = unicodedata.normalize("NFKD", col).encode("ascii", "ignore").decode("utf-8")
    col = col.replace("*", "").strip()
    return col


def normalize_text(value):
    if pd.isna(value):
        return value
    value = str(value).strip()
    value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("utf-8")
    return value


def clean_notion_label(value: str) -> str:
    """
    Remove links do Notion:
    'Switzerland (https://www.notion.so/...)' -> 'Switzerland'
    """
    if pd.isna(value):
        return value
    value = str(value)
    return value.split(" (http")[0].strip()


def stable_hash(text: str, salt: str, length: int = 8) -> str:
    raw = f"{salt}::{text}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:length].upper()


def map_to_code(series, prefix, salt):
    """
    Maps values to hashed codes.
    Note: In this web version, we do not persist the mapping to disk (stateless),
    re-generating hashes deterministically based on input + salt.
    """
    series = series.fillna("")
    mapping = {}
    codes = []

    for value in series:
        if value == "":
            codes.append("")
            continue

        if value not in mapping:
            code = f"{prefix}{stable_hash(value, salt)}"
            mapping[value] = code

        codes.append(mapping[value])

    return pd.Series(codes, index=series.index)


def treat_deals(df: pd.DataFrame, salt: str) -> pd.DataFrame:
    # --- normaliza nomes de colunas ---
    df = df.rename(columns={c: normalize_colname(c) for c in df.columns})

    # --- colunas que vamos manter ---
    KEEP_COLUMNS = [
        "Deal",
        "Company",
        "Country",
        "Amount CHF",
        "Amount to Invoice CHF",
        "Close Date",
        "Deal Stage",
        "Segment",
        "Type",
        "Vertical",
        "Year of deal",
    ]

    # mantém apenas as colunas desejadas que existem no df
    df = df[[c for c in KEEP_COLUMNS if c in df.columns]].copy()

    # --- anonimização ---
    if "Deal" in df.columns:
        df["Deal"] = map_to_code(
            df["Deal"],
            prefix="DEAL-",
            salt=salt,
        )

    if "Company" in df.columns:
        df["Company"] = map_to_code(
            df["Company"],
            prefix="COMP-",
            salt=salt,
        )

    # --- limpeza de Country (remove link do Notion) ---
    if "Country" in df.columns:
        df["Country"] = (
            df["Country"]
            .map(clean_notion_label)
            .map(normalize_text)
        )

    # --- limpeza geral de texto ---
    TEXT_COLS = [
        "Deal Stage",
        "Segment",
        "Type",
        "Vertical",
    ]
    for col in TEXT_COLS:
        if col in df.columns:
            df[col] = df[col].map(normalize_text)

    # --- datas ---
    if "Close Date" in df.columns:
        df["Close Date"] = pd.to_datetime(df["Close Date"], errors="coerce")

    # --- valores numéricos ---
    for col in ["Amount CHF", "Amount to Invoice CHF"]:
        if col in df.columns:
            # First ensure it's string to use .str accessor, then clean
            df[col] = (
                df[col]
                .astype(str)
                .str.replace(",", "", regex=False)
                # Handle 'nan' strings that might result from astype(str) on NaN
                .replace('nan', '0') 
            )
            # FORCE to float, errors='coerce' turns non-convertible content to NaN
            df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0.0)

    return df


@router.post("/process")
async def process_file(
    file: UploadFile = File(...),
    salt: str = Form(...)
):
    try:
        content = await file.read()
        
        # Read file
        try:
            df = read_table(content, file.filename)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Error reading file: {str(e)}")

        # Process
        try:
            df_treated = treat_deals(df, salt)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Error processing data: {str(e)}")

        # Export to CSV
        stream = io.StringIO()
        df_treated.to_csv(stream, index=False)
        
        response = StreamingResponse(
            iter([stream.getvalue()]),
            media_type="text/csv"
        )
        response.headers["Content-Disposition"] = "attachment; filename=deals_treated.csv"
        return response

    except Exception as e:
         raise HTTPException(status_code=500, detail=f"Unexpected error: {str(e)}")
