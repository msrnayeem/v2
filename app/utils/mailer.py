import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.utils import formataddr
from app.helpers.settings import get_smtp_settings
import os
from dotenv import load_dotenv

# Load environment variables from .env
load_dotenv()


def send_email(subject, recipient, body_html, body_text=None):
    smtp_settings = get_smtp_settings()
    if not smtp_settings:
        return False

    sender_email = smtp_settings.get("username")
    sender_name = smtp_settings.get("company_name")
    password = smtp_settings.get("password")
    mail_server = smtp_settings.get("host")
    mail_port = int(smtp_settings.get("port"))

    # Create the email message
    msg = MIMEMultipart("alternative")  # For HTML + plain text
    msg["From"] = formataddr((sender_name, sender_email))
    msg["To"] = recipient
    msg["Subject"] = subject

    # Optional plain text body fallback
    if body_text:
        msg.attach(MIMEText("Hi there!\nThanks for joining us at NumberSMS.", "plain"))

    # HTML body with optional unsubscribe link
    html_content = body_html
    msg.attach(MIMEText(html_content, "html"))

    try:
        print("Attempting TLS connection...")
        with smtplib.SMTP(mail_server, mail_port) as server:
            server.set_debuglevel(1)  # Enable SMTP logs for debugging
            server.starttls()
            server.login(sender_email, password)
            server.send_message(msg)
            print("Email sent successfully using TLS!")
            return True
    except smtplib.SMTPAuthenticationError:
        print("Authentication failed! Check your username and password.")
        return False
    except smtplib.SMTPException:
        print("TLS failed. Attempting SSL...")
        try:
            with smtplib.SMTP_SSL(mail_server, mail_port) as server:
                server.login(sender_email, password)
                server.send_message(msg)
                print("Email sent successfully using SSL!")
                return True
        except Exception:
            print("Failed to send email using SSL as well.")
            return False
    except Exception as e:
        print("An unexpected error occurred:", str(e))
        return False
