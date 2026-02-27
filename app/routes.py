from __future__ import annotations

import secrets
import json
from datetime import datetime, timedelta
from flask import Blueprint, current_app, render_template, request, redirect, url_for, session, flash, jsonify
from werkzeug.security import generate_password_hash, check_password_hash

from .extensions import db
from .models import Reseller, ConsultRequest, VisitLog, ConsultStatus, ResellerApplication, EmailLog, PolicyRow, AdminUser
from .tenant import get_tenant
from .emailer import send_email
from .cloudflare_dns import ensure_dns_record

bp = Blueprint("routes", __name__)

@bp.app_context_processor
def inject_globals():
    tenant = get_tenant()
    return {
        "tenant": tenant,
        "base_domain": current_app.config.get("BASE_DOMAIN"),
    }


@bp.app_template_filter("to_kst")
def to_kst(dt):
    """UTC datetime을 대한민국 표준시(KST, +9시간)로 변환."""
    if not dt:
        return dt
    try:
        return dt + timedelta(hours=9)
    except Exception:
        return dt


@bp.before_app_request
def log_visit():
    """간단한 접속 로그 (IP / UA / 디바이스 / 봇 여부)를 남깁니다."""
    # 정적 파일 및 파비콘은 스킵
    if request.path.startswith(("/static/", "/favicon.ico")):
        return

    ua = request.headers.get("User-Agent", "") or ""
    ua_lower = ua.lower()

    # 봇/크롤러 판별 (간단한 패턴)
    bot_keywords = ["bot", "spider", "crawl", "slurp", "bingpreview", "facebookexternalhit", "pingdom"]
    is_bot = any(k in ua_lower for k in bot_keywords)

    # 디바이스 유형 판별
    mobile_keywords = ["iphone", "android", "ipad", "ipod", "mobile"]
    is_mobile = any(k in ua_lower for k in mobile_keywords)
    is_desktop = not is_mobile

    # IP 추출 (프록시 환경 고려)
    ip = (request.headers.get("X-Forwarded-For") or request.remote_addr or "").split(",")[0].strip() or None

    tenant = get_tenant()
    reseller_id = tenant.id if tenant else None

    v = VisitLog(
        reseller_id=reseller_id,
        path=request.path[:255],
        method=(request.method or "GET")[:10],
        ip=ip[:64] if ip else None,
        user_agent=ua[:400] or None,
        referrer=(request.referrer or "")[:400] or None,
        is_bot=is_bot,
        is_mobile=is_mobile,
        is_desktop=is_desktop,
        is_admin=request.path.startswith("/admin"),
    )
    try:
        db.session.add(v)
        db.session.commit()
    except Exception:
        db.session.rollback()

def _tenant_context():
    tenant = get_tenant()
    moson_email = current_app.config.get("MOSON_EMAIL")
    if tenant:
        return {
            "tenant_company_name": tenant.company_name,
            "tenant_phone": tenant.phone,
            "tenant_email": tenant.email,
            "moson_email": moson_email,
            "tenant_subdomain": tenant.subdomain,
            "is_dealer_site": True,
        }
    return {
        "tenant_company_name": "MOSON 본사",
        "tenant_phone": "010-2397-7463",
        "tenant_email": moson_email,
        "moson_email": moson_email,
        "tenant_subdomain": None,
        "is_dealer_site": False,
    }

def _partners_json():
    # We embed tel.txt content (300 lines) into page JS.
    import json, os
    tel_path = os.path.join(current_app.root_path, "data", "tel.txt")
    partners = []
    try:
        with open(tel_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                parts = line.split("\t")
                if len(parts) >= 3 and parts[0].isdigit():
                    partners.append({"idx": int(parts[0]), "name": parts[1].strip(), "phone": parts[2].strip()})
    except Exception:
        partners = []
    return json.dumps(partners, ensure_ascii=False)


def _policy_summary():
    """랜딩 페이지 견적기: 정책표 행 단위로 100% 매칭용 데이터.
    통신사별로 행 리스트를 제공하고, 각 항목은 row_id로 API 조회 시 정확히 한 행과 매칭.
    """
    result = {}
    rows = (
        PolicyRow.query.filter(
            PolicyRow.telco.isnot(None),
            PolicyRow.telco != "",
        )
        .order_by(PolicyRow.telco.asc(), PolicyRow.kind.asc().nullslast(), PolicyRow.category.asc().nullslast(), PolicyRow.product_name.asc().nullslast(), PolicyRow.id.asc())
        .all()
    )
    for r in rows:
        tel = (r.telco or "").strip().upper()
        if tel.startswith("KT"):
            logical_telco = "KT"
        elif tel.startswith("LG"):
            logical_telco = "LG"
        elif tel in ("SKT", "SKB"):
            logical_telco = "SKT"
        else:
            continue

        entry = {
            "id": r.id,
            "kind": (r.kind or "").strip() or "기타",
            "category": (r.category or "").strip() or "",
            "product_name": (r.product_name or "").strip() or "-",
            "month_fee": r.month_fee,
        }
        result.setdefault(logical_telco, []).append(entry)

    return result


@bp.get("/")
def landing():
    ctx = _tenant_context()
    policy_summary = _policy_summary()
    return render_template(
        "landing.html",
        partners_json=_partners_json(),
        policy_summary_json=json.dumps(policy_summary, ensure_ascii=False),
        **ctx,
    )


@bp.get("/api/policy-quote")
def api_policy_quote():
    """정책표 기반 예상 현금지원액 조회. row_id 우선(100% 매칭), 없으면 telco+kind+product로 조회."""
    row_id_param = request.args.get("row_id", type=int)
    if row_id_param is not None and row_id_param > 0:
        row = PolicyRow.query.get(row_id_param)
        if row is None:
            return jsonify({"ok": False, "error": "policy row not found"}), 404
        cash_support = (row.final_gift or 0) * 10000
        voucher = (row.voucher or 0) if (row.telco or "").strip().upper().startswith("KT") else 0
        total_cash = cash_support + voucher
        return jsonify({
            "ok": True,
            "cash_support": cash_support,
            "voucher": voucher,
            "total_cash": total_cash,
            "month_fee": row.month_fee,
            "telco": row.telco or "",
            "has_voucher": (row.telco or "").strip().upper().startswith("KT"),
        })

    telco = (request.args.get("telco") or "").strip().upper()
    speed = (request.args.get("speed") or "").strip()
    kind = (request.args.get("kind") or "").strip()
    product = (request.args.get("product") or "").strip()

    if not speed and not product:
        return jsonify({"ok": False, "error": "row_id or (speed/product) required"}), 400

    def _query_by_product(telco_filter):
        q = PolicyRow.query.filter(PolicyRow.product_name == product)
        if kind:
            q = q.filter(PolicyRow.kind == kind)
        if telco_filter is not None:
            q = q.filter(telco_filter)
        return q.order_by(PolicyRow.final_gift.desc().nullslast()).all()

    if product:
        if telco == "ANY":
            rows = _query_by_product(None)
        elif telco == "SKT":
            rows = _query_by_product(PolicyRow.telco.in_(["SKT", "SKB"]))
        else:
            rows = _query_by_product(PolicyRow.telco == telco)
    else:
        speed_map = {"100M": ("100M", "100"), "500M": ("500M", "500"), "1G": ("1G", "1G")}
        product_candidates = speed_map.get(speed) or (speed,)

        def _query_rows(telco_filter):
            for prod in product_candidates:
                if telco_filter is None:
                    q = PolicyRow.query.filter(PolicyRow.product_name == prod)
                else:
                    q = PolicyRow.query.filter(telco_filter, PolicyRow.product_name == prod)
                rs = q.order_by(PolicyRow.final_gift.desc().nullslast()).all()
                if rs:
                    return rs
            return []

        if telco == "ANY":
            rows = _query_rows(None)
        elif telco == "SKT":
            rows = _query_rows(PolicyRow.telco.in_(["SKT", "SKB"]))
        else:
            rows = _query_rows(PolicyRow.telco == telco)

    row = rows[0] if rows else None
    if not row:
        return jsonify({"ok": True, "cash_support": 0, "voucher": 0, "total_cash": 0, "month_fee": None, "telco": telco, "has_voucher": False})

    cash_support = (row.final_gift or 0) * 10000
    voucher = (row.voucher or 0) if (row.telco or "").strip().upper().startswith("KT") else 0
    total_cash = cash_support + voucher
    return jsonify({
        "ok": True,
        "cash_support": cash_support,
        "voucher": voucher,
        "total_cash": total_cash,
        "month_fee": row.month_fee,
        "telco": row.telco or telco,
        "has_voucher": (row.telco or "").strip().upper().startswith("KT"),
    })


@bp.get("/api/quote-bids")
def api_quote_bids():
    """실시간 견적 입찰용 가상 견적 생성 API."""
    row_id = request.args.get("row_id", type=int)
    if not row_id:
        return jsonify({"ok": False, "error": "row_id required"}), 400

    row = PolicyRow.query.get(row_id)
    if not row:
        return jsonify({"ok": False, "error": "policy row not found"}), 404

    import re, random, os

    nums = []
    if row.gift_guide:
        for n in re.findall(r"\d[\d,]*", str(row.gift_guide)):
            n = n.replace(",", "")
            try:
                nums.append(int(n))
            except Exception:
                continue

    if not nums and row.final_gift:
        nums = [row.final_gift]

    if not nums:
        base_min = 30
        base_max = 50
    else:
        base_min = min(nums)
        base_max = max(nums)

    # 만원 단위를 원으로 변환하되, 값이 하나뿐이면 ±20% 범위로 다양화
    if base_min == base_max:
        low = max(1, int(base_min * 0.8))
        high = int(base_min * 1.2)
    else:
        low = base_min
        high = base_max

    def _rand_amount():
        return random.randint(low, high) * 10000

    # 제휴 대리점 10곳 랜덤 선택 (data/tel.txt 기반)
    tel_path = os.path.join(current_app.root_path, "data", "tel.txt")
    partners = []
    try:
        with open(tel_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                parts = line.split("\t")
                if len(parts) >= 2:
                    partners.append({"idx": parts[0], "name": parts[1].strip()})
    except Exception:
        partners = []

    competitors = []
    if partners:
        sample = random.sample(partners, k=min(10, len(partners)))
        for i, p in enumerate(sample):
            competitors.append({"name": p["name"], "amount": _rand_amount()})
    else:
        for i in range(10):
            competitors.append({"name": f"제휴대리점 {i+1}", "amount": _rand_amount()})

    max_comp = max(c["amount"] for c in competitors) if competitors else _rand_amount()
    reward_extra_min = 30000
    reward_extra_max = 150000
    reward_extra = random.randint(reward_extra_min // 10000, reward_extra_max // 10000) * 10000
    moson_amount = max_comp + reward_extra

    return jsonify({
        "ok": True,
        "base_min": base_min * 10000,
        "base_max": base_max * 10000,
        "competitors": competitors,
        "max_competitor": max_comp,
        "top": {
            "name": "모손라이프",
            "amount": moson_amount,
            "reward_extra_min": reward_extra_min,
            "reward_extra_max": reward_extra_max,
        },
    })


@bp.route("/partner/apply", methods=["GET", "POST"])
def partner_apply():
    """부업 파트너(대리점) 신청 페이지."""
    if request.method == "POST":
        subdomain = (request.form.get("subdomain") or "").strip().lower()
        company_name = (request.form.get("company_name") or "").strip()
        representative = (request.form.get("representative") or "").strip() or None
        phone = (request.form.get("phone") or "").strip()
        email = (request.form.get("email") or "").strip()
        bank_name = (request.form.get("bank_name") or "").strip() or None
        bank_account = (request.form.get("bank_account") or "").strip() or None

        # 간단한 서브도메인 형식 검증
        import re

        if not re.fullmatch(r"[a-z0-9-]{2,32}", subdomain or ""):
            flash("서브도메인은 영문 소문자/숫자/하이픈 2~32자만 가능합니다.", "error")
            return render_template("partner_apply.html", title="부업 파트너 신청")

        app_row = ResellerApplication(
            subdomain=subdomain,
            company_name=company_name,
            representative=representative,
            phone=phone,
            email=email,
            bank_name=bank_name,
            bank_account=bank_account,
        )
        db.session.add(app_row)
        db.session.commit()

        flash("부업 파트너 신청이 접수되었습니다. 운영진이 검토 후 연락드립니다.")
        return redirect(url_for("routes.landing", partner="1"))

    return render_template("partner_apply.html", title="부업 파트너 신청")

@bp.get("/favicon.ico")
def favicon():
    # avoid 404 noise
    from flask import send_from_directory
    import os
    # 앱 데이터 폴더에 있는 ff.png 를 파비콘으로 사용
    return send_from_directory(os.path.join(current_app.root_path, "data"), "ff.png")


@bp.post("/consult")
def submit_consult():
    tenant = get_tenant()
    source_host = request.host

    # 계산기와 연동된 견적 정보 (row_id 기반)
    quote_row_id_raw = request.form.get("quote_row_id")
    try:
        quote_row_id = int(quote_row_id_raw) if quote_row_id_raw else None
    except ValueError:
        quote_row_id = None
    quote_telco = (request.form.get("quote_telco") or "").strip() or None
    quote_kind = (request.form.get("quote_kind") or "").strip() or None
    quote_product = (request.form.get("quote_product_name") or "").strip() or None
    quote_month_fee = (request.form.get("quote_month_fee") or "").strip() or None
    quote_cash = (request.form.get("quote_cash_support") or "").strip() or None

    if quote_row_id:
        # 현금지원액 계산기에서 선택한 상품 기준
        telcos_str = quote_telco
        prods_str = " / ".join(
            [p for p in [quote_kind, quote_product] if p]
        ) or None
        bundle = quote_kind
        speed = None
    else:
        # 기존 체크박스 기반 (복수 선택)
        telcos = request.form.getlist("telco")
        prods = request.form.getlist("prod")
        telcos_str = ", ".join(telcos) if telcos else None
        prods_str = ", ".join(prods) if prods else None
        bundle = None
        speed = None

    customer_name = (request.form.get("customer_name") or "").strip() or None
    customer_phone = (request.form.get("customer_phone") or "").strip() or None

    r = ConsultRequest(
        reseller_id=tenant.id if tenant else None,
        source_host=source_host,
        customer_name=customer_name,
        customer_phone=customer_phone,
        telcos=telcos_str,
        products=prods_str,
        bundle=bundle,
        speed=speed,
    )
    db.session.add(r)
    db.session.commit()

    # Email recipients: dealer + moson
    moson_email = current_app.config.get("MOSON_EMAIL")
    to_list = []
    dealer_label = "메인"
    dealer_phone = "-"
    dealer_email = None
    if tenant:
        dealer_label = tenant.company_name
        dealer_phone = tenant.phone
        dealer_email = tenant.email
        to_list.append(tenant.email)
    to_list.append(moson_email)

    subject = f"[MOSON] 신규 견적/가입 신청 - {dealer_label}"
    body = "\n".join([
        "신규 견적/가입 신청이 접수되었습니다.",
        "",
        f"대리점: {dealer_label}",
        f"대리점 전화: {dealer_phone}",
        f"대리점 이메일: {dealer_email or moson_email}",
        "",
        f"고객명: {customer_name or '-'}",
        f"고객 전화: {customer_phone or '-'}",
        f"통신사 선택: {telcos_str or '-'}",
        f"상품 구성: {prods_str or '-'}",
        f"예상 월요금: {quote_month_fee or '-'}",
        f"예상 현금지원: {quote_cash or '-'}",
        "",
        f"접수 Host: {source_host}",
        f"접수 ID: {r.id}",
        f"접수 시각(UTC): {r.created_at.strftime('%Y-%m-%d %H:%M:%S')}",
    ])
    send_email(to_list=to_list, subject=subject, body=body)

    # Redirect back with toast
    return redirect(url_for("routes.landing", sent=1, dealer=(tenant.subdomain if tenant else None)))

# -----------------------
# Auth helpers
# -----------------------
def _is_main_logged_in() -> bool:
    return session.get("user_kind") == "main"

def _is_reseller_logged_in(tenant: Reseller | None) -> bool:
    return bool(tenant) and session.get("user_kind") == "reseller" and session.get("reseller_id") == tenant.id

def _require_main():
    if not _is_main_logged_in():
        return redirect(url_for("routes.admin_login"))
    return None

def _require_reseller(tenant: Reseller | None):
    if not _is_reseller_logged_in(tenant):
        return redirect(url_for("routes.admin_login"))
    return None


def _current_admin_role() -> str | None:
    if session.get("user_kind") != "main":
        return None
    return session.get("admin_role") or "master"


def _require_master():
    """마스터 권한(전체 권한)이 필요한 경우 사용."""
    if not _is_main_logged_in():
        return redirect(url_for("routes.admin_login"))
    if _current_admin_role() != "master":
        flash("마스터 권한이 필요한 기능입니다.", "error")
        return redirect(url_for("routes.admin_index"))
    return None

# -----------------------
# Admin routes (main + reseller)
# -----------------------
@bp.get("/admin")
def admin_index():
    tenant = get_tenant()
    if tenant:
        gate = _require_reseller(tenant)
        if gate:
            return gate
        consults = (
            ConsultRequest.query.filter_by(reseller_id=tenant.id)
            .order_by(ConsultRequest.id.desc())
            .limit(200)
            .all()
        )

        # 해당 대리점 기준 최근 24시간 접속 통계
        since = datetime.utcnow() - timedelta(hours=24)
        q = VisitLog.query.filter(
            VisitLog.reseller_id == tenant.id, VisitLog.created_at >= since
        )
        visits_24h = q.count()
        bots_24h = q.filter(VisitLog.is_bot.is_(True)).count()
        mobiles_24h = q.filter(VisitLog.is_mobile.is_(True)).count()
        desktops_24h = q.filter(VisitLog.is_desktop.is_(True)).count()
        recent_visits = q.order_by(VisitLog.id.desc()).limit(30).all()

        return render_template(
            "admin/reseller_dashboard.html",
            title="대리점 어드민",
            consults=consults,
            visits_24h=visits_24h,
            bots_24h=bots_24h,
            mobiles_24h=mobiles_24h,
            desktops_24h=desktops_24h,
            recent_visits=recent_visits,
        )
    else:
        gate = _require_main()
        if gate:
            return gate
        consults = (
            ConsultRequest.query.order_by(ConsultRequest.id.desc())
            .limit(300)
            .all()
        )
        resellers = Reseller.query.order_by(Reseller.id.desc()).all()

        now = datetime.utcnow()
        since_24h = now - timedelta(hours=24)
        since_7d = now - timedelta(days=7)
        since_30d = now - timedelta(days=30)

        # 전체 사이트 기준 접속 통계
        q_all = VisitLog.query
        total_visits = q_all.count()
        total_bots = q_all.filter(VisitLog.is_bot.is_(True)).count()

        q_24h = q_all.filter(VisitLog.created_at >= since_24h)
        visits_24h = q_24h.count()
        bots_24h = q_24h.filter(VisitLog.is_bot.is_(True)).count()
        mobiles_24h = q_24h.filter(VisitLog.is_mobile.is_(True)).count()
        desktops_24h = q_24h.filter(VisitLog.is_desktop.is_(True)).count()

        q_7d = q_all.filter(VisitLog.created_at >= since_7d)
        visits_7d = q_7d.count()

        q_30d = q_all.filter(VisitLog.created_at >= since_30d)
        visits_30d = q_30d.count()

        from sqlalchemy import func

        unique_ips_24h = (
            db.session.query(func.count(func.distinct(VisitLog.ip)))
            .filter(VisitLog.created_at >= since_24h)
            .scalar()
            or 0
        )

        recent_visits = q_24h.order_by(VisitLog.id.desc()).limit(40).all()

        return render_template(
            "admin/main_dashboard.html",
            title="메인 어드민",
            consults=consults,
            resellers=resellers,
            total_visits=total_visits,
            total_bots=total_bots,
            visits_24h=visits_24h,
            visits_7d=visits_7d,
            visits_30d=visits_30d,
            bots_24h=bots_24h,
            mobiles_24h=mobiles_24h,
            desktops_24h=desktops_24h,
            unique_ips_24h=unique_ips_24h,
            recent_visits=recent_visits,
        )


@bp.route("/admin/consults/<int:consult_id>/status", methods=["POST"])
def admin_update_consult_status(consult_id: int):
    """메인 어드민에서 상담 상태/메모를 수정 (대리점 어드민에도 동일하게 반영)."""
    gate = _require_main()
    if gate:
        return gate

    c = ConsultRequest.query.get_or_404(consult_id)
    status = (request.form.get("status") or "").strip()
    memo = (request.form.get("memo") or "").strip() or None
    reason = (request.form.get("reject_reason") or "").strip() or None

    allowed_status = ["", "신규", "상담중", "서류대기", "접수완료", "개통완료", "정산대기", "정산완료", "반려"]
    if status not in allowed_status:
        flash("잘못된 상태값입니다.", "error")
        return redirect(url_for("routes.admin_index"))

    if not status:
        status = "신규"

    if status != "반려":
        reason = None

    if c.status_obj is None:
        c.status_obj = ConsultStatus(status=status, memo=memo, reason=reason)
    else:
        c.status_obj.status = status
        c.status_obj.memo = memo
        c.status_obj.reason = reason

    db.session.commit()
    flash("상담 상태가 저장되었습니다.")
    return redirect(url_for("routes.admin_index") + f"#consult-{c.id}")


@bp.get("/admin/resellers")
def admin_reseller_list():
    """메인 어드민 전용 대리점 목록 페이지."""
    if get_tenant():
        return redirect(url_for("routes.admin_index"))
    gate = _require_main()
    if gate:
        return gate

    # 24시간이 지난 삭제 대기 대리점은 완전 삭제
    cutoff = datetime.utcnow() - timedelta(hours=24)
    to_purge = Reseller.query.filter(
        Reseller.is_active.is_(False),
        Reseller.deleted_at.isnot(None),
        Reseller.deleted_at < cutoff,
    ).all()
    if to_purge:
        for r in to_purge:
            db.session.delete(r)
        db.session.commit()

    resellers = Reseller.query.filter_by(is_active=True).order_by(Reseller.id.desc()).all()
    pending_deleted = (
        Reseller.query.filter(
            Reseller.is_active.is_(False),
            Reseller.deleted_at.isnot(None),
            Reseller.deleted_at >= cutoff,
        )
        .order_by(Reseller.deleted_at.desc())
        .all()
    )
    return render_template(
        "admin/reseller_list.html",
        title="대리점 관리",
        resellers=resellers,
        pending_deleted=pending_deleted,
    )


@bp.post("/admin/resellers/delete")
def admin_reseller_delete():
    """메인 어드민: 선택한 대리점을 24시간 삭제 대기 상태로 변경합니다."""
    if get_tenant():
        return redirect(url_for("routes.admin_index"))
    gate = _require_master()
    if gate:
        return gate

    ids = request.form.getlist("reseller_ids")
    if not ids:
        flash("삭제할 대리점을 선택해주세요.", "error")
        return redirect(url_for("routes.admin_reseller_list"))

    q = Reseller.query.filter(Reseller.id.in_(ids), Reseller.is_active.is_(True))
    count = 0
    now = datetime.utcnow()
    for r in q.all():
        r.is_active = False
        r.deleted_at = now
        count += 1
    if count:
        db.session.commit()
        flash(f"{count}개 대리점이 삭제 대기(24시간 후 자동 삭제) 상태로 변경되었습니다.")
    else:
        flash("삭제할 대리점을 찾지 못했습니다.", "error")

    return redirect(url_for("routes.admin_reseller_list"))


@bp.post("/admin/resellers/<int:reseller_id>/restore")
def admin_reseller_restore(reseller_id: int):
    """메인 어드민: 삭제 대기(24시간 이내) 대리점 복구."""
    if get_tenant():
        return redirect(url_for("routes.admin_index"))
    gate = _require_master()
    if gate:
        return gate

    cutoff = datetime.utcnow() - timedelta(hours=24)
    r = Reseller.query.get_or_404(reseller_id)
    if not (not r.is_active and r.deleted_at and r.deleted_at >= cutoff):
        flash("복구 가능한 대리점이 아니거나 24시간이 지났습니다.", "error")
        return redirect(url_for("routes.admin_reseller_list"))

    r.is_active = True
    r.deleted_at = None
    db.session.commit()
    flash("대리점이 복구되었습니다.")
    return redirect(url_for("routes.admin_reseller_list"))


@bp.get("/admin/profile")
def admin_reseller_profile():
    """대리점 어드민: 내 정보 / 랜딩 설정 페이지."""
    tenant = get_tenant()
    if not tenant:
        return redirect(url_for("routes.admin_index"))
    gate = _require_reseller(tenant)
    if gate:
        return gate

    return render_template(
        "admin/reseller_profile.html",
        title="내 정보 / 랜딩 설정",
        reseller=tenant,
    )


@bp.get("/admin/email-logs")
def admin_email_logs():
    """메인 어드민: 이메일 발송 로그."""
    if get_tenant():
        return redirect(url_for("routes.admin_index"))
    gate = _require_main()
    if gate:
        return gate

    logs = EmailLog.query.order_by(EmailLog.id.desc()).limit(200).all()
    return render_template(
        "admin/email_logs.html",
        title="이메일 발송 로그",
        logs=logs,
    )


@bp.get("/admin/policy")
def admin_policy():
    """통신 상품 정책표 (메인 어드민 + 대리점 어드민 열람)."""
    tenant = get_tenant()
    if tenant:
        gate = _require_reseller(tenant)
        if gate:
            return gate
    else:
        gate = _require_main()
        if gate:
            return gate

    rows = PolicyRow.query.order_by(
        PolicyRow.telco.asc().nullslast(), PolicyRow.id.asc()
    ).all()

    # 통신사 그룹별(KT 도매 / LG 도매 / SKT 도매 / SKB 도매)로 박스 분리
    groups = {
        "KT 도매": [],
        "LG 도매": [],
        "SKT 도매": [],
        "SKB 도매": [],
        "기타": [],
    }
    for r in rows:
        name = (r.telco or "").strip().upper()
        key = "기타"
        if name.startswith("KT"):
            key = "KT 도매"
        elif name.startswith("LG"):
            key = "LG 도매"
        elif "SKB" in name:
            key = "SKB 도매"
        elif "SKT" in name or name.startswith("SK "):
            key = "SKT 도매"
        groups.setdefault(key, []).append(r)

    return render_template(
        "admin/policy.html",
        title="정책표",
        groups=groups,
    )


@bp.post("/admin/policy/bulk")
def admin_policy_bulk_update():
    """정책표 전체 저장: 화면에서 수정된 모든 행을 한 번에 저장."""
    if get_tenant():
        return redirect(url_for("routes.admin_index"))
    # 정책표 수정은 마스터 어드민만 가능
    gate = _require_master()
    if gate:
        return gate

    def _parse_int(val: str):
        s = (val or "").strip()
        if not s:
            return None
        s = s.replace(",", "")
        try:
            return int(float(s))
        except Exception:
            return None

    import re

    def _max_number_in_text(text: str) -> int:
        if not text:
            return 0
        nums = re.findall(r"\d[\d,]*", str(text))
        parsed = []
        for n in nums:
            n = n.replace(",", "")
            try:
                parsed.append(int(n))
            except Exception:
                continue
        return max(parsed) if parsed else 0

    rows = PolicyRow.query.all()
    for row in rows:
        gid_key = f"gift_guide_{row.id}"
        cash_key = f"cash_vat_{row.id}"
        if gid_key not in request.form and cash_key not in request.form:
            continue

        guide_text = request.form.get(gid_key, row.gift_guide or "")
        cash_vat_raw = request.form.get(cash_key, "" if row.cash_vat is None else str(row.cash_vat))

        cash_vat_val = _parse_int(cash_vat_raw)
        final_gift = _max_number_in_text(guide_text)
        cash_val = None
        if cash_vat_val is not None:
            cash_val = cash_vat_val - (final_gift * 10000)

        row.gift_guide = guide_text
        row.cash_vat = cash_vat_val
        row.final_gift = final_gift
        row.cash = cash_val

    db.session.commit()

    return redirect(url_for("routes.admin_policy"))


@bp.post("/admin/policy/<int:row_id>")
def admin_policy_update(row_id: int):
    """정책표 개별 행 수정 (현금 VAT포함 / 경품가이드)."""
    if get_tenant():
        return redirect(url_for("routes.admin_index"))
    # 개별 수정도 마스터 어드민만 사용 (현재는 일괄 저장을 주로 사용)
    gate = _require_master()
    if gate:
        return gate

    row = PolicyRow.query.get_or_404(row_id)

    cash_vat_raw = request.form.get("cash_vat") or ""
    guide_text = request.form.get("gift_guide") or ""

    def _parse_int(val: str):
        s = (val or "").strip()
        if not s:
            return None
        s = s.replace(",", "")
        try:
            return int(float(s))
        except Exception:
            return None

    import re

    def _max_number_in_text(text: str) -> int:
        if not text:
            return 0
        nums = re.findall(r"\d[\d,]*", str(text))
        parsed = []
        for n in nums:
            n = n.replace(",", "")
            try:
                parsed.append(int(n))
            except Exception:
                continue
        return max(parsed) if parsed else 0

    cash_vat_val = _parse_int(cash_vat_raw)
    final_gift = _max_number_in_text(guide_text)
    cash_val = None
    # final_gift는 '만원' 단위, cash_vat는 '원' 단위 → 현금 = 현금VAT포함 − (최종경품만원 × 10000)
    if cash_vat_val is not None:
        cash_val = cash_vat_val - (final_gift * 10000)

    row.cash_vat = cash_vat_val
    row.gift_guide = guide_text
    row.final_gift = final_gift
    row.cash = cash_val

    db.session.commit()

    return redirect(url_for("routes.admin_policy"))


def _default_script_templates():
    return {
        "script_body": (
            "1) 인사 & 본인 소개\\n"
            "안녕하세요, 고객님. 통신 혜택 비교 플랫폼 MOSON.life 입니다.\\n"
            "남겨주신 문의 확인 차 연락드렸고요, 잠시 통화 가능하실까요?\\n\\n"
            "2) 현재 이용 현황 & 니즈 파악\\n"
            "- 현재 사용 중인 통신사 / 인터넷 속도 / TV 채널수 / 약정 남은 기간\\n"
            "- 인터넷 단독 / 인터넷+TV / 인터넷+TV+전화 중 어떤 구성을 원하시는지\\n"
            "- 가족 인원, 사용 용도(재택근무/게임/영상/아이 학습 등)를 간단히 확인합니다.\\n\\n"
            "3) 정책표 기반 조건 정리 (내부용)\\n"
            "- 상담사가 모손 정책표(정책표 메뉴)를 열어, 고객님 상황과 가장 유사한 상품을 1~2개 선택합니다.\\n"
            "- 월요금 / 최종 경품금액(현금지원) / KT 상품권 유무를 함께 확인합니다.\\n"
            "- 메인 페이지의 '내 예상 현금지원액 확인' 계산기와 동일한 기준으로 금액을 맞춥니다.\\n\\n"
            "4) 고객에게 조건 설명 (요약)\\n"
            "말씀해주신 내용 기준으로는 OO 통신사 / OO 구성 / OO 속도가 가장 유리해 보입니다.\\n"
            "모손 내부 정책표 기준으로 월 요금은 대략 OOOO원, 예상 현금지원은 최대 OOO,OOO원 수준입니다.\\n"
            "- KT의 경우에는 '현금 + 상품권' 구조임을 안내하고, 다른 통신사는 현금지원 위주임을 설명합니다.\\n"
            "- '리셀러 지원금'은 고객 현금지원과 별개의 구조이며, 고객님 혜택에는 영향이 없음을 덧붙입니다.\\n\\n"
            "5) 비교 & 선택 유도\\n"
            "동일한 조건에서 통신사별로 월 요금과 실제 받으시는 현금지원까지 같이 비교해 드릴게요.\\n"
            "설치 희망일이나 선호 통신사가 있으시면 미리 말씀해 주시면, 그쪽을 우선으로 맞춰보겠습니다.\\n\\n"
            "6) 마무리 & 다음 단계 안내\\n"
            "정리해보면, 고객님께 가장 유리한 조건은 OO 통신사 / OO 구성 / 예상 현금지원 OOO,OOO원 수준입니다.\\n"
            "원하시면 지금 바로 접수 도와드리고, 설치 가능 일자와 최종 확정금액은 문자로 다시 한 번 정리해 드리겠습니다."
        ),
        "faqs": [
            {
                "q": "Q. 현금지원은 언제 입금되나요?",
                "a": "설치 당일 오후 3시 이전 완료 시 당일, 이후 설치분은 익일 안으로 입금됩니다.\\n"
                     "입금 지연/미지급이 없도록 본사에서 직접 정산을 관리하고 있습니다.",
            },
            {
                "q": "Q. 통신사 직영보다 손해 보는 건 없나요?",
                "a": "기본 요금과 약정 조건은 직영/대리점이 거의 동일하고,\\n"
                     "저희는 통신사에서 책정한 대리점 수수료 일부를 고객 현금지원으로 돌려드리는 구조라 손해 보실 일은 없습니다.",
            },
            {
                "q": "Q. 약정 중인데 변경해도 되나요?",
                "a": "현재 약정/위약금 상황을 먼저 확인한 뒤, 손해 없이 전환 가능한지 비교해 드립니다.\\n"
                     "기존 약정 상태에 따라 권장/비권장 여부를 솔직하게 안내드립니다.",
            },
            {
                "q": "Q. 설치 품질/AS 는 믿을 수 있나요?",
                "a": "설치 및 사후 관리는 통신사 공식 기사님들이 담당하며, 본사 직영과 동일한 품질/AS 정책이 적용됩니다.",
            },
        ],
    }


def _load_script_templates():
    import os

    data_dir = os.path.join(current_app.root_path, "data")
    os.makedirs(data_dir, exist_ok=True)
    path = os.path.join(data_dir, "script_templates.json")
    if not os.path.exists(path):
        return _default_script_templates()
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
            if not isinstance(data, dict):
                return _default_script_templates()
            data.setdefault("script_body", _default_script_templates()["script_body"])
            data.setdefault("faqs", _default_script_templates()["faqs"])
            return data
    except Exception:
        return _default_script_templates()


def _save_script_templates(data: dict) -> None:
    import os

    data_dir = os.path.join(current_app.root_path, "data")
    os.makedirs(data_dir, exist_ok=True)
    path = os.path.join(data_dir, "script_templates.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


@bp.route("/admin/scripts", methods=["GET", "POST"])
def admin_script_templates():
    """상담 스크립트 / FAQ 템플릿 페이지 (본사 + 대리점 공용)."""
    tenant = get_tenant()
    if tenant:
        gate = _require_reseller(tenant)
        if gate:
            return gate
    else:
        gate = _require_main()
        if gate:
            return gate

    data = _load_script_templates()

    if request.method == "POST":
        script_body = (request.form.get("script_body") or "").strip()
        faqs = []
        idx = 0
        while True:
            q = (request.form.get(f"faq_q_{idx}") or "").strip()
            a = (request.form.get(f"faq_a_{idx}") or "").strip()
            if not q and not a:
                if idx >= len(data.get("faqs", [])):
                    break
            faqs.append({"q": q or data.get("faqs", [])[idx]["q"], "a": a or data.get("faqs", [])[idx]["a"] if idx < len(data.get("faqs", [])) else a})
            idx += 1

        if not faqs:
            faqs = data.get("faqs", [])

        new_data = {
            "script_body": script_body or data.get("script_body") or _default_script_templates()["script_body"],
            "faqs": faqs,
        }
        _save_script_templates(new_data)
        flash("상담 스크립트 / FAQ 템플릿이 저장되었습니다.")
        data = new_data

    return render_template(
        "admin/script_templates.html",
        title="상담 스크립트 / FAQ 템플릿",
        script_body=data.get("script_body", ""),
        faqs=data.get("faqs", []),
    )


@bp.get("/admin/notify")
def admin_notify_settings():
    """메인 어드민: SMS/카카오 알림톡 연동 준비 탭."""
    if get_tenant():
        return redirect(url_for("routes.admin_index"))
    gate = _require_main()
    if gate:
        return gate

    return render_template(
        "admin/notify_settings.html",
        title="SMS / 카카오 알림톡 연동 준비",
    )


@bp.route("/admin/resellers/<int:reseller_id>/password", methods=["GET", "POST"])
def admin_reseller_password(reseller_id: int):
    """메인 어드민: 특정 대리점 어드민 비밀번호 변경."""
    if get_tenant():
        return redirect(url_for("routes.admin_index"))
    gate = _require_master()
    if gate:
        return gate

    reseller = Reseller.query.get_or_404(reseller_id)

    if request.method == "POST":
        new_pw = (request.form.get("new_password") or "").strip()
        new_pw2 = (request.form.get("new_password_confirm") or "").strip()

        if not new_pw:
            flash("새 비밀번호를 입력해주세요.", "error")
            return redirect(url_for("routes.admin_reseller_password", reseller_id=reseller.id))
        if new_pw != new_pw2:
            flash("비밀번호 확인이 일치하지 않습니다.", "error")
            return redirect(url_for("routes.admin_reseller_password", reseller_id=reseller.id))

        reseller.admin_password_hash = generate_password_hash(new_pw)
        db.session.commit()
        flash("대리점 어드민 비밀번호가 변경되었습니다.")
        return redirect(url_for("routes.admin_reseller_list"))

    return render_template(
        "admin/reseller_password.html",
        title="대리점 비밀번호 변경",
        reseller=reseller,
    )


@bp.get("/admin/users")
def admin_user_list():
    """메인 어드민: 어드민 계정(마스터/상담사) 관리."""
    if get_tenant():
        return redirect(url_for("routes.admin_index"))
    gate = _require_master()
    if gate:
        return gate

    users = AdminUser.query.order_by(AdminUser.id.desc()).all()
    return render_template(
        "admin/user_list.html",
        title="회원관리",
        users=users,
    )


@bp.post("/admin/users")
def admin_user_create():
    """새 어드민 계정 생성."""
    if get_tenant():
        return redirect(url_for("routes.admin_index"))
    gate = _require_master()
    if gate:
        return gate

    username = (request.form.get("username") or "").strip()
    password = (request.form.get("password") or "").strip()
    role = (request.form.get("role") or "consultant").strip()

    if not username or not password:
        flash("아이디와 비밀번호를 입력해주세요.", "error")
        return redirect(url_for("routes.admin_user_list"))

    if AdminUser.query.filter_by(username=username).first():
        flash("이미 존재하는 아이디입니다.", "error")
        return redirect(url_for("routes.admin_user_list"))

    # admin 아이디는 항상 마스터로 고정
    if username == "admin":
        role = "master"
    elif role not in ("master", "consultant"):
        role = "consultant"

    u = AdminUser(
        username=username,
        password_hash=generate_password_hash(password),
        role=role,
    )
    db.session.add(u)
    db.session.commit()
    flash("새 어드민 계정이 생성되었습니다.")
    return redirect(url_for("routes.admin_user_list"))


@bp.post("/admin/users/<int:user_id>")
def admin_user_update(user_id: int):
    """어드민 계정 권한/비밀번호 변경."""
    if get_tenant():
        return redirect(url_for("routes.admin_index"))
    gate = _require_master()
    if gate:
        return gate

    u = AdminUser.query.get_or_404(user_id)
    role = (request.form.get("role") or u.role or "consultant").strip()
    new_pw = (request.form.get("new_password") or "").strip()

    # admin 아이디는 항상 마스터로 유지
    if u.username == "admin":
        u.role = "master"
    else:
        if role not in ("master", "consultant"):
            role = u.role or "consultant"
        u.role = role

    if new_pw:
        u.password_hash = generate_password_hash(new_pw)

    db.session.commit()
    flash("어드민 계정 정보가 저장되었습니다.")
    return redirect(url_for("routes.admin_user_list"))

@bp.route("/admin/login", methods=["GET","POST"])
def admin_login():
    tenant = get_tenant()
    is_main_admin = tenant is None

    if request.method == "POST":
        username = (request.form.get("username") or "").strip()
        password = (request.form.get("password") or "").strip()

        if is_main_admin:
            # 1) DB에 등록된 어드민 사용자 우선
            user = AdminUser.query.filter_by(username=username, is_active=True).first()
            if user and check_password_hash(user.password_hash, password):
                session.clear()
                session["user_kind"] = "main"
                session["admin_id"] = user.id
                # admin 아이디는 항상 최고 마스터 권한으로 강제
                if user.username == "admin":
                    session["admin_role"] = "master"
                else:
                    session["admin_role"] = user.role or "consultant"
                flash("메인 어드민 로그인 완료")
                return redirect(url_for("routes.admin_index"))
            # 2) 환경변수 기반 마스터 계정 (기존 방식 유지)
            if username == current_app.config.get("ADMIN_USERNAME") and password == current_app.config.get("ADMIN_PASSWORD"):
                session.clear()
                session["user_kind"] = "main"
                session["admin_role"] = "master"
                flash("메인 어드민 로그인 완료")
                return redirect(url_for("routes.admin_index"))
            flash("아이디 또는 비밀번호가 올바르지 않습니다.", "error")
            return render_template("admin/login.html", is_main_admin=True, title="메인 로그인")
        else:
            # Reseller login: username=email, password=stored
            if username.lower() != tenant.email.lower():
                flash("대리점 이메일이 올바르지 않습니다.", "error")
                return render_template("admin/login.html", is_main_admin=False, title="대리점 로그인")
            if not check_password_hash(tenant.admin_password_hash, password):
                flash("비밀번호가 올바르지 않습니다.", "error")
                return render_template("admin/login.html", is_main_admin=False, title="대리점 로그인")
            session.clear()
            session["user_kind"] = "reseller"
            session["reseller_id"] = tenant.id
            flash("대리점 어드민 로그인 완료")
            return redirect(url_for("routes.admin_index"))

    return render_template("admin/login.html", is_main_admin=is_main_admin, title=("메인 로그인" if is_main_admin else "대리점 로그인"))

@bp.get("/admin/logout")
def admin_logout():
    session.clear()
    return redirect(url_for("routes.admin_login"))

# ------------- main admin: reseller create -------------
@bp.route("/admin/resellers/new", methods=["GET","POST"])
def admin_reseller_new():
    # Main admin only (not dealer site)
    if get_tenant():
        return redirect(url_for("routes.admin_index"))
    gate = _require_main()
    if gate: return gate

    if request.method == "POST":
        subdomain = (request.form.get("subdomain") or "").strip().lower()
        company_name = (request.form.get("company_name") or "").strip()
        representative = (request.form.get("representative") or "").strip() or None
        phone = (request.form.get("phone") or "").strip()
        email = (request.form.get("email") or "").strip()
        bank_name = (request.form.get("bank_name") or "").strip() or None
        bank_account = (request.form.get("bank_account") or "").strip() or None
        initial_password = (request.form.get("initial_password") or "").strip() or None

        # Validate subdomain
        import re
        if not re.fullmatch(r"[a-z0-9-]{2,32}", subdomain or ""):
            flash("서브도메인은 영문 소문자/숫자/하이픈 2~32자만 가능합니다.", "error")
            return render_template("admin/reseller_new.html", title="대리점 생성")

        if Reseller.query.filter_by(subdomain=subdomain).first():
            flash("이미 존재하는 서브도메인입니다.", "error")
            return render_template("admin/reseller_new.html", title="대리점 생성")

        if not initial_password:
            # 요청: 초기 비밀번호를 고정값으로 설정
            initial_password = "admin1234"

        # 사이트 주소는 서브도메인 기반으로 자동 설정
        base = current_app.config.get("BASE_DOMAIN") or "moson.life"
        website_url = f"https://{subdomain}.{base}"

        r = Reseller(
            subdomain=subdomain,
            company_name=company_name,
            representative=representative,
            phone=phone,
            email=email,
            website_url=website_url,
            bank_name=bank_name,
            bank_account=bank_account,
            admin_password_hash=generate_password_hash(initial_password),
        )
        db.session.add(r)
        db.session.commit()

        # Optional: Cloudflare DNS creation (if env set)
        ok, msg = ensure_dns_record(subdomain)
        if msg:
            flash(msg)

        # 신청서에서 넘어온 경우 처리 완료 표시
        app_id = request.form.get("application_id")
        if app_id:
            app_row = ResellerApplication.query.get(app_id)
            if app_row:
                app_row.processed_at = datetime.utcnow()
                db.session.commit()

        flash(f"대리점 생성 완료! 초기 비밀번호: {initial_password}")

        return redirect(url_for("routes.admin_index"))

    # GET: 신청 대기 중인 부업 파트너 목록
    pending_apps = (
        ResellerApplication.query.filter_by(processed_at=None)
        .order_by(ResellerApplication.id.desc())
        .all()
    )

    prefill = None
    app_id = request.args.get("app_id")
    if app_id:
        prefill = ResellerApplication.query.get(app_id)

    return render_template(
        "admin/reseller_new.html",
        title="대리점 생성",
        pending_apps=pending_apps,
        prefill=prefill,
    )
