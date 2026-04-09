from datetime import date, datetime, timedelta

from flask import Blueprint, flash, redirect, render_template, request, url_for
from sqlalchemy import or_

from constants import DESIGNATED_POSITIONS
from models import (
    AttendanceRecord,
    DailyProjectReport,
    LeaveRequest,
    Project,
    ProjectAssignment,
    Skill,
    User,
    db,
    employee_skills,
    resume_skills,
)
from notification_utils import create_notification_with_target
from recommendation_engine import (
    calculate_attendance_metrics,
    calculate_attendance_score,
    calculate_overall_employee_score,
    calculate_performance_metrics,
    calculate_performance_score,
    calculate_skill_score,
    recommend_courses_for_employee,
)
from routes.auth_routes import current_user, login_required, role_required


employee_bp = Blueprint("employees", __name__)

BREAK_MINUTES = {
    "coffee": 15,
    "food": 45,
    "meeting": 30,
}

BREAK_LABELS = {
    "coffee": "Refreshment Break",
    "food": "Meal Break",
    "meeting": "Meeting Break",
}

LEAVE_TYPES = [
    "Planned Leave",
    "Sick Leave",
    "Personal Leave",
    "Vacation",
    "Emergency Leave",
]

ANNUAL_LEAVE_DAYS = 24
COURSE_PLATFORMS = [
    "Coursera",
    "Udemy",
    "edX",
    "Great Learning",
    "Scaler",
    "GeeksforGeeks",
    "NPTEL",
    "LinkedIn Learning",
    "Udacity",
]


@employee_bp.route("/")
@login_required
@role_required("Admin")
def list_employees():
    query = request.args.get("q", "").strip()
    base_employees = User.query.filter(User.role != "Admin").order_by(User.name.asc()).all()
    employees_query = User.query.filter(User.role != "Admin")
    if query:
        employees_query = employees_query.filter(
            or_(
                User.name.ilike(f"%{query}%"),
                User.email.ilike(f"%{query}%"),
                User.position.ilike(f"%{query}%"),
                User.department.ilike(f"%{query}%"),
                db.cast(User.id, db.String).ilike(f"%{query}%"),
            )
        )
    employees = employees_query.order_by(User.name.asc()).all()
    project_id = request.args.get("project_id", type=int)
    selected_project = Project.query.get(project_id) if project_id else None
    overall_scores = {employee.id: calculate_overall_employee_score(employee) for employee in employees}
    search_items = []
    for employee in base_employees:
        search_items.extend(
            [
                {
                    "category": "Employee ID",
                    "value": str(employee.id),
                    "meta": f"{employee.name} | {employee.email}",
                    "url": url_for("employees.edit_employee", employee_id=employee.id),
                },
                {
                    "category": "Name",
                    "value": employee.name,
                    "meta": f"ID {employee.id} | {employee.position}",
                    "url": url_for("employees.edit_employee", employee_id=employee.id),
                },
                {
                    "category": "Email",
                    "value": employee.email,
                    "meta": employee.name,
                    "url": url_for("employees.edit_employee", employee_id=employee.id),
                },
            ]
        )
        if employee.department:
            search_items.append(
                {
                    "category": "Department",
                    "value": employee.department,
                    "meta": employee.name,
                    "url": url_for("employees.edit_employee", employee_id=employee.id),
                }
            )
    return render_template(
        "employees/list.html",
        employees=employees,
        selected_project=selected_project,
        overall_scores=overall_scores,
        query=query,
        search_items=search_items,
    )


@employee_bp.route("/search")
@login_required
@role_required("Admin")
def admin_search():
    flash("Search is available directly from the dashboard now.", "info")
    return redirect(url_for("auth.dashboard"))


@employee_bp.route("/live-attendance")
@login_required
@role_required("Admin")
def live_attendance():
    employees = User.query.filter(User.role != "Admin").order_by(User.name.asc()).all()
    today = date.today()
    attendance_map = {
        row.user_id: row
        for row in AttendanceRecord.query.filter_by(record_date=today).all()
    }
    valid_report_user_ids = {
        report.user_id
        for report in DailyProjectReport.query.filter_by(report_date=today).all()
        if attendance_map.get(report.user_id) and attendance_map[report.user_id].login_time
    }
    live_attendance_rows = []
    for employee in employees:
        attendance_row = attendance_map.get(employee.id)
        if any(
            leave_request.status == "Approved"
            and leave_request.start_date <= today <= leave_request.end_date
            for leave_request in employee.leave_requests
        ):
            attendance_status = "On Approved Leave"
        elif attendance_row and attendance_row.logout_time:
            attendance_status = "Clocked Out"
        elif attendance_row and attendance_row.login_time:
            attendance_status = "Clocked In"
        else:
            attendance_status = "Not Logged In"

        live_attendance_rows.append(
            {
                "employee": employee,
                "attendance_status": attendance_status,
                "login_time": (
                    attendance_row.login_time.strftime("%I:%M %p")
                    if attendance_row and attendance_row.login_time
                    else "-"
                ),
                "logout_time": (
                    attendance_row.logout_time.strftime("%I:%M %p")
                    if attendance_row and attendance_row.logout_time
                    else "-"
                ),
                "reported_projects": 1 if employee.id in valid_report_user_ids else 0,
            }
        )
    return render_template(
        "employees/live_attendance.html",
        logged_rows=[row for row in live_attendance_rows if row["attendance_status"] in {"Clocked In", "Clocked Out"}],
        not_logged_rows=[row for row in live_attendance_rows if row["attendance_status"] not in {"Clocked In", "Clocked Out"}],
        today=today,
    )


@employee_bp.route("/live-attendance/<int:employee_id>")
@login_required
@role_required("Admin")
def live_attendance_detail(employee_id):
    employee = User.query.get_or_404(employee_id)
    today = date.today()
    attendance_row = AttendanceRecord.query.filter_by(user_id=employee.id, record_date=today).first()
    today_reports = (
        DailyProjectReport.query
        .filter_by(user_id=employee.id, report_date=today)
        .order_by(DailyProjectReport.submitted_at.desc())
        .all()
    )
    if not attendance_row or not attendance_row.login_time:
        today_reports = []

    if any(
        leave_request.status == "Approved"
        and leave_request.start_date <= today <= leave_request.end_date
        for leave_request in employee.leave_requests
    ):
        attendance_status = "On Approved Leave"
    elif attendance_row and attendance_row.logout_time:
        attendance_status = "Clocked Out"
    elif attendance_row and attendance_row.login_time:
        attendance_status = "Clocked In"
    else:
        attendance_status = "Not Logged In"

    return render_template(
        "employees/live_attendance_detail.html",
        employee=employee,
        today=today,
        attendance_row=attendance_row,
        attendance_status=attendance_status,
        today_reports=today_reports,
    )


def _authorize_employee_detail_view(employee_id):
    user = current_user()
    if user.role == "Admin":
        return None
    if user.id != employee_id:
        flash("You can only view your own score details.", "warning")
        return redirect(url_for("auth.dashboard"))
    return None


def get_today_attendance(employee_id):
    return AttendanceRecord.query.filter_by(user_id=employee_id, record_date=date.today()).first()


def calculate_net_duration_hours(record, logout_time):
    if not record.login_time or not logout_time:
        return None
    gross_hours = (logout_time - record.login_time).total_seconds() / 3600
    break_hours = record.total_break_minutes / 60
    return round(max(0.0, gross_hours - break_hours), 2)


def _find_overlapping_leave(employee_id, start_date_value, end_date_value):
    return (
        LeaveRequest.query
        .filter(
            LeaveRequest.user_id == employee_id,
            LeaveRequest.status.in_(["Pending", "Approved"]),
            LeaveRequest.start_date <= end_date_value,
            LeaveRequest.end_date >= start_date_value,
        )
        .first()
    )


def _count_leave_days(start_date_value, end_date_value):
    leave_days = 0
    current_day = start_date_value
    while current_day <= end_date_value:
        if current_day.weekday() < 5:
            leave_days += 1
        current_day += timedelta(days=1)
    return leave_days


def calculate_leave_balance(employee, balance_year=None):
    balance_year = balance_year or date.today().year
    available_days = ANNUAL_LEAVE_DAYS
    approved_requests = [
        request
        for request in employee.leave_requests
        if request.status == "Approved" and request.start_date.year == balance_year
    ]
    pending_requests = [
        request
        for request in employee.leave_requests
        if request.status == "Pending" and request.start_date.year == balance_year
    ]

    used_days = sum(request.total_days for request in approved_requests)
    pending_days = sum(request.total_days for request in pending_requests)

    return {
        "year": balance_year,
        "available_days": available_days,
        "used_days": used_days,
        "pending_days": pending_days,
        "remaining_days": max(0, available_days - used_days),
        "requestable_days": max(0, available_days - used_days - pending_days),
    }


def _employee_pending_project_reports(employee):
    today = date.today()
    ongoing_assignments = [
        assignment for assignment in employee.assignments if assignment.project.computed_status == "Ongoing"
    ]
    reports_by_project = {
        report.project_id: report
        for report in DailyProjectReport.query.filter_by(user_id=employee.id, report_date=today).all()
    }

    pending_projects = []
    submitted_reports = []
    for assignment in ongoing_assignments:
        report = reports_by_project.get(assignment.project_id)
        if report:
            submitted_reports.append(report)
        else:
            pending_projects.append(assignment.project)

    return pending_projects, submitted_reports


@employee_bp.route("/add", methods=["GET", "POST"])
@login_required
@role_required("Admin")
def add_employee():
    skills = Skill.query.order_by(Skill.name.asc()).all()
    project_id = request.args.get("project_id", type=int)
    selected_project = Project.query.get(project_id) if project_id else None

    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "").strip()
        role = request.form.get("role", "Employee").strip()
        position = request.form.get("position", "Web Developer").strip()
        department = request.form.get("department", "").strip()

        if not name or not email or not password:
            flash("Name, email, and password are required.", "danger")
            return render_template(
                "employees/form.html",
                skills=skills,
                employee=None,
                designated_positions=DESIGNATED_POSITIONS,
                selected_project=selected_project,
            )

        if User.query.filter_by(email=email).first():
            flash("Email already exists.", "danger")
            return render_template(
                "employees/form.html",
                skills=skills,
                employee=None,
                designated_positions=DESIGNATED_POSITIONS,
                selected_project=selected_project,
            )

        if position not in DESIGNATED_POSITIONS:
            position = "Web Developer"

        employee = User(
            name=name,
            email=email,
            role=role,
            position=position,
            department=department,
            is_registered=True,
        )
        employee.set_password(password)

        selected_skill_ids = request.form.getlist("skill_ids")
        if selected_skill_ids:
            selected_skills = Skill.query.filter(Skill.id.in_(selected_skill_ids)).all()
            employee.skills = selected_skills
            employee.resume_skills = selected_skills

        db.session.add(employee)
        db.session.commit()

        if selected_project:
            has_leader = ProjectAssignment.query.filter_by(
                project_id=selected_project.id,
                is_team_leader=True,
            ).first()
            assignment = ProjectAssignment(
                project_id=selected_project.id,
                user_id=employee.id,
                is_team_leader=(has_leader is None),
            )
            db.session.add(assignment)
            create_notification_with_target(
                employee.id,
                f"You have been assigned to project: {selected_project.name}",
                subject="STAFFLY Project Assignment",
                target_url=url_for("projects.project_detail", project_id=selected_project.id),
            )
            db.session.commit()
            flash("New employee added and allocated to the selected project.", "success")
            return redirect(url_for("employees.list_employees", project_id=selected_project.id))

        flash("Employee added successfully.", "success")
        return redirect(url_for("employees.list_employees"))

    return render_template(
        "employees/form.html",
        skills=skills,
        employee=None,
        designated_positions=DESIGNATED_POSITIONS,
        selected_project=selected_project,
    )


@employee_bp.route("/<int:employee_id>/edit", methods=["GET", "POST"])
@login_required
@role_required("Admin")
def edit_employee(employee_id):
    employee = User.query.get_or_404(employee_id)
    skills = Skill.query.order_by(Skill.name.asc()).all()

    if request.method == "POST":
        employee.name = request.form.get("name", "").strip()
        employee.email = request.form.get("email", "").strip().lower()
        employee.role = request.form.get("role", "Employee").strip()

        chosen_position = request.form.get("position", "Web Developer").strip()
        employee.position = chosen_position if chosen_position in DESIGNATED_POSITIONS else "Web Developer"

        employee.department = request.form.get("department", "").strip()

        new_password = request.form.get("password", "").strip()
        if new_password:
            employee.set_password(new_password)

        selected_skill_ids = request.form.getlist("skill_ids")
        employee.skills = Skill.query.filter(Skill.id.in_(selected_skill_ids)).all() if selected_skill_ids else []

        db.session.commit()
        flash("Employee updated successfully.", "success")
        return redirect(url_for("employees.list_employees"))

    return render_template(
        "employees/form.html",
        skills=skills,
        employee=employee,
        designated_positions=DESIGNATED_POSITIONS,
        selected_project=None,
    )


@employee_bp.route("/<int:employee_id>/delete", methods=["POST"])
@login_required
@role_required("Admin")
def delete_employee(employee_id):
    employee = User.query.get_or_404(employee_id)

    if employee.role == "Admin":
        flash("Admin user cannot be deleted here.", "warning")
        return redirect(url_for("employees.list_employees"))

    db.session.delete(employee)
    db.session.commit()
    flash("Employee deleted.", "info")
    return redirect(url_for("employees.list_employees"))


@employee_bp.route("/skills", methods=["GET", "POST"])
@login_required
@role_required("Admin")
def skills():
    flash("Skills are now managed automatically from project required skills.", "info")
    return redirect(url_for("projects.create_project"))


@employee_bp.route("/attendance/check-in", methods=["POST"])
@login_required
def attendance_check_in():
    user = current_user()
    if user.role == "Admin":
        flash("Attendance actions are available only for employees.", "warning")
        return redirect(url_for("auth.dashboard"))

    record = get_today_attendance(user.id)
    if record and record.login_time:
        flash("You have already logged in for today.", "info")
        return redirect(url_for("auth.dashboard"))

    if not record:
        record = AttendanceRecord(user_id=user.id, record_date=date.today())
        db.session.add(record)

    record.login_time = datetime.now()
    record.logout_time = None
    record.duration_hours = None
    db.session.commit()
    flash("Clock in recorded.", "success")
    return redirect(url_for("auth.dashboard"))


@employee_bp.route("/attendance/check-out", methods=["POST"])
@login_required
def attendance_check_out():
    user = current_user()
    if user.role == "Admin":
        flash("Attendance actions are available only for employees.", "warning")
        return redirect(url_for("auth.dashboard"))

    record = get_today_attendance(user.id)
    if not record or not record.login_time:
        flash("Please log in first.", "warning")
        return redirect(url_for("auth.dashboard"))
    if record.logout_time:
        flash("You have already logged out for today.", "info")
        return redirect(url_for("auth.dashboard"))

    record.logout_time = datetime.now()
    record.duration_hours = calculate_net_duration_hours(record, record.logout_time)
    db.session.commit()
    flash("Clock out recorded.", "success")
    return redirect(url_for("auth.dashboard"))


@employee_bp.route("/attendance/add-break", methods=["POST"])
@login_required
def attendance_add_break():
    user = current_user()
    if user.role == "Admin":
        flash("Break tracking is available only for employees.", "warning")
        return redirect(url_for("auth.dashboard"))

    break_type = request.form.get("break_type", "").strip().lower()
    if break_type not in BREAK_MINUTES:
        flash("Invalid break type selected.", "danger")
        return redirect(url_for("auth.dashboard"))

    record = get_today_attendance(user.id)
    if not record or not record.login_time:
        flash("Please log in before adding breaks.", "warning")
        return redirect(url_for("auth.dashboard"))
    if record.logout_time:
        flash("You cannot add breaks after logging out.", "warning")
        return redirect(url_for("auth.dashboard"))

    if break_type == "coffee":
        record.coffee_break_minutes = int(record.coffee_break_minutes or 0) + BREAK_MINUTES[break_type]
    elif break_type == "food":
        record.food_break_minutes = int(record.food_break_minutes or 0) + BREAK_MINUTES[break_type]
    else:
        record.meeting_break_minutes = int(record.meeting_break_minutes or 0) + BREAK_MINUTES[break_type]

    db.session.commit()
    flash(f"{BREAK_LABELS[break_type]} recorded.", "success")
    return redirect(url_for("auth.dashboard"))


@employee_bp.route("/<int:employee_id>/attendance")
@login_required
def attendance_detail(employee_id):
    unauthorized_redirect = _authorize_employee_detail_view(employee_id)
    if unauthorized_redirect:
        return unauthorized_redirect
    employee = User.query.get_or_404(employee_id)
    records = sorted(employee.attendance_records, key=lambda row: row.record_date, reverse=True)
    metrics = calculate_attendance_metrics(employee)
    score = metrics["attendance_score"]
    return render_template(
        "employees/attendance.html",
        employee=employee,
        records=records,
        attendance_score=score,
        attendance_metrics=metrics,
    )


@employee_bp.route("/leave", methods=["GET", "POST"])
@login_required
def leave_requests():
    user = current_user()
    if user.role == "Admin":
        flash("Use the admin leave review page to manage employee leave requests.", "info")
        return redirect(url_for("employees.admin_leave_requests"))

    if request.method == "POST":
        leave_type = request.form.get("leave_type", "Planned Leave").strip()
        reason = request.form.get("reason", "").strip()
        start_date_raw = request.form.get("start_date", "").strip()
        end_date_raw = request.form.get("end_date", "").strip()

        if leave_type not in LEAVE_TYPES:
            leave_type = "Planned Leave"

        if not reason or not start_date_raw or not end_date_raw:
            flash("Leave type, start date, end date, and reason are required.", "danger")
        else:
            try:
                start_date_value = datetime.strptime(start_date_raw, "%Y-%m-%d").date()
                end_date_value = datetime.strptime(end_date_raw, "%Y-%m-%d").date()
            except ValueError:
                flash("Please enter valid leave dates.", "danger")
            else:
                today = date.today()
                leave_days = _count_leave_days(start_date_value, end_date_value)
                leave_balance = calculate_leave_balance(user)
                if start_date_value <= today:
                    flash("Leave must be applied in advance. Choose a future start date.", "warning")
                elif end_date_value < start_date_value:
                    flash("End date cannot be earlier than start date.", "warning")
                elif leave_days <= 0:
                    flash("Leave request must include at least one working day.", "warning")
                elif _find_overlapping_leave(user.id, start_date_value, end_date_value):
                    flash("You already have a pending or approved leave request for those dates.", "warning")
                elif leave_days > leave_balance["requestable_days"]:
                    flash(
                        f"Requested leave exceeds your available balance. "
                        f"You can currently request up to {leave_balance['requestable_days']} working day(s).",
                        "warning",
                    )
                else:
                    leave_request = LeaveRequest(
                        user_id=user.id,
                        leave_type=leave_type,
                        start_date=start_date_value,
                        end_date=end_date_value,
                        reason=reason,
                    )
                    db.session.add(leave_request)

                    admin_users = User.query.filter_by(role="Admin").all()
                    for admin_user in admin_users:
                        create_notification_with_target(
                            admin_user.id,
                            (
                                f"New leave request from {user.name}: "
                                f"{start_date_value.strftime('%Y-%m-%d')} to {end_date_value.strftime('%Y-%m-%d')}"
                            ),
                            subject="STAFFLY Leave Request",
                            target_url=url_for("employees.admin_leave_requests"),
                        )

                    db.session.commit()
                    flash("Leave request submitted successfully.", "success")
                    return redirect(url_for("employees.leave_requests"))

    my_leave_requests = (
        LeaveRequest.query
        .filter_by(user_id=user.id)
        .order_by(LeaveRequest.applied_at.desc(), LeaveRequest.start_date.desc())
        .all()
    )
    return render_template(
        "employees/leave_apply.html",
        leave_types=LEAVE_TYPES,
        my_leave_requests=my_leave_requests,
        leave_balance=calculate_leave_balance(user),
    )


@employee_bp.route("/leave/admin")
@login_required
@role_required("Admin")
def admin_leave_requests():
    status_filter = request.args.get("status", "").strip().title()
    if status_filter not in {"Pending", "Approved", "Rejected"}:
        status_filter = ""

    pending_requests = (
        LeaveRequest.query
        .filter_by(status="Pending")
        .order_by(LeaveRequest.start_date.asc(), LeaveRequest.applied_at.asc())
        .all()
    )

    all_requests_query = LeaveRequest.query.order_by(LeaveRequest.applied_at.desc(), LeaveRequest.start_date.desc())
    if status_filter:
        all_requests_query = all_requests_query.filter_by(status=status_filter)

    status_counts = {
        "Pending": LeaveRequest.query.filter_by(status="Pending").count(),
        "Approved": LeaveRequest.query.filter_by(status="Approved").count(),
        "Rejected": LeaveRequest.query.filter_by(status="Rejected").count(),
    }

    return render_template(
        "employees/leave_admin.html",
        pending_requests=pending_requests,
        leave_requests=all_requests_query.all(),
        status_counts=status_counts,
        selected_status=status_filter,
        annual_leave_days=ANNUAL_LEAVE_DAYS,
    )


@employee_bp.route("/leave/<int:leave_request_id>/review", methods=["POST"])
@login_required
@role_required("Admin")
def review_leave_request(leave_request_id):
    leave_request = LeaveRequest.query.get_or_404(leave_request_id)
    decision = request.form.get("decision", "").strip().title()
    admin_note = request.form.get("admin_note", "").strip()

    if decision not in {"Approved", "Rejected"}:
        flash("Invalid leave request decision.", "danger")
        return redirect(url_for("employees.admin_leave_requests"))

    if leave_request.status != "Pending":
        flash("This leave request has already been reviewed.", "info")
        return redirect(url_for("employees.admin_leave_requests"))

    if decision == "Approved":
        leave_balance = calculate_leave_balance(leave_request.employee, leave_request.start_date.year)
        if leave_request.total_days > leave_balance["remaining_days"]:
            flash(
                f"Cannot approve this leave request. {leave_request.employee.name} has only "
                f"{leave_balance['remaining_days']} day(s) remaining.",
                "warning",
            )
            return redirect(url_for("employees.admin_leave_requests"))

    leave_request.status = decision
    leave_request.admin_note = admin_note or None
    leave_request.reviewed_at = datetime.utcnow()

    create_notification_with_target(
        leave_request.user_id,
        (
            f"Your leave request for {leave_request.start_date.strftime('%Y-%m-%d')} to "
            f"{leave_request.end_date.strftime('%Y-%m-%d')} was {decision.lower()}."
        ),
        subject="STAFFLY Leave Update",
        target_url=url_for("employees.leave_requests"),
    )
    db.session.commit()
    flash(f"Leave request {decision.lower()} successfully.", "success")
    return redirect(url_for("employees.admin_leave_requests"))


@employee_bp.route("/<int:employee_id>/skill-score")
@login_required
def skill_score_detail(employee_id):
    unauthorized_redirect = _authorize_employee_detail_view(employee_id)
    if unauthorized_redirect:
        return unauthorized_redirect
    employee = User.query.get_or_404(employee_id)

    updated_rows = db.session.execute(
        db.select(Skill.name, employee_skills.c.proficiency)
        .join(employee_skills, Skill.id == employee_skills.c.skill_id)
        .where(employee_skills.c.user_id == employee.id)
        .order_by(Skill.name.asc())
    ).all()

    resume_rows = db.session.execute(
        db.select(Skill.name, resume_skills.c.proficiency)
        .join(resume_skills, Skill.id == resume_skills.c.skill_id)
        .where(resume_skills.c.user_id == employee.id)
        .order_by(Skill.name.asc())
    ).all()

    proficiency_labels = {
        1: "Beginner",
        2: "Intermediate",
        3: "Advanced",
        4: "Expert",
    }

    updated_skills = [
        {"name": skill_name, "proficiency": int(level), "label": proficiency_labels.get(int(level), str(level))}
        for skill_name, level in updated_rows
    ]
    resume_skills_data = [
        {"name": skill_name, "proficiency": int(level), "label": proficiency_labels.get(int(level), str(level))}
        for skill_name, level in resume_rows
    ]

    return render_template(
        "employees/skill_score.html",
        employee=employee,
        skill_score=calculate_skill_score(employee),
        updated_skills=updated_skills,
        resume_skills_data=resume_skills_data,
    )


@employee_bp.route("/<int:employee_id>/performance")
@login_required
def performance_detail(employee_id):
    unauthorized_redirect = _authorize_employee_detail_view(employee_id)
    if unauthorized_redirect:
        return unauthorized_redirect
    employee = User.query.get_or_404(employee_id)
    metrics = calculate_performance_metrics(employee)

    project_rows = sorted(
        employee.past_performance_records,
        key=lambda row: row.completed_on,
        reverse=True,
    )
    feedback_rows = sorted(
        employee.feedback_records,
        key=lambda row: row.created_at,
        reverse=True,
    )

    return render_template(
        "employees/performance.html",
        employee=employee,
        performance_metrics=metrics,
        project_rows=project_rows,
        feedback_rows=feedback_rows,
    )


@employee_bp.route("/<int:employee_id>/overall-scores")
@login_required
def overall_scores_detail(employee_id):
    unauthorized_redirect = _authorize_employee_detail_view(employee_id)
    if unauthorized_redirect:
        return unauthorized_redirect
    employee = User.query.get_or_404(employee_id)
    attendance_score = calculate_attendance_score(employee)
    performance_score = calculate_performance_score(employee)
    skill_score = calculate_skill_score(employee)
    overall_score = calculate_overall_employee_score(employee)

    return render_template(
        "employees/overall_scores.html",
        employee=employee,
        attendance_score=attendance_score,
        performance_score=performance_score,
        skill_score=skill_score,
        overall_score=overall_score,
    )


@employee_bp.route("/project-reports")
@login_required
def my_project_reports():
    user = current_user()
    if user.role == "Admin":
        flash("Project reports are submitted by employees from their assigned projects.", "info")
        return redirect(url_for("projects.list_projects"))

    today = date.today()
    pending_projects, submitted_reports = _employee_pending_project_reports(user)
    all_reports = (
        DailyProjectReport.query
        .filter_by(user_id=user.id)
        .order_by(DailyProjectReport.report_date.desc(), DailyProjectReport.submitted_at.desc())
        .all()
    )
    return render_template(
        "employees/project_reports.html",
        today=today,
        pending_projects=pending_projects,
        submitted_reports=submitted_reports,
        all_reports=all_reports,
    )


@employee_bp.route("/learning-recommendations")
@login_required
def learning_recommendations():
    user = current_user()
    if user.role == "Admin":
        flash("AI learning recommendations are available in the employee portal.", "info")
        return redirect(url_for("auth.dashboard"))

    selected_skill_names = [item.strip() for item in request.args.getlist("selected_skills") if item.strip()]
    skill_scope = request.args.get("skill_scope", "").strip().lower()
    filters = {
        "selected_skill_names": selected_skill_names,
        "skill_scope": skill_scope if skill_scope in {"required", "all"} else "",
        "platform": request.args.get("platform", "").strip(),
        "price_type": request.args.get("price_type", "").strip(),
        "delivery_mode": request.args.get("delivery_mode", "").strip(),
        "level": request.args.get("level", "").strip(),
        "duration_category": request.args.get("duration_category", "").strip(),
    }
    filters = {
        key: value
        for key, value in filters.items()
        if value or (key == "selected_skill_names" and selected_skill_names)
    }
    recommendations = recommend_courses_for_employee(user, filters)

    return render_template(
        "employees/learning_recommendations.html",
        recommendations=recommendations,
        selected_filters=filters,
        selected_skill_names=recommendations.get("selected_skill_names", []),
        selected_skill_scope=filters.get("skill_scope") or ("required" if recommendations.get("required_skill_names") else "all"),
        platforms=COURSE_PLATFORMS,
        price_types=["Free", "Paid"],
        delivery_modes=["Recorded", "Live"],
        levels=["Beginner", "Intermediate", "Advanced"],
        durations=["Short", "Long"],
    )
