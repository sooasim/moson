from app import create_app
from app.extensions import db
from app.models import Reseller, ConsultRequest, VisitLog


def run():
    app = create_app()
    results = {}

    with app.app_context():
        # 기존 데이터 정리
        Reseller.query.delete()
        ConsultRequest.query.delete()
        VisitLog.query.delete()
        db.session.commit()

        client = app.test_client()

        # 1) 메인 어드민 로그인
        resp = client.post(
            "/admin/login",
            data={
                "username": app.config["ADMIN_USERNAME"],
                "password": app.config["ADMIN_PASSWORD"],
            },
            follow_redirects=False,
        )
        results["admin_login_status"] = resp.status_code

        # 2) 대리점 생성
        resp = client.post(
            "/admin/resellers/new",
            data={
                "subdomain": "testdealer",
                "company_name": "테스트 대리점",
                "phone": "010-0000-0000",
                "email": "dealer@example.com",
                "website_url": "https://dealer.example.com",
                "initial_password": "testpass123",
            },
            follow_redirects=False,
        )
        results["reseller_create_status"] = resp.status_code

        created_reseller = Reseller.query.filter_by(subdomain="testdealer").first()
        results["reseller_created"] = bool(created_reseller)

        # 3) 대리점 사이트에서 상담 신청 (/consult?dealer=testdealer)
        resp = client.post(
            "/consult?dealer=testdealer",
            data={
                "telco": ["SK", "LG"],
                "prod": ["INT", "TV"],
                "customer_name": "홍길동",
                "customer_phone": "010-1234-5678",
            },
            follow_redirects=False,
        )
        results["consult_dealer_status"] = resp.status_code

        dealer_consult = (
            ConsultRequest.query.order_by(ConsultRequest.id.desc()).first()
        )
        results["dealer_consult_exists"] = bool(dealer_consult)
        results["dealer_consult_reseller_match"] = bool(
            dealer_consult and dealer_consult.reseller_id == created_reseller.id
        )

        # 4) 메인 사이트에서 상담 신청 (/consult)
        resp = client.post(
            "/consult",
            data={
                "telco": ["KT"],
                "prod": ["TV"],
                "customer_name": "김메인",
                "customer_phone": "010-9999-0000",
            },
            follow_redirects=False,
        )
        results["consult_main_status"] = resp.status_code

        main_consult = (
            ConsultRequest.query.order_by(ConsultRequest.id.desc()).first()
        )
        results["main_consult_exists"] = bool(main_consult)
        results["main_consult_reseller_none"] = bool(
            main_consult and main_consult.reseller_id is None
        )

        # 5) VisitLog 기록 확인
        visit_count = VisitLog.query.count()
        bot_count = VisitLog.query.filter_by(is_bot=True).count()
        mobile_count = VisitLog.query.filter_by(is_mobile=True).count()

        results["visit_logs_total"] = visit_count
        results["visit_logs_bots"] = bot_count
        results["visit_logs_mobile"] = mobile_count

    print(results)


if __name__ == "__main__":
    run()

