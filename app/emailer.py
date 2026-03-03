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
        # SMTP 미설정: 콘솔 출력 + 로그에 DRYRUN(실제 발송 안 됨) 으로 저장
        print("\n[EMAIL:DRYRUN] To:", to_list)
        print("[EMAIL:DRYRUN] Subject:", subject)
        print("[EMAIL:DRYRUN] Body:\n", body)

        missing = []
        if not host:
            missing.append("SMTP_HOST")
        if not user:
            missing.append("SMTP_USER")
        if not pw:
            missing.append("SMTP_PASS")
        cfg_summary = f"SMTP_HOST={host or '-'}, SMTP_USER={user or '-'}, SMTP_PORT={port}, TLS={use_tls}"
        err = "SMTP 설정이 완전하지 않아 실제 이메일을 보내지 않았습니다. 누락된 항목: " + (", ".join(missing) or "없음") + f" / 설정 요약: {cfg_summary}"

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

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = from_addr
    msg["To"] = ", ".join(to_list)
    msg.set_content(body)

    success = False
    error_message = None
    steps = []
    try:
        steps.append(f"CONNECT smtp://{host}:{port}")
        with smtplib.SMTP(host, port, timeout=15) as smtp:
            if use_tls:
                steps.append("STARTTLS")
                smtp.starttls()
            steps.append(f"LOGIN as {user}")
            smtp.login(user, pw)
            steps.append("SEND_MESSAGE")
            smtp.send_message(msg)
        success = True
        steps.append("DONE")
    except Exception as e:
        # 예외 발생 시: 지금까지 진행된 단계 + ERROR 메시지를 한 줄씩 기록
        steps.append(f"ERROR: {e}")
        error_message = "\n".join(steps)
        print("\n[EMAIL:ERROR]\n" + error_message)

    # 성공한 경우에도 어떤 단계를 거쳤는지 모두 기록
    if success and not error_message:
        error_message = "\n".join(steps) if steps else None

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
