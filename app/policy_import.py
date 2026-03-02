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
                # 현재 moson_policy.xlsx 원본(140행 × 12열) 구조를 그대로 사용
                # 통신사별 헤더/데이터가 0~11열에 위치함 (KT/LG/SKB/SKT 공통)
                df = pd.read_excel(source, sheet_name=0, header=None)
            except Exception as e:
                return False, f"엑셀 읽기 실패: {e}", 0

            col_count = len(df.columns)
            if col_count < 11:
                return False, f"엑셀 열 개수가 너무 적습니다 (현재 {col_count}열, 최소 11열 필요).", 0

            def _get_str(row, idx, max_len=None):
                v = row[idx] if idx < len(row) else None
                if v is None or (isinstance(v, float) and pd.isna(v)):
                    return None
                s = str(v).strip()
                if not s or s.lower() == "nan":
                    return None
                if max_len is not None:
                    return s[:max_len]
                return s

            PolicyRow.query.delete()
            db.session.commit()

            rows = 0
            current_telco = None  # "KT 도매" / "LG 도매" / "SKB 도매" / "SKT 도매"

            for idx, row in df.iterrows():
                c0 = _get_str(row, 0)
                upper0 = (c0 or "").upper()

                # 통신사 섹션 헤더 감지
                if c0 and "KT" in upper0:
                    current_telco = "KT 도매"
                    continue
                if c0 and "LG" in upper0:
                    current_telco = "LG 도매"
                    continue
                if c0 and "SKB" in upper0:
                    current_telco = "SKB 도매"
                    continue
                if c0 and "SKT" in upper0:
                    current_telco = "SKT 도매"
                    continue

                if current_telco is None:
                    # 아직 어떤 통신사 블록인지 모르면 스킵
                    continue

                # 헤더 행(종류/상품명/월요금 등) 스킵
                c2 = _get_str(row, 2)
                c3 = _get_str(row, 3)
                if (c0 and "종류" in c0) or (c2 and "상품" in c2) or (c3 and "월요금" in c3):
                    continue

                # 데이터가 거의 없는 메모/빈 행 스킵
                core_vals = [row.get(i) for i in range(2, 11)]
                if all((v is None or (isinstance(v, float) and pd.isna(v))) for v in core_vals):
                    continue

                telco = current_telco

                # 통신사별 열 매핑
                if telco.startswith("KT"):
                    # 0:종류, 1:구분, 2:상품명, 3:월요금, 4~7:정액/총액/프리미엄, 8:경품가이드, 9:상품권, 10:현금VAT, 11:합산
                    kind = _get_str(row, 0, 100)
                    category = _get_str(row, 1, 100)
                    product = _get_str(row, 2, 200)
                    month_fee = _parse_int(row.get(3))
                    promo1 = _get_str(row, 4, 100)
                    promo2 = _get_str(row, 5, 100)
                    promo3 = _get_str(row, 6, 100)
                    promo4 = _get_str(row, 7, 100)
                    guide_text = _get_str(row, 8, 400)
                    voucher_val = _parse_int(row.get(9))
                    cash_vat_val = _parse_int(row.get(10))
                    total_fee_val = _parse_int(row.get(11))
                elif telco.startswith("LG"):
                    # 0:종류, 1:구분, 2:상품명, 3:월요금, 4:참쉬운, 5:투게더, 6:인터넷끼리, 7:경품가이드, 8:상품권, 9:현금VAT, 10:상품권+현금VAT
                    kind = _get_str(row, 0, 100)
                    category = _get_str(row, 1, 100)
                    product = _get_str(row, 2, 200)
                    month_fee = _parse_int(row.get(3))
                    promo1 = _get_str(row, 4, 100)
                    promo2 = _get_str(row, 5, 100)
                    promo3 = _get_str(row, 6, 100)
                    promo4 = None
                    guide_text = _get_str(row, 7, 400)
                    voucher_val = _parse_int(row.get(8))
                    cash_vat_val = _parse_int(row.get(9))
                    total_fee_val = _parse_int(row.get(10))
                elif telco.startswith("SKB"):
                    # 0:종류, 1:상품명, 2:월요금, 3:요즘가족, 4:패밀리, 5:1년미만, 6:2년미만, 7:3년미만, 8:3년이상, 9:경품가이드, 10:현금VAT
                    kind = _get_str(row, 0, 100)
                    category = None
                    product = _get_str(row, 1, 200)
                    month_fee = _parse_int(row.get(2))
                    promo1 = _get_str(row, 3, 100)
                    promo2 = _get_str(row, 4, 100)
                    promo3 = _get_str(row, 5, 100)
                    promo4 = _get_str(row, 6, 100)
                    guide_text = _get_str(row, 9, 400)
                    voucher_val = None
                    cash_vat_val = _parse_int(row.get(10))
                    total_fee_val = None
                else:  # SKT
                    # 구조는 SKB와 동일
                    kind = _get_str(row, 0, 100)
                    category = None
                    product = _get_str(row, 1, 200)
                    month_fee = _parse_int(row.get(2))
                    promo1 = _get_str(row, 3, 100)
                    promo2 = _get_str(row, 4, 100)
                    promo3 = _get_str(row, 5, 100)
                    promo4 = _get_str(row, 6, 100)
                    guide_text = _get_str(row, 9, 400)
                    voucher_val = None
                    cash_vat_val = _parse_int(row.get(10))
                    total_fee_val = None

                # 상품명/월요금도 비어 있으면 최종적으로 스킵
                if not product and month_fee is None:
                    continue

                final_gift = _max_number_in_text(guide_text)
                cash_val = None
                if cash_vat_val is not None and final_gift is not None:
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
                    gift_guide=guide_text,
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
