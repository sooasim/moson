from sqlalchemy import text

from app import create_app
from app.extensions import db


def run():
    app = create_app()
    with app.app_context():
        engine = db.engine
        with engine.begin() as conn:
            for col, col_type in [
                ("representative", "VARCHAR(100)"),
                ("bank_name", "VARCHAR(100)"),
                ("bank_account", "VARCHAR(100)"),
                ("is_active", "BOOLEAN DEFAULT 1"),
                ("deleted_at", "DATETIME"),
            ]:
                try:
                    conn.execute(
                        text(f"ALTER TABLE resellers ADD COLUMN {col} {col_type}")
                    )
                    print(f"Added column {col}")
                except Exception as e:  # 이미 존재하거나 기타 오류 시 무시
                    print(f"Skip adding column {col}: {e}")


if __name__ == "__main__":
    run()

