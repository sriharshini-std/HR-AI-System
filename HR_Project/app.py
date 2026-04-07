import random
import secrets
from datetime import date, datetime, time, timedelta
from pathlib import Path

import click
from faker import Faker
from flask import Flask, redirect, url_for
from flask.cli import with_appcontext
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from constants import DESIGNATED_POSITIONS
from models import (
    AttendanceRecord,
    Course,
    DailyProjectReport,
    Notification,
    PastProjectPerformance,
    Project,
    ProjectAssignment,
    ProjectFeedback,
    Skill,
    User,
    db,
    employee_skills,
    project_skills,
    resume_skills,
)
from routes.auth_routes import ADMIN_EMAILS, PRIMARY_ADMIN_EMAIL, SECONDARY_ADMIN_EMAIL, auth_bp, current_user
from routes.employee_routes import employee_bp
from routes.project_routes import project_bp

BASE_DIR = Path(__file__).resolve().parent
INSTANCE_DIR = BASE_DIR / "instance"
DB_PATH = INSTANCE_DIR / "hr_project.db"
ADMIN_EMAIL = PRIMARY_ADMIN_EMAIL
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


def create_app():
    app = Flask(__name__)
    INSTANCE_DIR.mkdir(parents=True, exist_ok=True)

    app.config["SECRET_KEY"] = "change-me-in-production"
    app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{DB_PATH.as_posix()}"
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

    db.init_app(app)

    app.register_blueprint(auth_bp)
    app.register_blueprint(employee_bp, url_prefix="/employees")
    app.register_blueprint(project_bp, url_prefix="/projects")

    @app.route("/")
    def index():
        if current_user():
            return redirect(url_for("auth.dashboard"))
        return redirect(url_for("auth.home"))

    with app.app_context():
        db.create_all()
        ensure_project_status_column()
        ensure_project_timeline_columns()
        ensure_assignment_leader_column()
        ensure_user_position_column()
        ensure_user_registration_column()
        ensure_user_security_code_column()
        ensure_attendance_log_columns()
        ensure_skill_proficiency_columns()
        ensure_employee_skill_proficiency_band()
        ensure_performance_data_columns()
        sync_project_status_from_timeline()
        ensure_each_project_has_leader()
        ensure_default_admin()
        ensure_fixed_auth_emails()
        ensure_priority_employee_project_coverage()
        seed_course_catalog()
        normalize_course_catalog_links()
        generate_ongoing_project_reports()

    register_cli_commands(app)

    return app


def ensure_default_admin():
    changed = False
    existing_admins = {admin.email: admin for admin in User.query.filter(User.role == "Admin").all()}
    admin_profiles = [
        ("System Admin", PRIMARY_ADMIN_EMAIL),
        ("System Admin", SECONDARY_ADMIN_EMAIL),
    ]

    for admin_name, admin_email in admin_profiles:
        admin = existing_admins.get(admin_email)
        if admin:
            if admin.name != admin_name:
                admin.name = admin_name
                changed = True
            if admin.position != "HR Specialist":
                admin.position = "HR Specialist"
                changed = True
            if admin.department != "Administration":
                admin.department = "Administration"
                changed = True
            if not admin.is_registered:
                admin.is_registered = True
                changed = True
            continue

    if changed:
        db.session.commit()

    for admin_name, admin_email in admin_profiles:
        if User.query.filter_by(role="Admin", email=admin_email).first():
            continue

        admin = User(
            name=admin_name,
            email=admin_email,
            role="Admin",
            position="HR Specialist",
            department="Administration",
            is_registered=True,
        )
        admin.set_password(secrets.token_urlsafe(16))
        db.session.add(admin)
        try:
            db.session.commit()
        except IntegrityError:
            db.session.rollback()


def ensure_fixed_auth_emails():
    employees = User.query.filter(User.role != "Admin").order_by(User.id.asc()).all()
    if not employees:
        return

    target_pairs = [
        (employees[0], "abdulazeez9143@gmail.com", "Abdul Azeez"),
        (employees[-1], "sureshsharan233@gmail.com", "Suresh Sharan"),
    ]

    occupied_targets = {email for _, email, _ in target_pairs}
    changed = False

    for user in User.query.filter(User.role != "Admin").all():
        if user not in {pair[0] for pair in target_pairs} and user.email in occupied_targets:
            user.email = f"user_{user.id}@example.org"
            changed = True

    for employee, target_email, target_name in target_pairs:
        if employee.email != target_email:
            employee.email = target_email
            changed = True
        if employee.name != target_name:
            employee.name = target_name
            changed = True

    if changed:
        db.session.commit()


def ensure_priority_employee_project_coverage():
    target_emails = [
        "abdulazeez9143@gmail.com",
        "sureshsharan233@gmail.com",
    ]
    target_statuses = ["Upcoming", "Ongoing", "Completed"]

    for employee_email in target_emails:
        employee = User.query.filter_by(email=employee_email, role="Employee").first()
        if not employee:
            continue

        assigned_project_ids = {assignment.project_id for assignment in employee.assignments}
        assigned_statuses = {assignment.project.computed_status for assignment in employee.assignments}

        for status in target_statuses:
            if status in assigned_statuses:
                continue

            candidate_project = (
                Project.query
                .filter_by(status=status)
                .outerjoin(ProjectAssignment)
                .group_by(Project.id)
                .order_by(db.func.count(ProjectAssignment.id).asc(), Project.start_date.asc())
                .first()
            )
            if not candidate_project or candidate_project.id in assigned_project_ids:
                continue

            db.session.add(
                ProjectAssignment(
                    project_id=candidate_project.id,
                    user_id=employee.id,
                    is_team_leader=False,
                )
            )
            assigned_project_ids.add(candidate_project.id)
            assigned_statuses.add(status)

    db.session.commit()


def ensure_project_status_column():
    columns = db.session.execute(text("PRAGMA table_info(projects)")).fetchall()
    column_names = {col[1] for col in columns}
    if "status" not in column_names:
        db.session.execute(
            text("ALTER TABLE projects ADD COLUMN status VARCHAR(20) NOT NULL DEFAULT 'Ongoing'")
        )
        db.session.commit()


def ensure_project_timeline_columns():
    columns = db.session.execute(text("PRAGMA table_info(projects)")).fetchall()
    column_names = {col[1] for col in columns}
    if "start_date" not in column_names:
        db.session.execute(
            text("ALTER TABLE projects ADD COLUMN start_date DATE NOT NULL DEFAULT '2026-01-01'")
        )
    if "duration_days" not in column_names:
        db.session.execute(
            text("ALTER TABLE projects ADD COLUMN duration_days INTEGER NOT NULL DEFAULT 30")
        )
    db.session.commit()


def _compute_status(start_date_value, duration_days):
    end_date = start_date_value + timedelta(days=max(1, duration_days) - 1)
    today = date.today()
    if today < start_date_value:
        return "Upcoming"
    if today > end_date:
        return "Completed"
    return "Ongoing"


def sync_project_status_from_timeline():
    projects = Project.query.all()
    changed = False
    for project in projects:
        computed = _compute_status(project.start_date, project.duration_days)
        if project.status != computed:
            project.status = computed
            changed = True
    if changed:
        db.session.commit()


def ensure_assignment_leader_column():
    columns = db.session.execute(text("PRAGMA table_info(project_assignments)")).fetchall()
    column_names = {col[1] for col in columns}
    if "is_team_leader" not in column_names:
        db.session.execute(
            text("ALTER TABLE project_assignments ADD COLUMN is_team_leader BOOLEAN NOT NULL DEFAULT 0")
        )
        db.session.commit()


def ensure_each_project_has_leader():
    projects = Project.query.all()
    changed = False
    for project in projects:
        if not project.assignments:
            continue
        if any(a.is_team_leader for a in project.assignments):
            continue
        first_assignment = sorted(project.assignments, key=lambda a: a.assigned_at)[0]
        first_assignment.is_team_leader = True
        changed = True
    if changed:
        db.session.commit()


def ensure_user_position_column():
    columns = db.session.execute(text("PRAGMA table_info(users)")).fetchall()
    column_names = {col[1] for col in columns}
    if "position" not in column_names:
        db.session.execute(
            text("ALTER TABLE users ADD COLUMN position VARCHAR(120) NOT NULL DEFAULT 'Web Developer'")
        )
        db.session.commit()


def ensure_user_registration_column():
    columns = db.session.execute(text("PRAGMA table_info(users)")).fetchall()
    column_names = {col[1] for col in columns}
    if "is_registered" not in column_names:
        db.session.execute(
            text("ALTER TABLE users ADD COLUMN is_registered BOOLEAN NOT NULL DEFAULT 0")
        )
        db.session.commit()

    db.session.execute(
        text("UPDATE users SET is_registered = 1 WHERE role = 'Admin'")
    )
    db.session.commit()


def ensure_user_security_code_column():
    columns = db.session.execute(text("PRAGMA table_info(users)")).fetchall()
    column_names = {col[1] for col in columns}
    if "security_code_hash" not in column_names:
        db.session.execute(
            text("ALTER TABLE users ADD COLUMN security_code_hash VARCHAR(255)")
        )
        db.session.commit()


def ensure_attendance_log_columns():
    columns = db.session.execute(text("PRAGMA table_info(attendance_records)")).fetchall()
    if not columns:
        return
    column_names = {col[1] for col in columns}
    if "login_time" not in column_names:
        db.session.execute(text("ALTER TABLE attendance_records ADD COLUMN login_time DATETIME"))
    if "logout_time" not in column_names:
        db.session.execute(text("ALTER TABLE attendance_records ADD COLUMN logout_time DATETIME"))
    if "duration_hours" not in column_names:
        db.session.execute(text("ALTER TABLE attendance_records ADD COLUMN duration_hours FLOAT"))
    if "coffee_break_minutes" not in column_names:
        db.session.execute(
            text("ALTER TABLE attendance_records ADD COLUMN coffee_break_minutes INTEGER NOT NULL DEFAULT 0")
        )
    if "food_break_minutes" not in column_names:
        db.session.execute(
            text("ALTER TABLE attendance_records ADD COLUMN food_break_minutes INTEGER NOT NULL DEFAULT 0")
        )
    if "meeting_break_minutes" not in column_names:
        db.session.execute(
            text("ALTER TABLE attendance_records ADD COLUMN meeting_break_minutes INTEGER NOT NULL DEFAULT 0")
        )
    db.session.commit()


def ensure_skill_proficiency_columns():
    for table_name in ["employee_skills", "resume_skills", "project_skills"]:
        columns = db.session.execute(text(f"PRAGMA table_info({table_name})")).fetchall()
        if not columns:
            continue
        column_names = {col[1] for col in columns}
        if "proficiency" not in column_names:
            db.session.execute(
                text(f"ALTER TABLE {table_name} ADD COLUMN proficiency INTEGER NOT NULL DEFAULT 1")
            )
    db.session.commit()


def ensure_employee_skill_proficiency_band():
    db.session.execute(
        employee_skills.update()
        .where(employee_skills.c.proficiency > 2)
        .values(proficiency=2)
    )
    db.session.execute(
        employee_skills.update()
        .where(employee_skills.c.proficiency < 1)
        .values(proficiency=1)
    )
    db.session.execute(
        resume_skills.update()
        .where(resume_skills.c.proficiency > 2)
        .values(proficiency=2)
    )
    db.session.execute(
        resume_skills.update()
        .where(resume_skills.c.proficiency < 1)
        .values(proficiency=1)
    )
    db.session.commit()


def ensure_performance_data_columns():
    columns = db.session.execute(text("PRAGMA table_info(past_project_performances)")).fetchall()
    if not columns:
        return
    column_names = {col[1] for col in columns}
    if "rating" not in column_names:
        db.session.execute(
            text("ALTER TABLE past_project_performances ADD COLUMN rating FLOAT NOT NULL DEFAULT 3.0")
        )
    if "deadline_met" not in column_names:
        db.session.execute(
            text("ALTER TABLE past_project_performances ADD COLUMN deadline_met BOOLEAN NOT NULL DEFAULT 1")
        )
    if "tasks_completed" not in column_names:
        db.session.execute(
            text("ALTER TABLE past_project_performances ADD COLUMN tasks_completed INTEGER NOT NULL DEFAULT 0")
        )
    if "tasks_assigned" not in column_names:
        db.session.execute(
            text("ALTER TABLE past_project_performances ADD COLUMN tasks_assigned INTEGER NOT NULL DEFAULT 0")
        )
    db.session.commit()


def _random_proficiency():
    # Beginner=1, Intermediate=2, Advanced=3, Expert=4
    return random.choices([1, 2, 3, 4], weights=[20, 40, 30, 10], k=1)[0]


def _employee_skill_proficiency():
    return random.choices([1, 2], weights=[55, 45], k=1)[0]


def _course_url_for_platform(platform_name, skill_name):
    query_value = (skill_name or "").replace(" ", "+")
    template = COURSE_PLATFORM_URLS.get(platform_name, "https://www.google.com/search?q={query}+course")
    return template.format(query=query_value)


def normalize_course_catalog_links():
    changed = False
    for course in Course.query.all():
        primary_skill_name = course.skills[0].name if course.skills else course.title.split(" - ")[0].strip()
        normalized_url = _course_url_for_platform(course.platform, primary_skill_name)
        if course.url != normalized_url:
            course.url = normalized_url
            changed = True

    if changed:
        db.session.commit()


def generate_attendance_history(employee_population):
    """Generate last-30-day attendance with realistic break bands and 8-10 net work hours."""
    AttendanceRecord.query.delete()
    db.session.commit()


def generate_ongoing_project_reports(projects=None):
    """Backfill one daily report per assigned employee per working day for ongoing projects."""
    projects = projects or Project.query.filter_by(status="Ongoing").all()
    today = date.today()
    summary_templates = [
        "Worked on {project} implementation tasks and resolved active backlog items.",
        "Reviewed assigned deliverables for {project} and completed planned execution work.",
        "Progressed feature work for {project} and coordinated follow-up actions with the team.",
        "Handled daily development items for {project} and closed scheduled work chunks.",
    ]
    blocker_templates = [
        None,
        "Awaiting review from the team lead.",
        "Minor dependency pending from another module.",
        "No blockers for the day.",
    ]

    created_count = 0
    for project in projects:
        if project.computed_status != "Ongoing":
            continue

        project_start = project.start_date
        elapsed_days = max(1, (today - project_start).days + 1)
        for assignment in project.assignments:
            employee_id = assignment.user_id
            current_day = project_start
            while current_day <= today:
                if current_day.weekday() >= 5:
                    current_day += timedelta(days=1)
                    continue

                exists = DailyProjectReport.query.filter_by(
                    user_id=employee_id,
                    project_id=project.id,
                    report_date=current_day,
                ).first()
                if exists:
                    current_day += timedelta(days=1)
                    continue

                days_since_start = (current_day - project_start).days + 1
                progress_ratio = min(1.0, max(0.05, days_since_start / max(1, project.duration_days)))
                progress_percent = max(5, min(99, int(round(progress_ratio * 100 + random.randint(-5, 5)))))
                work_summary = random.choice(summary_templates).format(project=project.name)
                blocker_text = random.choice(blocker_templates)

                db.session.add(
                    DailyProjectReport(
                        user_id=employee_id,
                        project_id=project.id,
                        report_date=current_day,
                        work_summary=work_summary,
                        blockers=blocker_text,
                        progress_percent=progress_percent,
                        submitted_at=datetime.combine(current_day, time(hour=18, minute=random.randint(0, 30))),
                    )
                )
                created_count += 1
                current_day += timedelta(days=1)

    db.session.commit()
    return created_count


def seed_course_catalog():
    platforms = list(COURSE_PLATFORM_URLS.items())
    price_types = ["Free", "Paid"]
    delivery_modes = ["Recorded", "Live"]
    levels = ["Beginner", "Intermediate", "Advanced"]
    duration_options = {
        "Short": ["2 weeks", "4 weeks", "10 hours", "18 hours"],
        "Long": ["8 weeks", "12 weeks", "4 months", "6 months"],
    }

    existing_titles = {course.title for course in Course.query.all()}
    skills = Skill.query.order_by(Skill.name.asc()).all()

    for skill in skills:
        for index, (platform_name, _url_template) in enumerate(platforms):
            title = f"{skill.name} {['Essentials', 'Bootcamp', 'Mastery'][index % 3]} - {platform_name}"
            if title in existing_titles:
                continue

            level = levels[index % len(levels)]
            price_type = price_types[index % len(price_types)]
            delivery_mode = delivery_modes[(index + 1) % len(delivery_modes)]
            duration_category = "Short" if index % 2 == 0 else "Long"
            duration_text = duration_options[duration_category][index % len(duration_options[duration_category])]

            course = Course(
                title=title,
                platform=platform_name,
                provider=platform_name,
                url=_course_url_for_platform(platform_name, skill.name),
                price_type=price_type,
                delivery_mode=delivery_mode,
                level=level,
                duration_category=duration_category,
                duration_text=duration_text,
                description=f"Structured {skill.name} learning track on {platform_name}.",
            )
            course.skills.append(skill)
            db.session.add(course)
            existing_titles.add(title)

    db.session.commit()


def register_cli_commands(app):
    @app.cli.command("seed-data")
    @click.option("--employees", default=120, show_default=True, type=int, help="Number of employees.")
    @click.option("--projects", default=25, show_default=True, type=int, help="Number of projects.")
    @click.option("--clear", is_flag=True, help="Clear existing non-admin data before seeding.")
    @with_appcontext
    def seed_data(employees, projects, clear):
        fake = Faker()
        Faker.seed(42)
        random.seed(42)

        if clear:
            db.drop_all()
            db.create_all()
            ensure_project_status_column()
            ensure_project_timeline_columns()
            ensure_assignment_leader_column()
            ensure_user_position_column()
            ensure_user_registration_column()
            ensure_attendance_log_columns()
            ensure_skill_proficiency_columns()
            ensure_performance_data_columns()
            ensure_default_admin()
            fake.unique.clear()

        skill_pool = [
            "Python", "Flask", "SQL", "JavaScript", "HTML", "CSS", "React", "Node.js", "Docker",
            "Kubernetes", "AWS", "GCP", "Azure", "Terraform", "Ansible", "Linux", "Git", "CI/CD",
            "REST API", "GraphQL", "Microservices", "Redis", "PostgreSQL", "MySQL", "MongoDB", "ETL",
            "Power BI", "Tableau", "Data Analysis", "Machine Learning", "Deep Learning", "NLP", "MLOps",
            "Data Engineering", "Spark", "Hadoop", "Pandas", "Testing", "Unit Testing", "Integration Testing",
            "Selenium", "PyTest", "UI/UX", "Figma", "Wireframing", "Project Management", "Agile", "Scrum",
            "Jira", "Leadership", "Communication", "DevOps", "Security", "Cybersecurity", "Network Security",
            "Penetration Testing", "HR Analytics", "Payroll", "Recruitment", "Performance Management",
            "Stakeholder Management", "Business Analysis", "Documentation",
        ]

        existing_skill_names = {s.name for s in Skill.query.all()}
        for name in skill_pool:
            if name not in existing_skill_names:
                db.session.add(Skill(name=name))
        db.session.commit()
        skills = Skill.query.all()

        departments = ["Engineering", "HR", "Finance", "Sales", "Operations", "Product"]
        existing_emails = {email for (email,) in db.session.query(User.email).all()}

        created_users = []
        for _ in range(max(0, employees)):
            email = None
            for _attempt in range(20):
                candidate = fake.unique.email()
                if candidate not in existing_emails:
                    email = candidate
                    break
            if email is None:
                email = f"user_{random.randint(100000, 999999)}@example.org"
                while email in existing_emails:
                    email = f"user_{random.randint(100000, 999999)}@example.org"

            existing_emails.add(email)
            employee = User(
                name=fake.name(),
                email=email,
                role="Employee",
                position=random.choice(DESIGNATED_POSITIONS),
                department=random.choice(departments),
                is_registered=False,
            )
            employee.set_password(secrets.token_urlsafe(16))

            updated_skills = random.sample(skills, k=random.randint(3, min(7, len(skills))))
            resume_skill_set = random.sample(skills, k=random.randint(3, min(7, len(skills))))
            employee.skills = updated_skills
            employee.resume_skills = resume_skill_set

            db.session.add(employee)
            created_users.append(employee)

        db.session.commit()

        # Assign proficiency to employee updated/resume skill mappings.
        for employee in created_users:
            for skill in employee.skills:
                db.session.execute(
                    employee_skills.update()
                    .where(employee_skills.c.user_id == employee.id)
                    .where(employee_skills.c.skill_id == skill.id)
                    .values(proficiency=_employee_skill_proficiency())
                )
            for skill in employee.resume_skills:
                db.session.execute(
                    resume_skills.update()
                    .where(resume_skills.c.user_id == employee.id)
                    .where(resume_skills.c.skill_id == skill.id)
                    .values(proficiency=_employee_skill_proficiency())
                )
        db.session.commit()

        employee_population = User.query.filter_by(role="Employee").all()
        generate_attendance_history(employee_population)

        for employee in employee_population:
            history_count = random.randint(3, 6)
            for idx in range(history_count):
                completion_date = date.today() - timedelta(days=random.randint(35, 400))
                project_name = f"Project {idx + 1}"
                deadline_met = random.random() < 0.72

                # Keep task counts realistic and consistent per project.
                tasks_assigned = random.randint(12, 60)
                if deadline_met:
                    completion_ratio = random.uniform(0.82, 1.0)
                else:
                    completion_ratio = random.uniform(0.50, 0.88)
                tasks_completed = min(tasks_assigned, int(round(tasks_assigned * completion_ratio)))

                # Derive rating from completion quality + deadline adherence.
                rating_base = 1.8 + (completion_ratio * 2.9) + (0.4 if deadline_met else -0.35)
                rating = round(max(1.0, min(5.0, rating_base + random.uniform(-0.25, 0.25))), 2)

                # Feedback follows rating with small variation.
                feedback_score = round(max(1.0, min(5.0, rating + random.uniform(-0.45, 0.45))), 2)

                # Legacy 0..100 score kept for compatibility, derived from same factors.
                completion_pct = (tasks_completed / tasks_assigned) * 100 if tasks_assigned else 0.0
                perf_score = round(
                    (rating / 5.0) * 55
                    + completion_pct * 0.35
                    + (10 if deadline_met else 0),
                    2,
                )
                perf_score = max(0.0, min(100.0, perf_score))

                db.session.add(
                    PastProjectPerformance(
                        user_id=employee.id,
                        project_name=project_name,
                        score=perf_score,
                        rating=rating,
                        deadline_met=deadline_met,
                        tasks_completed=tasks_completed,
                        tasks_assigned=tasks_assigned,
                        completed_on=completion_date,
                    )
                )
                db.session.add(
                    ProjectFeedback(
                        user_id=employee.id,
                        project_name=project_name,
                        feedback_score=feedback_score,
                        feedback_note=random.choice([
                            "Strong collaboration",
                            "Delivered on time",
                            "High quality output",
                            "Needs mentoring on deadlines",
                            "Excellent stakeholder communication",
                        ]),
                    )
                )

        db.session.commit()

        active_users = User.query.filter_by(role="Employee").all()
        created_projects = []
        for _ in range(max(0, projects)):
            random_offset = random.randint(-120, 120)
            start_date_value = date.today() + timedelta(days=random_offset)
            duration_days = random.randint(30, 180)
            project = Project(
                name=f"{fake.bs().title()} Platform",
                description=fake.paragraph(nb_sentences=3),
                start_date=start_date_value,
                duration_days=duration_days,
                status=_compute_status(start_date_value, duration_days),
            )
            req_skills = random.sample(skills, k=random.randint(3, min(7, len(skills))))
            project.required_skills = req_skills
            db.session.add(project)
            created_projects.append(project)
        db.session.commit()

        # Assign proficiency to project required skill mappings.
        for project in created_projects:
            for skill in project.required_skills:
                db.session.execute(
                    project_skills.update()
                    .where(project_skills.c.project_id == project.id)
                    .where(project_skills.c.skill_id == skill.id)
                    .values(proficiency=_random_proficiency())
                )
        db.session.commit()

        assignment_count = 0
        for project in Project.query.all():
            team_size = random.randint(5, min(10, len(active_users))) if active_users else 0
            team_members = random.sample(active_users, k=team_size) if team_size else []
            leader_set = False

            for member in team_members:
                exists = ProjectAssignment.query.filter_by(project_id=project.id, user_id=member.id).first()
                if exists:
                    continue

                assignment = ProjectAssignment(
                    project_id=project.id,
                    user_id=member.id,
                    is_team_leader=(not leader_set),
                )
                db.session.add(assignment)
                leader_set = True
                db.session.add(
                    Notification(
                        user_id=member.id,
                        message=f"You have been assigned to project: {project.name}",
                    )
                )
                assignment_count += 1

        db.session.commit()
        generate_ongoing_project_reports(Project.query.filter_by(status="Ongoing").all())
        click.echo(
            f"Seed complete: employees={len(created_users)}, projects={len(created_projects)}, "
            f"assignments={assignment_count}, skills={len(skills)}"
        )


if __name__ == "__main__":
    app = create_app()
    app.run(debug=True)

