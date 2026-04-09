from datetime import date
from functools import wraps
import re
import secrets
from flask import Blueprint, flash, redirect, render_template, request, session, url_for

from constants import ALERT_PREFERENCE_FIELDS, DEADLINE_ALERT_OPTIONS
from models import DailyProjectReport, Notification, Project, ProjectAssignment, User, db
from notification_utils import (
    get_sendgrid_settings_display,
    save_sendgrid_settings,
    sendgrid_configured,
)
from recommendation_engine import (
    calculate_attendance_score,
    calculate_overall_employee_score,
    calculate_performance_score,
    calculate_skill_score,
)


auth_bp = Blueprint("auth", __name__)
PRIMARY_ADMIN_EMAIL = "sudhishna47@gmail.com"
SECONDARY_ADMIN_EMAIL = "sriharshini0107@gmail.com"
ADMIN_EMAILS = {
    PRIMARY_ADMIN_EMAIL,
    SECONDARY_ADMIN_EMAIL,
}
EMPLOYEE_ALLOWED_EMAILS = {
    "abdulazeez9143@gmail.com",
    "sureshsharan233@gmail.com",
}


def _build_project_deadline_report():
    today = date.today()
    report_rows = []
    alert_windows = {30, 15, 10, 5, 1}

    for project in Project.query.order_by(Project.start_date.asc()).all():
        days_to_deadline = (project.end_date - today).days
        if days_to_deadline not in alert_windows:
            continue

        if days_to_deadline == 1:
            deadline_label = "Deadline tomorrow"
        else:
            deadline_label = f"Deadline in {days_to_deadline} days"

        report_rows.append(
            {
                "project": project,
                "deadline_label": deadline_label,
                "days_to_deadline": days_to_deadline,
                "team_size": len(project.assignments),
            }
        )

    return report_rows


def _employee_pending_reports(user):
    today = date.today()
    ongoing_assignments = [
        assignment for assignment in user.assignments if assignment.project.computed_status == "Ongoing"
    ]
    submitted_project_ids = {
        row.project_id
        for row in DailyProjectReport.query.filter_by(user_id=user.id, report_date=today).all()
    }
    pending_projects = [
        assignment.project for assignment in ongoing_assignments if assignment.project_id not in submitted_project_ids
    ]
    return pending_projects


def _build_dashboard_search_items():
    search_items = []

    employees = User.query.filter(User.role != "Admin").order_by(User.name.asc()).all()
    for employee in employees:
        search_items.append(
            {
                "category": "Employees",
                "value": employee.name,
                "meta": f"ID {employee.id} | {employee.email} | {employee.position}",
                "url": url_for("employees.edit_employee", employee_id=employee.id),
            }
        )
        search_items.append(
            {
                "category": "Employees",
                "value": employee.email,
                "meta": employee.name,
                "url": url_for("employees.edit_employee", employee_id=employee.id),
            }
        )

    projects = Project.query.order_by(Project.created_at.desc()).all()
    for project in projects:
        search_items.append(
            {
                "category": "Projects",
                "value": project.name,
                "meta": f"{project.computed_status} | {project.start_date.strftime('%Y-%m-%d')}",
                "url": url_for("projects.project_detail", project_id=project.id),
            }
        )

    return search_items


def current_user():
    user_id = session.get("user_id")
    if not user_id:
        return None
    return User.query.get(user_id)


def _admin_user():
    return User.query.filter(User.role == "Admin").order_by(User.id.asc()).first()


def _admin_user_by_email(email):
    normalized_email = (email or "").strip().lower()
    if not normalized_email:
        return None
    return User.query.filter_by(role="Admin", email=normalized_email).first()


def _admin_setup_complete(email=None):
    if email:
        admin = _admin_user_by_email(email)
        return bool(admin and admin.security_code_hash)
    for admin_email in ADMIN_EMAILS:
        admin = _admin_user_by_email(admin_email)
        if not admin or not admin.security_code_hash:
            return False
    return True


def _is_security_code(code):
    return bool(re.fullmatch(r"[A-Z]{3}\d{3}[^A-Za-z0-9]", code or ""))


def login_required(view_func):
    @wraps(view_func)
    def wrapped(*args, **kwargs):
        if not current_user():
            flash("Please login first.", "warning")
            return redirect(url_for("auth.home"))
        return view_func(*args, **kwargs)

    return wrapped


def role_required(required_role):
    def decorator(view_func):
        @wraps(view_func)
        def wrapped(*args, **kwargs):
            user = current_user()
            if not user:
                flash("Please login first.", "warning")
                return redirect(url_for("auth.home"))
            if user.role != required_role:
                flash("You are not authorized for this action.", "danger")
                return redirect(url_for("auth.dashboard"))
            return view_func(*args, **kwargs)

        return wrapped

    return decorator


@auth_bp.app_context_processor
def inject_auth_context():
    user = current_user()
    unread = 0
    if user:
        unread = Notification.query.filter_by(user_id=user.id, is_read=False).count()
    return {
        "current_user": user,
        "unread_count": unread,
        "admin_recent_login": session.pop("admin_recent_login", False),
        "admin_setup_complete": _admin_setup_complete(),
    }


@auth_bp.route("/home")
def home():
    if current_user():
        return redirect(url_for("auth.dashboard"))
    return render_template("home.html")


@auth_bp.route("/login", methods=["GET", "POST"])
@auth_bp.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if request.args.get("reverify") == "1":
        session.clear()
        flash("Please login again with your admin email and security code.", "info")

    if current_user():
        return redirect(url_for("auth.dashboard"))

    selected_email = ""

    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        selected_email = email
        security_code = request.form.get("security_code", "").strip()
        admin = _admin_user_by_email(email)

        if not email or not security_code:
            flash("Email and security code are required.", "danger")
        elif email not in ADMIN_EMAILS:
            flash("Only an authorized admin email can login here.", "danger")
        elif not admin:
            flash("Admin account is unavailable.", "danger")
        elif not _admin_setup_complete(email):
            flash("Create the login code for this admin email first.", "warning")
            return redirect(url_for("auth.admin_setup", email=email))
        elif not admin.check_security_code(security_code):
            flash("Invalid security code.", "danger")
        else:
            session["user_id"] = admin.id
            session["admin_recent_login"] = True
            flash("Admin login successful.", "success")
            return redirect(url_for("auth.dashboard"))

    return render_template(
        "auth/login.html",
        admin_emails=sorted(ADMIN_EMAILS),
        selected_email=selected_email,
    )


@auth_bp.route("/admin/setup", methods=["GET", "POST"])
@auth_bp.route("/admin/register", methods=["GET", "POST"])
def admin_setup():
    if current_user():
        return redirect(url_for("auth.dashboard"))

    selected_email = (
        request.form.get("email", "").strip().lower()
        if request.method == "POST"
        else request.args.get("email", "").strip().lower()
    )
    admin = _admin_user_by_email(selected_email) if selected_email else None

    if request.method == "POST":
        security_code = request.form.get("security_code", "").strip()
        confirm_security_code = request.form.get("confirm_security_code", "").strip()

        if not selected_email:
            flash("Choose the admin email for setup.", "danger")
        elif selected_email not in ADMIN_EMAILS:
            flash("Use one of the authorized admin emails for setup.", "danger")
        elif not admin:
            flash("Admin account is unavailable for that email.", "danger")
        elif _admin_setup_complete(selected_email):
            flash("This admin email is already configured. Please login.", "info")
            return redirect(url_for("auth.admin_login"))
        elif not security_code or not confirm_security_code:
            flash("Security code and confirm security code are required.", "danger")
        elif security_code != confirm_security_code:
            flash("Security code and confirm security code do not match.", "danger")
        elif not _is_security_code(security_code):
            flash(
                "Security code must be in this exact order: 3 uppercase letters, 3 numbers, and 1 special character.",
                "danger",
            )
        else:
            admin.set_password(secrets.token_urlsafe(24))
            admin.set_security_code(security_code)
            admin.is_registered = True
            db.session.commit()
            flash("Admin credentials saved. Please login.", "success")
            return redirect(url_for("auth.admin_login"))

    return render_template(
        "auth/admin_setup.html",
        admin_emails=sorted(ADMIN_EMAILS),
        selected_email=selected_email,
    )


@auth_bp.route("/employee/login", methods=["GET", "POST"])
def employee_login():
    if current_user():
        return redirect(url_for("auth.dashboard"))

    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        security_code = request.form.get("security_code", "").strip()

        user = User.query.filter_by(email=email).first()
        if not user or user.role == "Admin":
            flash("Use the admin portal for admin logins.", "warning")
        elif email not in EMPLOYEE_ALLOWED_EMAILS:
            flash("Use the employee email assigned in the system.", "danger")
        elif not user.is_registered:
            flash("Please register first.", "warning")
            return redirect(url_for("auth.employee_register"))
        elif not security_code:
            flash("Email and security code are required.", "danger")
        elif user.check_security_code(security_code):
            session["user_id"] = user.id
            flash("Login successful.", "success")
            return redirect(url_for("auth.dashboard"))
        else:
            flash("Invalid employee security code.", "danger")

    return render_template("auth/employee_login.html")


@auth_bp.route("/employee/register", methods=["GET", "POST"])
def employee_register():
    if current_user():
        return redirect(url_for("auth.dashboard"))

    entered_email = request.form.get("email", "").strip().lower() if request.method == "POST" else ""

    if request.method == "POST":
        employee_id = request.form.get("employee_id", type=int)
        email = entered_email
        security_code = request.form.get("security_code", "").strip()
        confirm_security_code = request.form.get("confirm_security_code", "").strip()

        if not employee_id or not email or not security_code or not confirm_security_code:
            flash("Employee ID, email, security code, and confirm security code are required.", "danger")
            return render_template("auth/register.html", entered_email=entered_email)

        if security_code != confirm_security_code:
            flash("Security code and confirm security code do not match.", "danger")
            return render_template("auth/register.html", entered_email=entered_email)

        employee = User.query.filter_by(id=employee_id, email=email).first()
        if not employee or employee.role == "Admin":
            flash("Invalid employee ID or email.", "danger")
            return render_template("auth/register.html", entered_email=entered_email)

        if email not in EMPLOYEE_ALLOWED_EMAILS:
            flash("Use an employee email that is assigned in the system data.", "danger")
            return render_template("auth/register.html", entered_email=entered_email)

        if not _is_security_code(security_code):
            flash(
                "Security code must be in this exact order: 3 uppercase letters, 3 numbers, and 1 special character.",
                "danger",
            )
            return render_template("auth/register.html", entered_email=entered_email)

        if employee.is_registered and employee.security_code_hash:
            flash("This employee account is already registered. Please login.", "info")
            return redirect(url_for("auth.employee_login"))

        employee.set_password(secrets.token_urlsafe(24))
        employee.set_security_code(security_code)
        employee.is_registered = True
        db.session.commit()
        flash("Registration successful. Please login.", "success")
        return redirect(url_for("auth.employee_login"))

    return render_template("auth/register.html", entered_email=entered_email)


@auth_bp.route("/logout")
@login_required
def logout():
    session.clear()
    flash("You have been logged out.", "info")
    return redirect(url_for("auth.home"))


@auth_bp.route("/settings", methods=["GET", "POST"])
@login_required
def settings():
    user = current_user()
    selected_deadline_alert_days = [
        value for value, _label in DEADLINE_ALERT_OPTIONS
        if getattr(user, f"deadline_alert_{value}", False)
    ]
    if request.method == "POST":
        form_type = request.form.get("form_type", "").strip()
        if form_type == "alerts":
            user.project_start_alert = bool(request.form.get("project_start_alert"))

            selected_days = request.form.getlist("deadline_alert_days")
            if "all" in selected_days:
                selected_days = [value for value, _label in DEADLINE_ALERT_OPTIONS]

            for value, _label in DEADLINE_ALERT_OPTIONS:
                setattr(user, f"deadline_alert_{value}", value in selected_days)
            db.session.commit()
            flash("Alert preferences saved.", "success")
            return redirect(url_for("auth.settings"))

        if user.role != "Admin":
            flash("Only admins can update SendGrid settings.", "warning")
            return redirect(url_for("auth.settings"))

        save_sendgrid_settings(request.form)
        flash("SendGrid settings saved.", "success")
        return redirect(url_for("auth.settings"))

    return render_template(
        "settings.html",
        sendgrid_settings=get_sendgrid_settings_display(),
        sendgrid_configured=sendgrid_configured(),
        alert_preference_fields=ALERT_PREFERENCE_FIELDS,
        deadline_alert_options=DEADLINE_ALERT_OPTIONS,
        selected_deadline_alert_days=selected_deadline_alert_days,
    )


@auth_bp.route("/dashboard")
@login_required
def dashboard():
    user = current_user()

    if user.role != "Admin":
        my_assignments = (
            ProjectAssignment.query
            .filter_by(user_id=user.id)
            .order_by(ProjectAssignment.assigned_at.desc())
            .all()
        )
        my_projects = [assignment.project for assignment in my_assignments]
        alert_notifications = (
            Notification.query
            .filter(
                Notification.user_id == user.id,
                Notification.message.ilike("%alert%"),
            )
            .order_by(Notification.created_at.desc())
            .limit(5)
            .all()
        )
        return render_template(
            "employee_dashboard.html",
            my_projects=my_projects,
            pending_report_projects=_employee_pending_reports(user),
            alert_notifications=alert_notifications,
        )

    total_employees = User.query.filter(User.role != "Admin").count()
    total_projects = Project.query.count()

    employees = User.query.filter(User.role != "Admin").all()
    top_employee_rows = []
    for employee in employees:
        attendance_score = calculate_attendance_score(employee)
        performance_score = calculate_performance_score(employee)
        skill_score = calculate_skill_score(employee)
        overall_score = calculate_overall_employee_score(employee)
        top_employee_rows.append(
            {
                "employee": employee,
                "attendance_score": attendance_score,
                "performance_score": performance_score,
                "skill_score": skill_score,
                "overall_score": overall_score,
            }
        )

    top_employee_rows = sorted(
        top_employee_rows,
        key=lambda row: (row["overall_score"], row["performance_score"], row["skill_score"]),
        reverse=True,
    )[:7]

    project_deadline_rows = _build_project_deadline_report()

    return render_template(
        "dashboard.html",
        total_employees=total_employees,
        total_projects=total_projects,
        top_employee_rows=top_employee_rows,
        project_deadline_rows=project_deadline_rows,
        dashboard_search_items=_build_dashboard_search_items(),
    )
