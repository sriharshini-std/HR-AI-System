import json
import os
from pathlib import Path
from urllib import error, request

from models import Notification, User, db


EMAIL_ENABLED_RECIPIENTS = {
    "sudhishna47@gmail.com",
    "sriharshini0107@gmail.com",
    "abdulazeez9143@gmail.com",
    "sureshsharan233@gmail.com",
}
SENDGRID_SETTINGS_PATH = Path(__file__).resolve().parent / "instance" / "staffly_sendgrid_settings.json"
SENDGRID_API_URL = "https://api.sendgrid.com/v3/mail/send"


def _load_file_settings():
    if not SENDGRID_SETTINGS_PATH.exists():
        return {}
    try:
        return json.loads(SENDGRID_SETTINGS_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def get_sendgrid_settings():
    file_settings = _load_file_settings()
    return {
        "api_key": os.environ.get("STAFFLY_SENDGRID_API_KEY", os.environ.get("SENDGRID_API_KEY", file_settings.get("api_key", ""))).strip(),
        "from_email": os.environ.get("STAFFLY_SENDGRID_FROM_EMAIL", file_settings.get("from_email", "")).strip(),
        "from_name": os.environ.get("STAFFLY_SENDGRID_FROM_NAME", file_settings.get("from_name", "STAFFLY")).strip() or "STAFFLY",
    }


def get_sendgrid_settings_display():
    settings = get_sendgrid_settings()
    return {
        "from_email": settings["from_email"],
        "from_name": settings["from_name"],
        "api_key_set": bool(settings["api_key"]),
    }


def sendgrid_configured():
    settings = get_sendgrid_settings()
    return bool(settings["api_key"] and settings["from_email"])


def save_sendgrid_settings(form_data):
    existing = _load_file_settings()
    SENDGRID_SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)

    api_key_value = form_data.get("api_key", "").strip()
    settings = {
        "api_key": api_key_value if api_key_value else existing.get("api_key", ""),
        "from_email": form_data.get("from_email", "").strip(),
        "from_name": form_data.get("from_name", "").strip() or "STAFFLY",
    }
    SENDGRID_SETTINGS_PATH.write_text(json.dumps(settings, indent=2), encoding="utf-8")


def send_email_notification(recipient_email, subject, message):
    settings = get_sendgrid_settings()
    if not recipient_email or recipient_email not in EMAIL_ENABLED_RECIPIENTS:
        return False

    if not settings["api_key"] or not settings["from_email"]:
        return False

    payload = {
        "personalizations": [
            {
                "to": [{"email": recipient_email}],
                "subject": subject,
            }
        ],
        "from": {
            "email": settings["from_email"],
            "name": settings["from_name"],
        },
        "content": [
            {
                "type": "text/plain",
                "value": f"STAFFLY Notification\n\n{message}\n\nThis message was sent from STAFFLY.",
            }
        ],
    }

    request_body = json.dumps(payload).encode("utf-8")
    sendgrid_request = request.Request(
        SENDGRID_API_URL,
        data=request_body,
        method="POST",
        headers={
            "Authorization": f"Bearer {settings['api_key']}",
            "Content-Type": "application/json",
        },
    )

    try:
        with request.urlopen(sendgrid_request, timeout=15) as response:
            return response.status == 202
    except (error.HTTPError, error.URLError, TimeoutError, ValueError):
        return False


def create_notification(user_id, message, subject="STAFFLY Notification"):
    return create_notification_with_target(user_id, message, subject=subject, target_url=None)


def create_notification_with_target(user_id, message, subject="STAFFLY Notification", target_url=None):
    notification = Notification(user_id=user_id, message=message, target_url=target_url)
    db.session.add(notification)

    user = User.query.get(user_id)
    if user and user.email in EMAIL_ENABLED_RECIPIENTS:
        send_email_notification(user.email, subject, message)

    return notification


def create_notifications_for_users(user_ids, message, subject="STAFFLY Notification"):
    notifications = []
    for user_id in user_ids:
        notifications.append(create_notification(user_id, message, subject=subject))
    return notifications
