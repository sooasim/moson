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

            cols = list(df.columns)

            def _find_col(patterns):
                """헤더 텍스트에 특정 키워드가 포함된 열을 찾는다."""
                for c in cols:
                    name = str(c)
                    if any(p in name for p in patterns):
                        return c
                return None

            # 필수 열 매핑 (헤더 이름 기준)
            col_telco = _find_col(["통신사", "도매"])
            col_kind = _find_col(["종류"])
            col_category = _find_col(["구분"])
            col_product = _find_col(["상품명"])
            col_month = _find_col(["월요금", "요금"])
            col_guide = _find_col(["경품가이드", "경품 가이드"])
            col_voucher = _find_col(["상품권"])
            col_cash_vat = _find_col(["현금", "VAT"])
            col_total = _find_col(["합산", "상품권+현금", "총수수료", "최종수수료"])

            if not (col_telco and col_product and (col_guide or col_cash_vat)):
                return False, "엑셀 헤더를 인식할 수 없습니다. 통신사/상품명/경품가이드(또는 현금 VAT포함) 열 이름을 확인해 주세요.", 0

            # 프로모션 열은 나머지 열 중에서 순서대로 최대 4개까지 사용
            essential = {
                col_telco,
                col_kind,
                col_category,
                col_product,
                col_month,
                col_guide,
                col_voucher,
                col_cash_vat,
                col_total,
            }
            promo_candidates = [c for c in cols if c not in essential]
            col_promo1 = promo_candidates[0] if len(promo_candidates) > 0 else None
            col_promo2 = promo_candidates[1] if len(promo_candidates) > 1 else None
            col_promo3 = promo_candidates[2] if len(promo_candidates) > 2 else None
            col_promo4 = promo_candidates[3] if len(promo_candidates) > 3 else None

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

                def _promo_val(col):
                    v = row.get(col)
                    if v is None or (isinstance(v, float) and pd.isna(v)):
                        return None
                    s = str(v).strip()
                    if s in ("", "nan"):
                        return None
                    try:
                        return str(int(float(s)))
                    except Exception:
                        return s

                promo1 = _promo_val(col_promo1) if col_promo1 is not None else None
                promo2 = _promo_val(col_promo2) if col_promo2 is not None else None
                promo3 = _promo_val(col_promo3) if col_promo3 is not None else None
                promo4 = _promo_val(col_promo4) if col_promo4 is not None else None

                # LG 기타 특수 처리 등은 제거하고, 경품가이드는 항상 지정된 열에서만 읽는다.
                guide_text = row.get(col_guide) if col_guide is not None else None

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
        except Exception as e:
            return False, str(e), 0

    return True, f"정책 데이터 {rows}건을 불러왔습니다.", rows
