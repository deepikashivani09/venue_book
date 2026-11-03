"""Email notifications. Every email is stored in the `emails` table.
If SMTP_HOST is set the email is really sent; otherwise it is only logged (handy for demos)."""
import os
import smtplib
from email.message import EmailMessage


def send_email(conn, to_addr, subject, body):
    status = "logged"
    host = os.environ.get("SMTP_HOST")
    if host:
        try:
            msg = EmailMessage()
            msg["From"] = os.environ.get("MAIL_FROM", "VenueBook <no-reply@venuebook.local>")
            msg["To"] = to_addr
            msg["Subject"] = subject
            msg.set_content(body)
            with smtplib.SMTP(host, int(os.environ.get("SMTP_PORT", 587)), timeout=10) as smtp:
                smtp.starttls()
                if os.environ.get("SMTP_USER"):
                    smtp.login(os.environ["SMTP_USER"], os.environ.get("SMTP_PASSWORD", ""))
                smtp.send_message(msg)
            status = "sent"
        except Exception as exc:  # never let an email problem break a booking decision
            status = f"failed: {exc}"[:200]
    else:
        print(f"\n--- EMAIL (not sent, SMTP not configured) ---\nTo: {to_addr}\nSubject: {subject}\n\n{body}\n---------------------------------------------")
    conn.execute("INSERT INTO emails (to_addr, subject, body, status) VALUES (?, ?, ?, ?)", (to_addr, subject, body, status))
    return status
