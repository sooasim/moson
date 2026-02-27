import re

import pandas as pd
from pathlib import Path

from app import create_app
from app.extensions import db
from app.models import PolicyRow


def parse_int(val):
    if val is None:
        return None
    s = str(val).strip()
    if not s:
        return None
    # remove commas etc.
    s = s.replace(",", "")
    try:
        return int(float(s))
    except Exception:
        return None


def max_number_in_text(text):
    if not text:
        return 0
    nums = re.findall(r"\d[\d,]*", str(text))
    parsed = []
    for n in nums:
        n = n.replace(",", "")
        try:
            parsed.append(int(n))
        except Exception:
            continue
    return max(parsed) if parsed else 0


def run():
    # 앱 내부 data 폴더에 있는 엑셀 파일 사용
    project_root = Path(__file__).resolve().parent
    xlsx_path = project_root / "app" / "data" / "moson_policy.xlsx"
    if not xlsx_path.exists():
        print("Excel file not found:", xlsx_path)
        return

    app = create_app()
    with app.app_context():
        # 엑셀은 고정된 구조(열 개수/순서)로 관리된다고 가정하고,
        # 우측 KT/LG/SKB/SKT 공통 블록(통신사/종류/상품/월요금/프로모션/경품/현금/합산)을 기준으로 파싱한다.
        df = pd.read_excel(xlsx_path, sheet_name=0, header=1)
        print("Loaded columns:", list(df.columns))

        # 우측 블록 열 인덱스 기준 매핑
        #  - 32: 통신사 (KT/LG/SKB/SKT)
        #  - 33: 종류
        #  - 34: 구분/상품군
        #  - 35: 상품/속도
        #  - 36: 월요금
        #  - 37~40: 프로모션1~4
        #  - 41: 경품가이드
        #  - 42: 상품권 / 상품권 별도
        #  - 43: 현금 (VAT 포함/별도)
        #  - 44: 상품권+현금 합산 (최종 수수료)
        if len(df.columns) < 45:
            print("Unexpected column count in Excel; expected at least 45 columns.")
            return

        col_telco = df.columns[32]
        col_kind = df.columns[33]
        col_category = df.columns[34]
        col_product = df.columns[35]
        col_month = df.columns[36]
        col_promo1 = df.columns[37]
        col_promo2 = df.columns[38]
        col_promo3 = df.columns[39]
        col_promo4 = df.columns[40]
        col_guide = df.columns[41]
        col_voucher = df.columns[42]
        col_cash_vat = df.columns[43]
        col_total = df.columns[44]

        print("Mapped column names ->")
        print("  telco   :", col_telco)
        print("  kind    :", col_kind)
        print("  category:", col_category)
        print("  product :", col_product)
        print("  month   :", col_month)
        print("  promo1~4:", col_promo1, col_promo2, col_promo3, col_promo4)
        print("  guide   :", col_guide)
        print("  voucher :", col_voucher)
        print("  cash_vat:", col_cash_vat)
        print("  total   :", col_total)

        # 기존 데이터 삭제 후 재적재
        PolicyRow.query.delete()
        db.session.commit()

        rows = 0
        for _, row in df.iterrows():
            telco = (str(row.get(col_telco)).strip()
                     if row.get(col_telco) is not None and str(row.get(col_telco)).strip() not in ("", "nan")
                     else None)
            if not telco:
                # 통신사 정보가 없는 행은 스킵 (헤더/공백/요약 등)
                continue

            kind = (str(row.get(col_kind)).strip()
                    if row.get(col_kind) is not None and str(row.get(col_kind)).strip() not in ("", "nan")
                    else None)
            category = (str(row.get(col_category)).strip()
                        if row.get(col_category) is not None and str(row.get(col_category)).strip() not in ("", "nan")
                        else None)
            product = (str(row.get(col_product)).strip()
                       if row.get(col_product) is not None and str(row.get(col_product)).strip() not in ("", "nan")
                       else None)

            month_fee = parse_int(row.get(col_month))

            # 통신사 공통: 엑셀 37→promo1, 38→promo2, 39→promo3, 40→promo4 (순서 통일)
            def _promo_val(col):
                v = row.get(col)
                if v is None or (isinstance(v, float) and pd.isna(v)):
                    return None
                s = str(v).strip()
                if s in ("", "nan"):
                    return None
                # 숫자면 정수로 정리 (17600.0 → 17600)
                try:
                    n = int(float(s))
                    return str(n)
                except Exception:
                    return s

            promo1 = _promo_val(col_promo1)
            promo2 = _promo_val(col_promo2)
            promo3 = _promo_val(col_promo3)
            promo4 = _promo_val(col_promo4) if telco != "LG" else None

            # LG "기타 추가 상품" 블록은 엑셀에서 열 배치가 다를 수 있음 → 40, 41, 42 중 경품가이드 형식 값 사용
            is_lg_other = (telco or "").strip().upper() == "LG" and (
                "기타" in (kind or "") or "기타" in (category or "")
            )
            if is_lg_other and len(df.columns) > 42:
                # 경품가이드는 보통 문구+금액(숫자) 형태 → 숫자 포함된 열 우선
                def _looks_like_guide(val):
                    if val is None: return False
                    s = str(val).strip()
                    if s in ("", "nan"): return False
                    if s.isdigit(): return False  # 숫자만 있으면 상품권/프로모 열
                    if not re.search(r"\d", s): return False  # 숫자 없으면 경품가이드 아님
                    return True
                for idx in (40, 41, 42):
                    cand = row.get(df.columns[idx])
                    if _looks_like_guide(cand):
                        guide_text = cand
                        break
                else:
                    guide_text = row.get(col_guide)
            else:
                guide_text = row.get(col_guide)
            voucher_val = parse_int(row.get(col_voucher))
            cash_vat_val = parse_int(row.get(col_cash_vat))
            total_fee_val = parse_int(row.get(col_total))

            # 경품가이드 기준 최종 경품금액/현금 계산
            # final_gift 단위: 만원, cash_vat 단위: 원
            final_gift = max_number_in_text(guide_text)
            cash_val = None
            if cash_vat_val is not None:
                cash_val = cash_vat_val - (final_gift * 10000)

            pr = PolicyRow(
                telco=telco,
                kind=kind,
                category=category,
                product_name=product,
                month_fee=month_fee,
                promo1=promo1,
                promo2=promo2,
                promo3=promo3,
                promo4=promo4,
                gift_guide=str(guide_text) if guide_text is not None else None,
                voucher=voucher_val,
                cash_vat=cash_vat_val,
                total_fee=total_fee_val,
                final_gift=final_gift,
                cash=cash_val,
            )
            db.session.add(pr)
            rows += 1

        db.session.commit()
        print(f"Imported {rows} policy rows.")


if __name__ == "__main__":
    run()

