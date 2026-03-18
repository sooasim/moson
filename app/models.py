from datetime import datetime
from .extensions import db


class Reseller(db.Model):
    __tablename__ = "resellers"
    id = db.Column(db.Integer, primary_key=True)
    subdomain = db.Column(db.String(64), unique=True, nullable=False, index=True)
    company_name = db.Column(db.String(200), nullable=False)
    representative = db.Column(db.String(100), nullable=True)
    phone = db.Column(db.String(50), nullable=False)
    email = db.Column(db.String(200), nullable=False)
    bank_name = db.Column(db.String(100), nullable=True)
    bank_account = db.Column(db.String(100), nullable=True)
    website_url = db.Column(db.String(500), nullable=True)
    admin_password_hash = db.Column(db.String(255), nullable=False)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    deleted_at = db.Column(db.DateTime, nullable=True)
    # 어느 대리점이 모집해 등록했는지 (NULL이면 본사 직접 모집/등록)
    recruited_by_reseller_id = db.Column(db.Integer, db.ForeignKey("resellers.id"), nullable=True, index=True)


class ConsultRequest(db.Model):
    __tablename__ = "consult_requests"
    id = db.Column(db.Integer, primary_key=True)

    reseller_id = db.Column(db.Integer, db.ForeignKey("resellers.id"), nullable=True, index=True)
    reseller = db.relationship("Reseller", backref=db.backref("consults", lazy=True))

    source_host = db.Column(db.String(255), nullable=True)

    customer_name = db.Column(db.String(100), nullable=True)
    customer_phone = db.Column(db.String(50), nullable=True)

    telcos = db.Column(db.String(400), nullable=True)
    products = db.Column(db.String(400), nullable=True)

    bundle = db.Column(db.String(50), nullable=True)   # internet_only / internet_tv
    speed = db.Column(db.String(50), nullable=True)    # 100 / 500 / 1000 etc

    policy_row_id = db.Column(db.Integer, db.ForeignKey("policy_rows.id"), nullable=True, index=True)
    policy_row = db.relationship("PolicyRow", backref=db.backref("consults", lazy="dynamic"))

    settlement_status = db.Column(db.String(20), nullable=False, default="미정산")  # 미정산 / 정산완료
    settled_at = db.Column(db.DateTime, nullable=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)


class ConsultStatus(db.Model):
    """상담 건의 진행 상태 및 메모를 별도 테이블로 관리 (1:1)."""

    __tablename__ = "consult_status"
    id = db.Column(db.Integer, primary_key=True)

    consult_id = db.Column(
        db.Integer,
        db.ForeignKey("consult_requests.id"),
        nullable=False,
        unique=True,
        index=True,
    )
    # 상태 값은 한국어 그대로 저장 (예: 신규/연락중/설치완료/지급완료/보류)
    status = db.Column(db.String(32), nullable=False, default="신규")
    memo = db.Column(db.Text, nullable=True)
    reason = db.Column(db.String(50), nullable=True)

    updated_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)


class EmailLog(db.Model):
    """이메일 발송 로그 (성공/실패/내용)."""

    __tablename__ = "email_logs"
    id = db.Column(db.Integer, primary_key=True)

    to = db.Column(db.String(500), nullable=False)
    subject = db.Column(db.String(500), nullable=False)
    body = db.Column(db.Text, nullable=False)

    success = db.Column(db.Boolean, default=False, nullable=False)
    is_dryrun = db.Column(db.Boolean, default=False, nullable=False)
    error_message = db.Column(db.Text, nullable=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)


class AdminUser(db.Model):
    """메인 어드민 로그인 계정(여러 명) 및 권한."""

    __tablename__ = "admin_users"
    id = db.Column(db.Integer, primary_key=True)

    username = db.Column(db.String(64), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)

    # role: 'master' (전체 권한) / 'consultant' (열람 중심)
    role = db.Column(db.String(20), nullable=False, default="consultant")
    is_active = db.Column(db.Boolean, default=True, nullable=False)

    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)


class PolicyRow(db.Model):
    """통신사별 정책표(엑셀 기반)."""

    __tablename__ = "policy_rows"
    id = db.Column(db.Integer, primary_key=True)

    # 공통 식별 컬럼
    telco = db.Column(db.String(50), nullable=True)          # 통신사 (KT / LG / SKB / SKT 등)

    # 우측 블록 기준 공통 컬럼 (KT/LG/SKB/SKT 공용)
    kind = db.Column(db.String(100), nullable=True)          # 종류 (예: 인터넷 단독)
    category = db.Column(db.String(100), nullable=True)      # 구분/상품군 (예: 일반/결합 등)
    product_name = db.Column(db.String(200), nullable=True)  # 상품/속도 (예: 100M, 1G 등)
    month_fee = db.Column(db.Integer, nullable=True)         # 월요금

    promo1 = db.Column(db.String(100), nullable=True)        # 프로모션1 (KT: 정액결합 37K↑, etc.)
    promo2 = db.Column(db.String(100), nullable=True)        # 프로모션2
    promo3 = db.Column(db.String(100), nullable=True)        # 프로모션3
    promo4 = db.Column(db.String(100), nullable=True)        # 프로모션4

    gift_guide = db.Column(db.String(400), nullable=True)    # '경품가이드' 원문
    voucher = db.Column(db.Integer, nullable=True)           # 상품권 / 상품권 별도
    cash_vat = db.Column(db.Integer, nullable=True)          # '현금 (VAT 포함/별도)'
    total_fee = db.Column(db.Integer, nullable=True)         # 상품권+현금 합산 (최종 수수료)

    # 파생 컬럼
    final_gift = db.Column(db.Integer, nullable=True)        # 최종 경품금액 (경품가이드 내 최대값)
    cash = db.Column(db.Integer, nullable=True)              # 현금 = cash_vat - final_gift

    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)


ConsultRequest.status_obj = db.relationship(
    "ConsultStatus",
    backref="consult",
    uselist=False,
    cascade="all, delete-orphan",
)


class VisitLog(db.Model):
    __tablename__ = "visit_logs"
    id = db.Column(db.Integer, primary_key=True)

    # 어느 테넌트(대리점)에서 발생한 접속인지 (None이면 메인 사이트)
    reseller_id = db.Column(db.Integer, db.ForeignKey("resellers.id"), nullable=True, index=True)
    reseller = db.relationship("Reseller", backref=db.backref("visits", lazy=True))

    path = db.Column(db.String(255), nullable=False)
    method = db.Column(db.String(10), nullable=False, default="GET")
    ip = db.Column(db.String(64), nullable=True, index=True)
    user_agent = db.Column(db.String(400), nullable=True)
    referrer = db.Column(db.String(400), nullable=True)

    is_bot = db.Column(db.Boolean, default=False, nullable=False)
    is_mobile = db.Column(db.Boolean, default=False, nullable=False)
    is_desktop = db.Column(db.Boolean, default=False, nullable=False)
    is_admin = db.Column(db.Boolean, default=False, nullable=False)

    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)


class ResellerApplication(db.Model):
    """부업 파트너(대리점) 신청서."""

    __tablename__ = "reseller_applications"
    id = db.Column(db.Integer, primary_key=True)

    subdomain = db.Column(db.String(64), nullable=False, index=True)
    company_name = db.Column(db.String(200), nullable=False)
    representative = db.Column(db.String(100), nullable=True)
    phone = db.Column(db.String(50), nullable=False)
    email = db.Column(db.String(200), nullable=False)
    bank_name = db.Column(db.String(100), nullable=True)
    bank_account = db.Column(db.String(100), nullable=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    processed_at = db.Column(db.DateTime, nullable=True)
    # 서브사이트에서 접수 시 모집 대리점 (NULL이면 본사 moson.life 접수)
    recruiting_reseller_id = db.Column(db.Integer, db.ForeignKey("resellers.id"), nullable=True, index=True)
    dealer_approved_at = db.Column(db.DateTime, nullable=True)
    dealer_dismissed_at = db.Column(db.DateTime, nullable=True)
