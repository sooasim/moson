from flask import Flask
from werkzeug.middleware.proxy_fix import ProxyFix
from dotenv import load_dotenv
import os

from .extensions import db
from .routes import bp as routes_bp

def create_app():
    load_dotenv()

    app = Flask(__name__, instance_relative_config=True)
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_port=1, x_prefix=1)

    # Secret key
    app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "dev-secret-change-me")

    # Database: Railway Postgres uses DATABASE_URL; locally defaults to SQLite
    database_url = os.getenv("DATABASE_URL")
    if database_url:
        # Railway/Heroku use "postgres://", SQLAlchemy 1.4+ needs "postgresql://"
        if database_url.startswith("postgres://"):
            database_url = "postgresql://" + database_url[9:]
        app.config["SQLALCHEMY_DATABASE_URI"] = database_url
    else:
        os.makedirs(app.instance_path, exist_ok=True)
        db_path = os.path.join(app.instance_path, "moson.sqlite3")
        app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{db_path}"
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

    # Domain settings
    app.config["BASE_DOMAIN"] = os.getenv("MOSON_BASE_DOMAIN", "moson.life")
    app.config["MOSON_EMAIL"] = os.getenv("MOSON_EMAIL", "mosoncp@gmail.com")

    # Admin login (main)
    app.config["ADMIN_USERNAME"] = os.getenv("MOSON_ADMIN_USERNAME", "admin")
    app.config["ADMIN_PASSWORD"] = os.getenv("MOSON_ADMIN_PASSWORD", "admin1234")

    # Email sending backends
    # 1) Resend API (우선 사용)
    app.config["RESEND_API_KEY"] = os.getenv("RESEND_API_KEY")
    app.config["RESEND_FROM"] = os.getenv("RESEND_FROM")

    # 2) SMTP (로컬/백업용)
    app.config["SMTP_HOST"] = os.getenv("SMTP_HOST")
    app.config["SMTP_PORT"] = int(os.getenv("SMTP_PORT", "587"))
    app.config["SMTP_USER"] = os.getenv("SMTP_USER")
    app.config["SMTP_PASS"] = os.getenv("SMTP_PASS")
    app.config["SMTP_FROM"] = os.getenv("SMTP_FROM", app.config["MOSON_EMAIL"])
    app.config["SMTP_TLS"] = os.getenv("SMTP_TLS", "1") == "1"

    # Cloudflare (optional: for per-subdomain DNS record creation)
    app.config["CLOUDFLARE_API_TOKEN"] = os.getenv("CLOUDFLARE_API_TOKEN")
    app.config["CLOUDFLARE_ZONE_ID"] = os.getenv("CLOUDFLARE_ZONE_ID")
    app.config["CLOUDFLARE_DNS_TARGET"] = os.getenv("CLOUDFLARE_DNS_TARGET")  # IP or CNAME target
    app.config["CLOUDFLARE_PROXIED"] = os.getenv("CLOUDFLARE_PROXIED", "1") == "1"
    app.config["DB_HEALTH_OK"] = True
    app.config["DB_HEALTH_ERROR"] = None

    db.init_app(app)
    app.register_blueprint(routes_bp)

    with app.app_context():
        try:
            db.create_all()
            from .db_migrate import run_schema_patches
            run_schema_patches(app, db)
            # 정책표 자동 불러오기: 로컬(SQLite)에서만 실행. 배포(Postgres)에서는 절대 자동 불러오기 하지 않음.
            # → 커밋/푸시 후 재배포해도 DB에 저장된 수정 내용이 유지됨. 초기 데이터는 어드민 정책표 페이지에서 엑셀 업로드로만 반영.
            if not database_url:
                from .models import PolicyRow
                if PolicyRow.query.count() == 0:
                    xlsx_path = os.path.join(app.root_path, "data", "moson_policy.xlsx")
                    if os.path.isfile(xlsx_path):
                        try:
                            from .policy_import import run_policy_import
                            run_policy_import(app, xlsx_path=xlsx_path)
                        except Exception:
                            pass
        except Exception as e:
            # DB가 일시적으로 죽어도 앱은 뜨게 하고, 어드민에서 경고를 표시한다.
            app.config["DB_HEALTH_OK"] = False
            app.config["DB_HEALTH_ERROR"] = str(e)
            app.logger.exception("Database initialization failed: %s", e)

    return app
