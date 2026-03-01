"""로컬에서 정책 엑셀 → DB import 실행 (app.policy_import 사용)."""
from pathlib import Path

from app import create_app
from app.policy_import import run_policy_import

if __name__ == "__main__":
    project_root = Path(__file__).resolve().parent
    xlsx_path = project_root / "app" / "data" / "moson_policy.xlsx"
    app = create_app()
    success, message, count = run_policy_import(app, xlsx_path=str(xlsx_path) if xlsx_path.exists() else None)
    if success:
        print(message)
    else:
        print("Error:", message)
