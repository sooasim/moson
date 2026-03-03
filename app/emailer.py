import smtplib
from email.message import EmailMessage
from flask import current_app
import requests

from .extensions import db
from .models import EmailLog

def send_email(to_list: list[str], subject: str, body: str) -> None:
    """이메일 발송: Resend API 우선 사용, 없으면 SMTP, 둘 다 없으면 DRYRUN."""
    to_list = [t for t in (to_list or []) if t]
    if not to_list:
        return

    # 1) Resend API 설정
    resend_api_key = current_app.config.get("RESEND_API_KEY")
    resend_from = current_app.config.get("RESEND_FROM") or current_app.config.get("SMTP_FROM") or current_app.config.get("MOSON_EMAIL")

    # 2) 기존 SMTP 설정 (로컬/테스트용 백업)
    host = current_app.config.get("SMTP_HOST")
    user = current_app.config.get("SMTP_USER")
    pw = current_app.config.get("SMTP_PASS")
    port = int(current_app.config.get("SMTP_PORT", 587))
    use_tls = bool(current_app.config.get("SMTP_TLS", True))
    from_addr = resend_from  # 발신 주소는 공통으로 사용

    # Resend와 SMTP 둘 다 설정이 없으면 DRYRUN
    if not resend_api_key and (not host or not user or not pw):
        # 발송 백엔드 미설정: 콘솔 출력 + 로그에 DRYRUN(실제 발송 안 됨) 으로 저장
        print("\n[EMAIL:DRYRUN] To:", to_list)
        print("[EMAIL:DRYRUN] Subject:", subject)
        print("[EMAIL:DRYRUN] Body:\n", body)

        err_parts = []
        if not resend_api_key:
            err_parts.append("RESEND_API_KEY 미설정")
        if not host or not user or not pw:
            missing = []
            if not host:
                missing.append("SMTP_HOST")
            if not user:
                missing.append("SMTP_USER")
            if not pw:
                missing.append("SMTP_PASS")
            cfg_summary = f"SMTP_HOST={host or '-'}, SMTP_USER={user or '-'}, SMTP_PORT={port}, TLS={use_tls}"
            err_parts.append("SMTP 누락 항목: " + (", ".join(missing) or "없음") + f" / 설정 요약: {cfg_summary}")
        err = "이메일 발송 백엔드가 설정되지 않아 실제 이메일을 보내지 않았습니다. " + " | ".join(err_parts)

        log = EmailLog(
            to=", ".join(to_list),
            subject=subject,
            body=body,
            success=False,      # 실제 발송 안 됨
            is_dryrun=True,     # DRYRUN 모드
            error_message=err,
        )
        try:
            db.session.add(log)
            db.session.commit()
        except Exception:
            db.session.rollback()
        return

    success = False
    error_message = None

    # 3) Resend API 우선 사용 (Railway 등에서 SMTP 포트 차단 문제 회피)
    if resend_api_key and resend_from:
        steps = []
        try:
            steps.append("RESEND:PREPARE_PAYLOAD")
            url = "https://api.resend.com/emails"
            headers = {
                "Authorization": f"Bearer {resend_api_key}",
                "Content-Type": "application/json",
            }
            payload = {
                "from": resend_from,
                "to": to_list,
                "subject": subject,
                "text": body,
            }
            steps.append("RESEND:REQUEST")
            resp = requests.post(url, json=payload, headers=headers, timeout=15)
            steps.append(f"RESEND:STATUS {resp.status_code}")
            if 200 <= resp.status_code < 300:
                success = True
                steps.append("RESEND:DONE")
            else:
                steps.append(f"RESEND:ERROR_BODY {resp.text[:500]}")
                raise RuntimeError(f"Resend API 응답 코드 {resp.status_code}")
        except Exception as e:
            steps.append(f"RESEND:EXCEPTION {e}")
            error_message = "\n".join(steps)
            print("\n[EMAIL:RESEND_ERROR]\n" + error_message)
        else:
            # 성공/실패 모두 단계 로그를 남김
            if not error_message:
                error_message = "\n".join(steps)

    # 4) Resend 실패 또는 미설정 시, 로컬 테스트용으로만 SMTP 시도
    if not success and host and user and pw:
        msg = EmailMessage()
        msg["Subject"] = subject
        msg["From"] = from_addr
        msg["To"] = ", ".join(to_list)
        msg.set_content(body)

        steps = []
        try:
            steps.append(f"SMTP:CONNECT smtp://{host}:{port}")
            with smtplib.SMTP(host, port, timeout=15) as smtp:
                if use_tls:
                    steps.append("SMTP:STARTTLS")
                    smtp.starttls()
                steps.append(f"SMTP:LOGIN as {user}")
                smtp.login(user, pw)
                steps.append("SMTP:SEND_MESSAGE")
                smtp.send_message(msg)
            success = True
            steps.append("SMTP:DONE")
        except Exception as e:
            steps.append(f"SMTP:ERROR {e}")
            error_message = "\n".join(steps)
            print("\n[EMAIL:SMTP_ERROR]\n" + error_message)
        else:
            if not error_message:
                error_message = "\n".join(steps)

    log = EmailLog(
        to=", ".join(to_list),
        subject=subject,
        body=body,
        success=success,
        is_dryrun=False,
        error_message=error_message,
    )
    try:
        db.session.add(log)
        db.session.commit()
    except Exception:
        db.session.rollback()
