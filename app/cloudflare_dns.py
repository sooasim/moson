import requests
from flask import current_app

def ensure_dns_record(subdomain: str) -> tuple[bool, str]:
    """Optionally create/ensure a DNS record in Cloudflare for subdomain.

    If you set a wildcard DNS (*.base_domain) in Cloudflare, you DON'T need this.
    This exists for the '자동 생성' 버튼 느낌을 MVP에서 지원하기 위한 옵션입니다.
    """
    token = current_app.config.get("CLOUDFLARE_API_TOKEN")
    zone_id = current_app.config.get("CLOUDFLARE_ZONE_ID")
    target = current_app.config.get("CLOUDFLARE_DNS_TARGET")  # IP or CNAME value
    proxied = current_app.config.get("CLOUDFLARE_PROXIED", True)
    base = current_app.config.get("BASE_DOMAIN")

    if not token or not zone_id or not target or not base:
        return False, "Cloudflare 설정이 비어 있어 DNS 자동 생성은 건너뜁니다. (와일드카드 DNS 추천)"

    name = f"{subdomain}.{base}".lower()

    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    # Create A record if target looks like IP else CNAME
    record_type = "A" if _looks_like_ip(target) else "CNAME"
    payload = {"type": record_type, "name": name, "content": target, "ttl": 1, "proxied": bool(proxied)}

    url = f"https://api.cloudflare.com/client/v4/zones/{zone_id}/dns_records"
    try:
        r = requests.post(url, headers=headers, json=payload, timeout=12)
        data = r.json()
        if data.get("success"):
            return True, "Cloudflare DNS 레코드가 생성되었습니다."
        # If already exists, that's fine
        errors = data.get("errors") or []
        msg = "; ".join([e.get("message","") for e in errors]) or "unknown error"
        if "already exists" in msg.lower():
            return True, "이미 DNS 레코드가 존재합니다."
        return False, f"Cloudflare DNS 생성 실패: {msg}"
    except Exception as e:
        return False, f"Cloudflare DNS 생성 예외: {e}"

def _looks_like_ip(s: str) -> bool:
    parts = (s or "").strip().split(".")
    if len(parts) != 4:
        return False
    try:
        return all(0 <= int(p) <= 255 for p in parts)
    except Exception:
        return False
