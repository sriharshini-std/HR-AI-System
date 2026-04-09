from models import Notification, db


def create_notification(user_id, message, subject="STAFFLY Notification"):
    return create_notification_with_target(user_id, message, subject=subject, target_url=None)


def create_notification_with_target(user_id, message, subject="STAFFLY Notification", target_url=None):
    notification = Notification(user_id=user_id, message=message, target_url=target_url)
    db.session.add(notification)

    return notification


def create_notifications_for_users(user_ids, message, subject="STAFFLY Notification"):
    notifications = []
    for user_id in user_ids:
        notifications.append(create_notification(user_id, message, subject=subject))
    return notifications
