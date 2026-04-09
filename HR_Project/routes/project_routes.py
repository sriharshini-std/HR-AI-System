from datetime import date, datetime

from flask import Blueprint, jsonify, flash, redirect, render_template, request, url_for
from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError

from models import AttendanceRecord, Course, DailyProjectReport, Notification, Project, ProjectAssignment, Skill, User, db
from notification_utils import create_notification_with_target
from recommendation_engine import (
    calculate_attendance_score,
    calculate_performance_score,
    calculate_skill_score,
    rank_employees_for_project,
    suggest_teams_for_project,
)
from routes.auth_routes import current_user, login_required, role_required


project_bp = Blueprint("projects", __name__)

COURSE_PLATFORM_URLS = {
    "Coursera": "https://www.coursera.org/browse",
    "Udemy": "https://www.udemy.com/courses/search/?q={query}",
    "edX": "https://www.edx.org/learn",
    "Great Learning": "https://www.mygreatlearning.com/academy/learn-for-free",
    "Scaler": "https://www.scaler.com/topics/",
    "GeeksforGeeks": "https://www.geeksforgeeks.org/courses/search?query={query}",
    "NPTEL": "https://onlinecourses.nptel.ac.in/",
    "LinkedIn Learning": "https://www.linkedin.com/learning/",
    "Udacity": "https://www.udacity.com/courses/all",
}


def _post_allocation_redirect(default_project_id):
    next_url = request.form.get("next_url", "").strip()
    if next_url.startswith("/employees"):
        return redirect(next_url)
    return redirect(url_for("projects.project_detail", project_id=default_project_id))


def _today_attendance_map():
    today = date.today()
    return {
        record.user_id: record
        for record in AttendanceRecord.query.filter_by(record_date=today).all()
    }


def _course_url_for_platform(platform_name, skill_name):
    query_value = (skill_name or "").replace(" ", "+")
    template = COURSE_PLATFORM_URLS.get(platform_name, "https://www.google.com/search?q={query}+course")
    return template.format(query=query_value)


def _normalize_skill_names(raw_value):
    if not raw_value:
        return []
    cleaned = []
    seen = set()
    for item in raw_value.split(","):
        skill_name = item.strip()
        if not skill_name:
            continue
        normalized = skill_name.lower()
        if normalized in seen:
            continue
        seen.add(normalized)
        cleaned.append(skill_name)
    return cleaned


def _resolve_project_skills(selected_skill_ids, new_skill_names):
    selected_skills = Skill.query.filter(Skill.id.in_(selected_skill_ids)).all() if selected_skill_ids else []
    skill_map = {skill.name.lower(): skill for skill in Skill.query.all()}
    created_skills = []

    for skill_name in new_skill_names:
        existing_skill = skill_map.get(skill_name.lower())
        if existing_skill:
            selected_skills.append(existing_skill)
            continue

        created_skill = Skill(name=skill_name)
        db.session.add(created_skill)
        db.session.flush()
        skill_map[created_skill.name.lower()] = created_skill
        selected_skills.append(created_skill)
        created_skills.append(created_skill)

    deduped_skills = list({skill.id: skill for skill in selected_skills}.values())
    return deduped_skills, created_skills


def _notify_employees_about_new_skills(created_skills):
    if not created_skills:
        return
    skill_names = ", ".join(skill.name for skill in created_skills)
    employees = User.query.filter(User.role != "Admin").all()
    for employee in employees:
        create_notification_with_target(
            employee.id,
            f"New project skill(s) added to the system: {skill_names}.",
            subject="STAFFLY Skills Update",
            target_url=url_for("employees.learning_recommendations"),
        )


def _create_course_catalog_for_skills(created_skills):
    if not created_skills:
        return

    platforms = list(COURSE_PLATFORM_URLS.items())
    price_types = ["Free", "Paid"]
    delivery_modes = ["Recorded", "Live"]
    levels = ["Beginner", "Intermediate", "Advanced"]
    duration_options = {
        "Short": ["2 weeks", "4 weeks", "10 hours", "18 hours"],
        "Long": ["8 weeks", "12 weeks", "4 months", "6 months"],
    }

    existing_titles = {course.title for course in Course.query.all()}
    for skill in created_skills:
        for index, (platform_name, _url_template) in enumerate(platforms):
            title = f"{skill.name} {['Essentials', 'Bootcamp', 'Mastery'][index % 3]} - {platform_name}"
            if title in existing_titles:
                continue

            duration_category = "Short" if index % 2 == 0 else "Long"
            course = Course(
                title=title,
                platform=platform_name,
                provider=platform_name,
                url=_course_url_for_platform(platform_name, skill.name),
                price_type=price_types[index % len(price_types)],
                delivery_mode=delivery_modes[(index + 1) % len(delivery_modes)],
                level=levels[index % len(levels)],
                duration_category=duration_category,
                duration_text=duration_options[duration_category][index % len(duration_options[duration_category])],
                description=f"Structured {skill.name} learning track on {platform_name}.",
            )
            course.skills.append(skill)
            db.session.add(course)
            existing_titles.add(title)


@project_bp.route("/")
@login_required
def list_projects():
    user = current_user()
    query = request.args.get("q", "").strip()
    selected_status = request.args.get("status", "").strip().title()
    if selected_status not in {"Upcoming", "Ongoing", "Completed"}:
        selected_status = ""

    if user.role == "Admin":
        projects = Project.query.order_by(Project.created_at.desc()).all()
    else:
        assigned_project_ids = [
            row.project_id
            for row in ProjectAssignment.query.with_entities(ProjectAssignment.project_id).filter_by(user_id=user.id).all()
        ]
        projects = (
            Project.query
            .filter(Project.id.in_(assigned_project_ids))
            .order_by(Project.created_at.desc())
            .all()
            if assigned_project_ids
            else []
        )
    visible_projects = list(projects)

    changed = False
    for project in projects:
        computed = project.computed_status
        if project.status != computed:
            project.status = computed
            changed = True
    if changed:
        db.session.commit()

    if selected_status:
        projects = [project for project in projects if project.computed_status == selected_status]

    if query:
        lowered = query.lower()
        projects = [
            project for project in projects
            if (
                lowered in project.name.lower()
            )
        ]
    search_items = []
    for project in visible_projects:
        search_items.append(
            {
                "category": "Project",
                "value": project.name,
                "meta": f"{project.computed_status} | {project.start_date.strftime('%Y-%m-%d')}",
                "url": url_for("projects.project_detail", project_id=project.id),
            }
        )

    if user.role == "Admin":
        status_counts = {
            "Completed": Project.query.filter_by(status="Completed").count(),
            "Ongoing": Project.query.filter_by(status="Ongoing").count(),
            "Upcoming": Project.query.filter_by(status="Upcoming").count(),
        }
    else:
        status_counts = {
            "Completed": sum(1 for p in projects if p.computed_status == "Completed"),
            "Ongoing": sum(1 for p in projects if p.computed_status == "Ongoing"),
            "Upcoming": sum(1 for p in projects if p.computed_status == "Upcoming"),
        }

    today = date.today()
    report_counts = {
        row[0]: row[1]
        for row in (
            db.session.query(DailyProjectReport.project_id, db.func.count(DailyProjectReport.id))
            .filter(DailyProjectReport.report_date == today)
            .group_by(DailyProjectReport.project_id)
            .all()
        )
    }
    attendance_map = _today_attendance_map()
    live_project_rows = []
    for project in projects:
        if project.computed_status != "Ongoing":
            continue

        team_members = [assignment.employee for assignment in project.assignments]
        clocked_in_count = sum(
            1
            for member in team_members
            if attendance_map.get(member.id) and attendance_map[member.id].login_time
        )
        reported_count = report_counts.get(project.id, 0)
        live_project_rows.append(
            {
                "project": project,
                "team_size": len(team_members),
                "clocked_in_count": clocked_in_count,
                "reported_count": reported_count,
                "reporting_gap": max(0, len(team_members) - reported_count),
            }
        )

    return render_template(
        "projects/list.html",
        projects=projects,
        status_counts=status_counts,
        selected_status=selected_status,
        live_project_rows=live_project_rows,
        query=query,
        search_items=search_items,
    )


@project_bp.route("/create", methods=["GET", "POST"])
@login_required
@role_required("Admin")
def create_project():
    skills = Skill.query.order_by(Skill.name.asc()).all()

    if request.method == "POST":
        name = request.form.get("name", "").strip()
        description = request.form.get("description", "").strip()
        start_date_raw = request.form.get("start_date", "").strip()
        duration_days = request.form.get("duration_days", type=int)
        skill_ids = request.form.getlist("skill_ids")
        new_skill_names = _normalize_skill_names(request.form.get("new_skills", ""))

        if not name:
            flash("Project name is required.", "danger")
            return render_template("projects/create.html", skills=skills)

        if not start_date_raw:
            flash("Project start date is required.", "danger")
            return render_template("projects/create.html", skills=skills)

        if not duration_days or duration_days <= 0:
            flash("Project duration must be a positive number of days.", "danger")
            return render_template("projects/create.html", skills=skills)

        try:
            start_date = datetime.strptime(start_date_raw, "%Y-%m-%d").date()
        except ValueError:
            flash("Invalid start date format.", "danger")
            return render_template("projects/create.html", skills=skills)

        project = Project(
            name=name,
            description=description,
            start_date=start_date,
            duration_days=duration_days,
        )
        project.status = project.computed_status

        resolved_skills, created_skills = _resolve_project_skills(skill_ids, new_skill_names)
        if resolved_skills:
            project.required_skills = resolved_skills

        db.session.add(project)
        _create_course_catalog_for_skills(created_skills)
        _notify_employees_about_new_skills(created_skills)
        db.session.commit()
        flash("Project created successfully.", "success")
        return redirect(url_for("projects.project_detail", project_id=project.id))

    return render_template("projects/create.html", skills=skills)


@project_bp.route("/<int:project_id>")
@login_required
def project_detail(project_id):
    user = current_user()
    project = Project.query.get_or_404(project_id)
    if user.role != "Admin":
        assigned = ProjectAssignment.query.filter_by(project_id=project.id, user_id=user.id).first()
        if not assigned:
            flash("You are not assigned to this project.", "warning")
            return redirect(url_for("projects.list_projects"))
    if project.status != project.computed_status:
        project.status = project.computed_status
        db.session.commit()

    employees = User.query.filter(User.role != "Admin").order_by(User.name.asc()).all()
    ranked_matches = rank_employees_for_project(project, employees)

    assigned_user_ids = {assignment.user_id for assignment in project.assignments}
    has_allocations = len(assigned_user_ids) > 0
    ordered_assignments = sorted(
        project.assignments,
        key=lambda assignment: (0 if assignment.is_team_leader else 1, assignment.assigned_at),
    )

    team_suggestions = []
    if project.computed_status == "Upcoming":
        team_suggestions = suggest_teams_for_project(project, employees, team_size=None, num_teams=6)

    elapsed_days = (date.today() - project.start_date).days + 1
    elapsed_days = max(0, min(elapsed_days, project.duration_days))
    project_progress_percentage = round((elapsed_days / max(1, project.duration_days)) * 100, 2)
    today = date.today()
    today_reports = (
        DailyProjectReport.query
        .filter_by(project_id=project.id, report_date=today)
        .order_by(DailyProjectReport.submitted_at.desc())
        .all()
    )
    attendance_map = _today_attendance_map()
    valid_today_reports = [
        report
        for report in today_reports
        if attendance_map.get(report.user_id) and attendance_map[report.user_id].login_time
    ]
    reports_by_user = {report.user_id: report for report in valid_today_reports}
    my_today_report = reports_by_user.get(user.id) if user.role != "Admin" else None
    reported_progress_percentage = (
        round(sum(report.progress_percent for report in valid_today_reports) / len(valid_today_reports), 2)
        if valid_today_reports
        else project_progress_percentage
    )
    completed_work_percentage = min(100.0, max(project_progress_percentage, reported_progress_percentage))
    remaining_work_percentage = round(max(0.0, 100.0 - completed_work_percentage), 2)

    allocated_team_rows = []
    for assignment in ordered_assignments:
        emp = assignment.employee
        attendance_score = calculate_attendance_score(emp)
        performance_score = calculate_performance_score(emp)
        skill_score = calculate_skill_score(emp)
        attendance_record = attendance_map.get(emp.id)
        today_report = reports_by_user.get(emp.id)
        employee_progress = round(
            (project_progress_percentage * 0.40)
            + (attendance_score * 0.20)
            + (performance_score * 0.20)
            + (skill_score * 0.20),
            2,
        )
        allocated_team_rows.append(
            {
                "assignment": assignment,
                "skills_text": ", ".join(sorted([skill.name for skill in emp.skills])) if emp.skills else "-",
                "attendance_score": attendance_score,
                "performance_score": performance_score,
                "skill_score": skill_score,
                "employee_progress": employee_progress,
                "today_login": (
                    attendance_record.login_time.strftime("%I:%M %p")
                    if attendance_record and attendance_record.login_time
                    else "Not logged in"
                ),
                "today_report": today_report,
                "report_status": "Reported" if today_report else "Pending Report",
            }
        )

    return render_template(
        "projects/detail.html",
        project=project,
        ranked_matches=ranked_matches,
        team_suggestions=team_suggestions,
        assigned_user_ids=assigned_user_ids,
        has_allocations=has_allocations,
        ordered_assignments=ordered_assignments,
        project_progress_percentage=project_progress_percentage,
        elapsed_days=elapsed_days,
        allocated_team_rows=allocated_team_rows,
        today_reports=valid_today_reports,
        today_report_count=len(valid_today_reports),
        team_size=len(ordered_assignments),
        my_today_report=my_today_report,
        today_date=today,
        completed_work_percentage=round(completed_work_percentage, 2),
        remaining_work_percentage=remaining_work_percentage,
        reported_progress_percentage=reported_progress_percentage,
    )


@project_bp.route("/<int:project_id>/report", methods=["POST"])
@login_required
def submit_project_report(project_id):
    user = current_user()
    if user.role == "Admin":
        flash("Project reports are submitted by employees.", "warning")
        return redirect(url_for("projects.project_detail", project_id=project_id))

    project = Project.query.get_or_404(project_id)
    assignment = ProjectAssignment.query.filter_by(project_id=project.id, user_id=user.id).first()
    if not assignment:
        flash("You are not assigned to this project.", "warning")
        return redirect(url_for("projects.list_projects"))
    if project.computed_status != "Ongoing":
        flash("Daily reports are available only for ongoing projects.", "warning")
        return redirect(url_for("projects.project_detail", project_id=project.id))

    today = date.today()
    today_attendance = AttendanceRecord.query.filter_by(user_id=user.id, record_date=today).first()
    if not today_attendance or not today_attendance.login_time:
        flash("Clock in first. Daily project reports can only be submitted after login.", "warning")
        return redirect(url_for("projects.project_detail", project_id=project.id))

    work_summary = request.form.get("work_summary", "").strip()
    blockers = request.form.get("blockers", "").strip()
    progress_percent = request.form.get("progress_percent", type=int)

    if not work_summary:
        flash("Please describe what you worked on today.", "danger")
        return redirect(url_for("projects.project_detail", project_id=project.id))
    if progress_percent is None or progress_percent < 0 or progress_percent > 100:
        flash("Progress percentage must be between 0 and 100.", "danger")
        return redirect(url_for("projects.project_detail", project_id=project.id))

    existing_report = DailyProjectReport.query.filter_by(
        user_id=user.id,
        project_id=project.id,
        report_date=today,
    ).first()

    if existing_report:
        existing_report.work_summary = work_summary
        existing_report.blockers = blockers or None
        existing_report.progress_percent = progress_percent
        existing_report.submitted_at = datetime.utcnow()
        flash("Today's project report updated.", "success")
    else:
        db.session.add(
            DailyProjectReport(
                user_id=user.id,
                project_id=project.id,
                report_date=today,
                work_summary=work_summary,
                blockers=blockers or None,
                progress_percent=progress_percent,
            )
        )
        flash("Today's project report submitted.", "success")

    db.session.commit()
    return redirect(url_for("projects.project_detail", project_id=project.id))


@project_bp.route("/<int:project_id>/assign", methods=["POST"])
@login_required
@role_required("Admin")
def assign_employee(project_id):
    project = Project.query.get_or_404(project_id)
    user_id = request.form.get("user_id", type=int)

    if not user_id:
        flash("Select a valid employee.", "danger")
        return redirect(url_for("projects.project_detail", project_id=project.id))

    assignment = ProjectAssignment(project_id=project.id, user_id=user_id)
    has_leader = ProjectAssignment.query.filter_by(project_id=project.id, is_team_leader=True).first()
    assignment.is_team_leader = has_leader is None
    db.session.add(assignment)

    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        flash("Employee is already assigned to this project.", "warning")
        return redirect(url_for("projects.project_detail", project_id=project.id))

    create_notification_with_target(
        user_id,
        f"You have been assigned to project: {project.name}",
        subject="STAFFLY Project Assignment",
        target_url=url_for("projects.project_detail", project_id=project.id),
    )
    db.session.commit()

    flash("Project allocation confirmed for selected employee.", "success")
    return _post_allocation_redirect(project.id)


@project_bp.route("/<int:project_id>/assign-team", methods=["POST"])
@login_required
@role_required("Admin")
def assign_suggested_team(project_id):
    project = Project.query.get_or_404(project_id)
    user_ids = request.form.getlist("user_ids")

    if not user_ids:
        flash("No team members were provided.", "warning")
        return redirect(url_for("projects.project_detail", project_id=project.id))

    created_count = 0
    leader_exists = ProjectAssignment.query.filter_by(project_id=project.id, is_team_leader=True).first() is not None
    leader_id = request.form.get("leader_id", type=int)
    for user_id in user_ids:
        try:
            parsed_id = int(user_id)
        except ValueError:
            continue
        exists = ProjectAssignment.query.filter_by(project_id=project.id, user_id=parsed_id).first()
        if exists:
            continue

        assignment = ProjectAssignment(project_id=project.id, user_id=parsed_id, is_team_leader=False)
        if not leader_exists:
            if leader_id and parsed_id == leader_id:
                assignment.is_team_leader = True
                leader_exists = True
            elif not leader_id:
                assignment.is_team_leader = True
                leader_exists = True

        db.session.add(assignment)
        create_notification_with_target(
            parsed_id,
            f"You have been assigned to project: {project.name}",
            subject="STAFFLY Project Assignment",
            target_url=url_for("projects.project_detail", project_id=project.id),
        )
        created_count += 1

    db.session.commit()
    if created_count:
        flash(f"Project allocation confirmed for suggested team ({created_count} new assignments).", "success")
    else:
        flash("All suggested members were already assigned.", "info")
    return _post_allocation_redirect(project.id)


@project_bp.route("/<int:project_id>/set-leader", methods=["POST"])
@login_required
@role_required("Admin")
def set_team_leader(project_id):
    project = Project.query.get_or_404(project_id)
    user_id = request.form.get("user_id", type=int)
    assignment = ProjectAssignment.query.filter_by(project_id=project.id, user_id=user_id).first()
    if not assignment:
        flash("Selected employee is not allocated to this project.", "warning")
        return redirect(url_for("projects.project_detail", project_id=project.id))

    ProjectAssignment.query.filter_by(project_id=project.id, is_team_leader=True).update({"is_team_leader": False})
    assignment.is_team_leader = True
    db.session.commit()
    flash("Team leader updated successfully.", "success")
    return redirect(url_for("projects.project_detail", project_id=project.id))


@project_bp.route("/<int:project_id>/remove-member", methods=["POST"])
@login_required
@role_required("Admin")
def remove_project_member(project_id):
    project = Project.query.get_or_404(project_id)
    user_id = request.form.get("user_id", type=int)
    assignment = ProjectAssignment.query.filter_by(project_id=project.id, user_id=user_id).first()
    if not assignment:
        flash("Selected employee is not allocated to this project.", "warning")
        return redirect(url_for("projects.project_detail", project_id=project.id))

    removed_was_leader = assignment.is_team_leader
    db.session.delete(assignment)
    db.session.commit()

    if removed_was_leader:
        next_member = (
            ProjectAssignment.query
            .filter_by(project_id=project.id)
            .order_by(ProjectAssignment.assigned_at.asc())
            .first()
        )
        if next_member:
            next_member.is_team_leader = True
            db.session.commit()

    flash("Employee removed from project allocation.", "info")
    return redirect(url_for("projects.project_detail", project_id=project.id))


@project_bp.route("/notifications/unread")
@login_required
def unread_notifications():
    user = current_user()
    unread_items = (
        Notification.query
        .filter_by(user_id=user.id, is_read=False)
        .order_by(Notification.created_at.desc())
        .limit(10)
        .all()
    )

    return jsonify(
        {
            "count": len(unread_items),
            "items": [
                {
                    "id": item.id,
                    "message": item.message,
                    "created_at": item.created_at.strftime("%Y-%m-%d %H:%M"),
                    "url": item.target_url or url_for("projects.notifications_page"),
                }
                for item in unread_items
            ],
        }
    )


@project_bp.route("/notifications")
@login_required
def notifications_page():
    user = current_user()
    all_notifications = (
        Notification.query
        .filter_by(user_id=user.id)
        .order_by(Notification.created_at.desc())
        .all()
    )
    return render_template("projects/notifications.html", notifications=all_notifications)


@project_bp.route("/notifications/mark-read", methods=["POST"])
@login_required
def mark_notifications_read():
    user = current_user()
    Notification.query.filter_by(user_id=user.id, is_read=False).update({"is_read": True})
    db.session.commit()
    return jsonify({"status": "ok"})
