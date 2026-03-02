# -*- coding: utf-8 -*-
"""정책표 엑셀 → DB import (CLI/웹 공용)."""
import re
import os

def _parse_int(val):
    if val is None:
        return None
    s = str(val).strip()
    if not s or s == "nan":
        return None
    s = s.replace(",", "")
    try:
        return int(float(s))
    except Exception:
        return None


def _max_number_in_text(text):
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


def run_policy_import(app, xlsx_path=None, xlsx_file=None):
    """
    엑셀을 읽어 PolicyRow 테이블에 적재.
    app: Flask app (app_context 밖에서 호출 시 내부에서 push 함).
    xlsx_file: 파일-like 객체(BytesIO 등)가 있으면 이걸 사용 (업로드용).
    xlsx_path: xlsx_file이 없을 때 사용. None이면 app.root_path/data/moson_policy.xlsx.
    Returns: (success: bool, message: str, count: int)
    """
    try:
        import pandas as pd
    except ImportError:
        return False, "pandas가 설치되어 있지 않습니다. pip install pandas openpyxl", 0

    from .extensions import db
    from .models import PolicyRow

    if xlsx_file is not None:
        source = xlsx_file
    else:
        if xlsx_path is None:
            xlsx_path = os.path.join(app.root_path, "data", "moson_policy.xlsx")
        if not os.path.isfile(xlsx_path):
            return False, f"엑셀 파일이 없습니다. 서버에 moson_policy.xlsx를 두거나, 아래에서 엑셀 파일을 업로드해 주세요.", 0
        source = xlsx_path

    with app.app_context():
        try:
            try:
                df = pd.read_excel(source, sheet_name=0, header=1)
            except Exception as e:
                return False, f"엑셀 읽기 실패: {e}", 0

            # 현재 moson_policy.xlsx 원본 구조(10열 기준)에 맞춰
            # 열 위치(인덱스)만으로 매핑한다.
            col_count = len(df.columns)
            if col_count < 9:
                return False, f"엑셀 열 개수가 너무 적습니다 (현재 {col_count}열, 최소 9열 필요).", 0

            cols = list(df.columns)
            col_telco = cols[0]     # 통신사
            col_kind = cols[1]      # 종류
            col_category = cols[2]  # 구분
            col_product = cols[3]   # 상품명
            col_month = cols[4]     # 월요금
            col_guide = cols[5]     # 경품가이드
            col_voucher = cols[6]   # 상품권
            col_cash_vat = cols[7]  # 현금 VAT포함
            col_total = cols[8]     # 합산(상품권+현금 등)

            # 프로모션 컬럼은 현재 10열 원본에서는 별도로 사용하지 않으므로 None 처리
            col_promo1 = None
            col_promo2 = None
            col_promo3 = None
            col_promo4 = None

            PolicyRow.query.delete()
            db.session.commit()

            rows = 0
            for _, row in df.iterrows():
                telco = (str(row.get(col_telco)).strip()
                         if row.get(col_telco) is not None and str(row.get(col_telco)).strip() not in ("", "nan")
                         else None)
                if not telco:
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

                month_fee = _parse_int(row.get(col_month))

                guide_text = row.get(col_guide)
                voucher_val = _parse_int(row.get(col_voucher))
                cash_vat_val = _parse_int(row.get(col_cash_vat))
                total_fee_val = _parse_int(row.get(col_total))

                final_gift = _max_number_in_text(guide_text)
                cash_val = None
                if cash_vat_val is not None:
                    cash_val = cash_vat_val - (final_gift * 10000)

                pr = PolicyRow(
                    telco=telco,
                    kind=kind,
                    category=category,
                    product_name=product,
                    month_fee=month_fee,
                    promo1=None,
                    promo2=None,
                    promo3=None,
                    promo4=None,
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
        except Exception as e:
            return False, str(e), 0

    return True, f"정책 데이터 {rows}건을 불러왔습니다.", rows
