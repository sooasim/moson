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

    # Enable/disable real SMTP sending (fallback prints to console)
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

    db.init_app(app)
    app.register_blueprint(routes_bp)

    with app.app_context():
        db.create_all()
        # 정책 데이터가 없고 엑셀 파일이 있으면 자동 불러오기 (배포 시 초기 데이터 적재)
        from .models import PolicyRow
        if PolicyRow.query.count() == 0:
            xlsx_path = os.path.join(app.root_path, "data", "moson_policy.xlsx")
            if os.path.isfile(xlsx_path):
                try:
                    from .policy_import import run_policy_import
                    run_policy_import(app, xlsx_path=xlsx_path)
                except Exception:
                    pass  # 실패 시 무시 (로컬에 엑셀 없을 수 있음)

    return app
