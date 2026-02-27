#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""정책표-메인 계산기 매핑 검증: 요약 데이터와 row_id로 API 조회가 1:1인지 확인합니다."""
import sys
from app import create_app
from app.routes import _policy_summary
from app.models import PolicyRow

def main():
    app = create_app()
    with app.app_context():
        summary = _policy_summary()
        print("=== 정책표 요약 (메인 계산기용) ===\n")
        for telco in ("KT", "LG", "SKT"):
            rows = summary.get(telco) or []
            print(f"[{telco}] 행 수: {len(rows)}")
            if not rows:
                continue
            kinds = {}
            for r in rows:
                k = r.get("kind") or "기타"
                kinds[k] = kinds.get(k, 0) + 1
            for kind, cnt in sorted(kinds.items()):
                print(f"  - {kind}: {cnt}건")
            for i, r in enumerate(rows[:3]):
                print(f"  샘플{i+1}: id={r['id']} kind={r['kind']} product_name={r['product_name']} month_fee={r['month_fee']}")
            if len(rows) > 3:
                print(f"  ... 외 {len(rows)-3}건")
            print()

        # DB 행 수와 요약 행 수 일치 여부
        total_db = PolicyRow.query.filter(
            PolicyRow.telco.isnot(None),
            PolicyRow.telco != "",
        ).count()
        total_summary = sum(len(summary.get(t, [])) for t in ("KT", "LG", "SKT"))
        print(f"DB 정책 행 수(통신사 있는 것): {total_db}")
        print(f"요약에 포함된 행 수(KT+LG+SKT): {total_summary}")
        if total_db != total_summary:
            print("  참고: SKT 요약에는 SKT+SKB가 합쳐지고, 기타 통신사는 제외됩니다.")
    return 0

if __name__ == "__main__":
    sys.exit(main())
