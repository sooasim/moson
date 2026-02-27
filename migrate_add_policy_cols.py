from pathlib import Path

from app import create_app
from app.extensions import db


def run():
    """policy_rows 테이블에 신규 컬럼들을 추가하는 간단한 마이그레이션."""
    app = create_app()
    with app.app_context():
        engine = db.engine
        conn = engine.connect()

        def add_column_if_missing(col_sql: str):
            try:
                conn.execute(db.text(col_sql))
                print("OK:", col_sql)
            except Exception as e:
                # 이미 존재하는 경우 등은 조용히 무시
                print("SKIP:", col_sql, "->", e)

        # SQLite 기준 ALTER TABLE ADD COLUMN (이미 있으면 예외)
        stmts = [
            "ALTER TABLE policy_rows ADD COLUMN kind VARCHAR(100)",
            "ALTER TABLE policy_rows ADD COLUMN category VARCHAR(100)",
            "ALTER TABLE policy_rows ADD COLUMN month_fee INTEGER",
            "ALTER TABLE policy_rows ADD COLUMN promo1 VARCHAR(100)",
            "ALTER TABLE policy_rows ADD COLUMN promo2 VARCHAR(100)",
            "ALTER TABLE policy_rows ADD COLUMN promo3 VARCHAR(100)",
            "ALTER TABLE policy_rows ADD COLUMN promo4 VARCHAR(100)",
            "ALTER TABLE policy_rows ADD COLUMN voucher INTEGER",
            "ALTER TABLE policy_rows ADD COLUMN total_fee INTEGER",
        ]

        for sql in stmts:
            add_column_if_missing(sql)

        conn.close()
        print("migration done.")


if __name__ == "__main__":
    run()

