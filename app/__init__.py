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

    # Database: store under instance/ (works on Windows, Linux, etc)
    os.makedirs(app.instance_path, exist_ok=True)
    db_path = os.path.join(app.instance_path, "moson.sqlite3")
    app.config["SQLALCHEMY_DATABASE_URI"] = os.getenv("DATABASE_URL", f"sqlite:///{db_path}")
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

    return app
