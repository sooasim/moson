import re
from flask import current_app, request
from .models import Reseller

def _strip_port(host: str) -> str:
    if not host:
        return ""
    return host.split(":")[0].strip().lower()

def get_subdomain_from_request() -> str | None:
    """Return subdomain string if request is to a dealer subdomain."""
    # For local/dev testing: http://localhost:5000/?dealer=abc
    forced = request.args.get("dealer")
    if forced:
        forced = forced.strip().lower()
        if forced and forced != "www":
            return forced

    host = _strip_port(request.host)
    base = current_app.config.get("BASE_DOMAIN", "moson.life").lower()

    # If host is an IP or localhost, no subdomain
    if host in ("localhost", "127.0.0.1") or re.match(r"^\d+\.\d+\.\d+\.\d+$", host):
        return None

    if host == base:
        # 본사/공용 도메인에서도 첫 방문 대리점 귀속 쿠키가 있으면 이를 우선 사용
        if request.path.startswith("/admin"):
            return None
        cookie_sub = (request.cookies.get("moson_affiliate") or "").strip().lower()
        if cookie_sub and cookie_sub != "www":
            return cookie_sub
        return None
    if host.endswith("." + base):
        prefix = host[: -(len(base) + 1)]
        if prefix in ("", "www"):
            return None
        return prefix
    # If user uses something like abc.localhost
    parts = host.split(".")
    if len(parts) >= 2 and parts[-1] == "localhost":
        return parts[0]
    return None

def get_tenant() -> Reseller | None:
    sub = get_subdomain_from_request()
    if not sub:
        return None
    return Reseller.query.filter_by(subdomain=sub).first()
