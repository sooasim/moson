from sqlalchemy import text

from app import create_app
from app.extensions import db


def run():
    app = create_app()
    with app.app_context():
        engine = db.engine
        with engine.begin() as conn:
            try:
                conn.execute(
                    text("ALTER TABLE consult_status ADD COLUMN reason VARCHAR(50)")
                )
                print("Added column reason to consult_status")
            except Exception as e:
                print(f"Skip adding reason column: {e}")


if __name__ == "__main__":
    run()

