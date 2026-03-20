import os
import io
import json
import math
import traceback
from urllib.parse import quote

import requests
import pandas as pd
from pyproj import Transformer

# =========================================================
# 경로
# =========================================================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
GEO_DIR = os.path.join(DATA_DIR, "geo")
REST_DIR = os.path.join(DATA_DIR, "restaurants")

os.makedirs(GEO_DIR, exist_ok=True)
os.makedirs(REST_DIR, exist_ok=True)

# =========================================================
# 다운로드 URL
# =========================================================
# 시도 / 시군구
SIDO_URL = "https://raw.githubusercontent.com/southkorea/southkorea-maps/master/gadm/json/skorea-provinces-geo.json"
SIGUNGU_URL = "https://raw.githubusercontent.com/southkorea/southkorea-maps/master/gadm/json/skorea-municipalities-geo.json"

# 읍면동(행정동)
EMD_URL = "https://raw.githubusercontent.com/vuski/admdongkor/master/ver20220101/HangJeongDong_ver20220101.geojson"

# 전국 일반음식점
# 지방행정인허가데이터개방에서 업종별 전체 파일 다운로드 방식으로 제공되는 일반음식점 파일 경로
RESTAURANT_XLSX_URL = "https://www.localdata.go.kr/datafile/each/07_24_04_P.xlsx"

# =========================================================
# 유틸
# =========================================================
def download_file(url: str, path: str, timeout: int = 180):
    print(f"[다운로드] {url}")
    r = requests.get(url, timeout=timeout)
    r.raise_for_status()
    with open(path, "wb") as f:
        f.write(r.content)
    print(f"[완료] {path}")


def normalize_str(v):
    if pd.isna(v):
        return ""
    return str(v).strip()


def find_col(df: pd.DataFrame, candidates):
    cols = list(df.columns)
    for cand in candidates:
        if cand in cols:
            return cand
    lower_map = {str(c).strip().lower(): c for c in cols}
    for cand in candidates:
        key = str(cand).strip().lower()
        if key in lower_map:
            return lower_map[key]
    return None


def first_nonempty(row, cols):
    for c in cols:
        if c and c in row and pd.notna(row[c]) and str(row[c]).strip() != "":
            return row[c]
    return None


def make_naver_map_search_url(query: str) -> str:
    return f"https://map.naver.com/v5/search/{quote(query)}"


def parse_address_parts(address: str):
    address = normalize_str(address)
    if not address:
        return "", "", ""

    parts = address.split()
    sido = parts[0] if len(parts) >= 1 else ""
    sigungu = parts[1] if len(parts) >= 2 else ""
    emd = parts[2] if len(parts) >= 3 else ""

    # 세종특별자치시처럼 시군구가 비는 경우 보정
    if sido == "세종특별자치시" and len(parts) >= 2:
        sigungu = "세종특별자치시"
        emd = parts[1] if len(parts) >= 2 else ""

    return sido, sigungu, emd


def transform_xy_to_wgs84(x_series: pd.Series, y_series: pd.Series):
    """
    공공데이터 설명에는 EPSG:5174로 안내되는 경우가 많지만,
    환경에 따라 예전 문서/미러에서 2097로 적힌 사례도 있어 둘 다 시도.
    우선 5174 -> 4326, 결과가 이상하면 2097 -> 4326 재시도.
    """
    x = pd.to_numeric(x_series, errors="coerce")
    y = pd.to_numeric(y_series, errors="coerce")

    t5174 = Transformer.from_crs("EPSG:5174", "EPSG:4326", always_xy=True)
    lon_5174, lat_5174 = t5174.transform(x.values, y.values)

    lat_5174 = pd.Series(lat_5174)
    lon_5174 = pd.Series(lon_5174)

    valid_5174 = (
        lat_5174.between(30, 40, inclusive="both")
        & lon_5174.between(120, 135, inclusive="both")
    )

    if valid_5174.mean() >= 0.7:
        return lat_5174, lon_5174

    t2097 = Transformer.from_crs("EPSG:2097", "EPSG:4326", always_xy=True)
    lon_2097, lat_2097 = t2097.transform(x.values, y.values)

    lat_2097 = pd.Series(lat_2097)
    lon_2097 = pd.Series(lon_2097)

    valid_2097 = (
        lat_2097.between(30, 40, inclusive="both")
        & lon_2097.between(120, 135, inclusive="both")
    )

    if valid_2097.mean() > valid_5174.mean():
        return lat_2097, lon_2097

    return lat_5174, lon_5174


def build_summary(row):
    pieces = []

    food_type = normalize_str(row.get("food_category", ""))
    if food_type:
        pieces.append(f"{food_type} 업종")

    status = normalize_str(row.get("business_status", ""))
    detail_status = normalize_str(row.get("detail_status", ""))
    if detail_status:
        pieces.append(f"상태: {detail_status}")
    elif status:
        pieces.append(f"상태: {status}")

    return " / ".join(pieces)


# =========================================================
# 1. GeoJSON 다운로드
# =========================================================
def prepare_geojson():
    download_file(SIDO_URL, os.path.join(GEO_DIR, "sido.geojson"))
    download_file(SIGUNGU_URL, os.path.join(GEO_DIR, "sigungu.geojson"))
    download_file(EMD_URL, os.path.join(GEO_DIR, "emd.geojson"))


# =========================================================
# 2. 음식점 데이터 다운로드 + 정리
# =========================================================
def prepare_restaurants():
    xlsx_path = os.path.join(REST_DIR, "general_restaurants.xlsx")
    csv_path = os.path.join(REST_DIR, "restaurants_merged.csv")
    parquet_path = os.path.join(REST_DIR, "restaurants_merged.parquet")

    download_file(RESTAURANT_XLSX_URL, xlsx_path)

    print("[로드] 엑셀 읽는 중...")
    df = pd.read_excel(xlsx_path, engine="openpyxl")
    print(f"[원본 행 수] {len(df):,}")

    # 컬럼 후보
    col_name = find_col(df, ["사업장명", "업소명"])
    col_addr = find_col(df, ["소재지전체주소", "지번주소"])
    col_road = find_col(df, ["도로명전체주소", "소재지도로명전체주소", "소재지도로명주소"])
    col_x = find_col(df, ["좌표정보(X)", "좌표정보x(epsg5174)", "좌표정보x", "좌표정보(X좌표)", "X", "경도"])
    col_y = find_col(df, ["좌표정보(Y)", "좌표정보y(epsg5174)", "좌표정보y", "좌표정보(Y좌표)", "Y", "위도"])
    col_type = find_col(df, ["업태구분명", "위생업태명"])
    col_phone = find_col(df, ["소재지전화", "전화번호"])
    col_status = find_col(df, ["영업상태명"])
    col_detail_status = find_col(df, ["상세영업상태명"])
    col_status_code = find_col(df, ["영업상태구분코드", "상세영업상태코드"])

    required = [col_name, col_addr, col_road, col_x, col_y]
    if any(c is None for c in required):
        raise ValueError(
            "원본 파일의 핵심 컬럼을 찾지 못했습니다. "
            f"name={col_name}, addr={col_addr}, road={col_road}, x={col_x}, y={col_y}"
        )

    # 영업 중만 남기기
    work = df.copy()
    if col_detail_status:
        work = work[
            work[col_detail_status].astype(str).str.contains("정상|영업", na=False)
        ].copy()
    elif col_status:
        work = work[
            work[col_status].astype(str).str.contains("정상|영업", na=False)
        ].copy()
    elif col_status_code:
        work = work[
            pd.to_numeric(work[col_status_code], errors="coerce").fillna(-1).isin([1])
        ].copy()

    print(f"[정상영업 필터 후] {len(work):,}")

    # 좌표 변환
    lat, lon = transform_xy_to_wgs84(work[col_x], work[col_y])

    out = pd.DataFrame({
        "name": work[col_name].astype(str).fillna("").str.strip(),
        "address": work[col_addr].astype(str).fillna("").str.strip(),
        "road_address": work[col_road].astype(str).fillna("").str.strip(),
        "lat": lat,
        "lon": lon,
        "food_category": work[col_type].astype(str).fillna("").str.strip() if col_type else "",
        "phone": work[col_phone].astype(str).fillna("").str.strip() if col_phone else "",
        "business_status": work[col_status].astype(str).fillna("").str.strip() if col_status else "",
        "detail_status": work[col_detail_status].astype(str).fillna("").str.strip() if col_detail_status else "",
    })

    # 좌표 이상치 제거
    out = out[
        out["lat"].between(30, 40, inclusive="both")
        & out["lon"].between(120, 135, inclusive="both")
    ].copy()

    # 주소 파싱
    base_addr = out["road_address"].where(out["road_address"].str.strip() != "", out["address"])
    parsed = base_addr.apply(parse_address_parts)
    out["sido"] = parsed.apply(lambda x: x[0])
    out["sigungu"] = parsed.apply(lambda x: x[1])
    out["emd"] = parsed.apply(lambda x: x[2])

    # 기본 컬럼 맞추기
    out["rating"] = pd.NA
    out["review_count"] = 0
    out["main_menu"] = ""
    out["summary"] = out.apply(build_summary, axis=1)
    out["parking"] = ""
    out["waiting"] = ""
    out["opening_hours"] = ""
    out["source"] = "지방행정인허가데이터개방 일반음식점"
    out["naver_map_url"] = out.apply(
        lambda r: make_naver_map_search_url(f"{r['name']} {r['road_address'] or r['address']}"),
        axis=1
    )

    # 중복 제거
    out = out.drop_duplicates(subset=["name", "road_address", "address", "lat", "lon"]).copy()

    # 빈 값 정리
    for c in [
        "name", "sido", "sigungu", "emd", "address", "road_address", "food_category",
        "main_menu", "summary", "parking", "waiting", "opening_hours", "phone",
        "source", "naver_map_url"
    ]:
        out[c] = out[c].astype(str).fillna("").str.strip()

    out["review_count"] = pd.to_numeric(out["review_count"], errors="coerce").fillna(0).astype(int)

    # 저장
    out.to_csv(csv_path, index=False, encoding="utf-8-sig")
    out.to_parquet(parquet_path, index=False)

    print(f"[저장 완료] {csv_path}")
    print(f"[저장 완료] {parquet_path}")
    print(f"[최종 행 수] {len(out):,}")


# =========================================================
# 실행
# =========================================================
if __name__ == "__main__":
    try:
        print("=== 1) 행정구역 GeoJSON 준비 ===")
        prepare_geojson()

        print("\n=== 2) 음식점 데이터 준비 ===")
        prepare_restaurants()

        print("\n모든 준비가 끝났습니다.")
        print("이제 아래 명령으로 앱을 실행하세요:")
        print("streamlit run app.py")

    except Exception as e:
        print("\n[오류 발생]")
        print(str(e))
        print(traceback.format_exc())
        raise
