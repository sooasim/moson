import smtplib
from email.message import EmailMessage
from flask import current_app

from .extensions import db
from .models import EmailLog

def send_email(to_list: list[str], subject: str, body: str) -> None:
    """Send email via SMTP if configured, otherwise print to console."""
    to_list = [t for t in (to_list or []) if t]
    if not to_list:
        return

    host = current_app.config.get("SMTP_HOST")
    user = current_app.config.get("SMTP_USER")
    pw = current_app.config.get("SMTP_PASS")
    port = int(current_app.config.get("SMTP_PORT", 587))
    use_tls = bool(current_app.config.get("SMTP_TLS", True))
    from_addr = current_app.config.get("SMTP_FROM") or current_app.config.get("MOSON_EMAIL")

    if not host or not user or not pw:
        # SMTP 미설정: 콘솔 출력 + 로그에 DRYRUN 으로 저장
        print("\n[EMAIL:DRYRUN] To:", to_list)
        print("[EMAIL:DRYRUN] Subject:", subject)
        print("[EMAIL:DRYRUN] Body:\n", body)
        log = EmailLog(
            to=", ".join(to_list),
            subject=subject,
            body=body,
            success=True,
            is_dryrun=True,
            error_message=None,
        )
        try:
            db.session.add(log)
            db.session.commit()
        except Exception:
            db.session.rollback()
        return

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = from_addr
    msg["To"] = ", ".join(to_list)
    msg.set_content(body)

    success = False
    error_message = None
    try:
        with smtplib.SMTP(host, port) as smtp:
            if use_tls:
                smtp.starttls()
            smtp.login(user, pw)
            smtp.send_message(msg)
        success = True
    except Exception as e:
        error_message = str(e)
        print("\n[EMAIL:ERROR]", e)

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
