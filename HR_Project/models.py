from datetime import date, datetime, timedelta

from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import check_password_hash, generate_password_hash


db = SQLAlchemy()


# Employee <-> Updated Skill association
employee_skills = db.Table(
    "employee_skills",
    db.Column("user_id", db.Integer, db.ForeignKey("users.id"), primary_key=True),
    db.Column("skill_id", db.Integer, db.ForeignKey("skills.id"), primary_key=True),
    # Proficiency scale: Beginner=1, Intermediate=2, Advanced=3, Expert=4
    db.Column("proficiency", db.Integer, nullable=False, default=1),
)


# Employee <-> Resume Skill association
resume_skills = db.Table(
    "resume_skills",
    db.Column("user_id", db.Integer, db.ForeignKey("users.id"), primary_key=True),
    db.Column("skill_id", db.Integer, db.ForeignKey("skills.id"), primary_key=True),
    # Proficiency scale: Beginner=1, Intermediate=2, Advanced=3, Expert=4
    db.Column("proficiency", db.Integer, nullable=False, default=1),
)


# Project <-> Required Skill association
project_skills = db.Table(
    "project_skills",
    db.Column("project_id", db.Integer, db.ForeignKey("projects.id"), primary_key=True),
    db.Column("skill_id", db.Integer, db.ForeignKey("skills.id"), primary_key=True),
    # Proficiency scale: Beginner=1, Intermediate=2, Advanced=3, Expert=4
    db.Column("proficiency", db.Integer, nullable=False, default=1),
)


course_skills = db.Table(
    "course_skills",
    db.Column("course_id", db.Integer, db.ForeignKey("courses.id"), primary_key=True),
    db.Column("skill_id", db.Integer, db.ForeignKey("skills.id"), primary_key=True),
)


class User(db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), nullable=False, default="Employee")
    position = db.Column(db.String(120), nullable=False, default="Web Developer")
    department = db.Column(db.String(120), nullable=True)
    is_registered = db.Column(db.Boolean, nullable=False, default=False)
    security_code_hash = db.Column(db.String(255), nullable=True)
    project_start_alert = db.Column(db.Boolean, nullable=False, default=True)
    deadline_alert_30 = db.Column(db.Boolean, nullable=False, default=True)
    deadline_alert_15 = db.Column(db.Boolean, nullable=False, default=True)
    deadline_alert_10 = db.Column(db.Boolean, nullable=False, default=True)
    deadline_alert_5 = db.Column(db.Boolean, nullable=False, default=True)
    deadline_alert_1 = db.Column(db.Boolean, nullable=False, default=True)

    skills = db.relationship("Skill", secondary=employee_skills, back_populates="employees")
    resume_skills = db.relationship("Skill", secondary=resume_skills, back_populates="resume_employees")

    notifications = db.relationship("Notification", backref="user", lazy=True, cascade="all, delete-orphan")
    assignments = db.relationship("ProjectAssignment", backref="employee", lazy=True, cascade="all, delete-orphan")
    attendance_records = db.relationship("AttendanceRecord", backref="employee", lazy=True, cascade="all, delete-orphan")
    leave_requests = db.relationship("LeaveRequest", backref="employee", lazy=True, cascade="all, delete-orphan")
    daily_project_reports = db.relationship("DailyProjectReport", backref="employee", lazy=True, cascade="all, delete-orphan")
    past_performance_records = db.relationship(
        "PastProjectPerformance",
        backref="employee",
        lazy=True,
        cascade="all, delete-orphan",
    )
    feedback_records = db.relationship("ProjectFeedback", backref="employee", lazy=True, cascade="all, delete-orphan")

    def set_password(self, password: str) -> None:
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        return check_password_hash(self.password_hash, password)

    def set_security_code(self, code: str) -> None:
        self.security_code_hash = generate_password_hash(code)

    def check_security_code(self, code: str) -> bool:
        return bool(self.security_code_hash) and check_password_hash(self.security_code_hash, code)


class Skill(db.Model):
    __tablename__ = "skills"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), unique=True, nullable=False)

    employees = db.relationship("User", secondary=employee_skills, back_populates="skills")
    resume_employees = db.relationship("User", secondary=resume_skills, back_populates="resume_skills")
    projects = db.relationship("Project", secondary=project_skills, back_populates="required_skills")
    courses = db.relationship("Course", secondary=course_skills, back_populates="skills")


class Course(db.Model):
    __tablename__ = "courses"

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(180), nullable=False, unique=True)
    platform = db.Column(db.String(80), nullable=False, index=True)
    provider = db.Column(db.String(120), nullable=True)
    url = db.Column(db.String(255), nullable=True)
    price_type = db.Column(db.String(20), nullable=False, default="Paid")
    delivery_mode = db.Column(db.String(20), nullable=False, default="Recorded")
    level = db.Column(db.String(20), nullable=False, default="Beginner")
    duration_category = db.Column(db.String(20), nullable=False, default="Short")
    duration_text = db.Column(db.String(60), nullable=True)
    description = db.Column(db.String(255), nullable=True)

    skills = db.relationship("Skill", secondary=course_skills, back_populates="courses")


class Project(db.Model):
    __tablename__ = "projects"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(150), nullable=False)
    description = db.Column(db.Text, nullable=True)
    status = db.Column(db.String(20), nullable=False, default="Ongoing")
    start_date = db.Column(db.Date, nullable=False, default=date.today)
    duration_days = db.Column(db.Integer, nullable=False, default=30)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    required_skills = db.relationship("Skill", secondary=project_skills, back_populates="projects")
    assignments = db.relationship("ProjectAssignment", backref="project", lazy=True, cascade="all, delete-orphan")
    daily_reports = db.relationship("DailyProjectReport", backref="project", lazy=True, cascade="all, delete-orphan")

    @property
    def end_date(self):
        return self.start_date + timedelta(days=max(1, self.duration_days) - 1)

    @property
    def computed_status(self):
        today = date.today()
        if today < self.start_date:
            return "Upcoming"
        if today > self.end_date:
            return "Completed"
        return "Ongoing"


class ProjectAssignment(db.Model):
    __tablename__ = "project_assignments"
    __table_args__ = (
        db.UniqueConstraint("project_id", "user_id", name="uq_project_user_assignment"),
    )

    id = db.Column(db.Integer, primary_key=True)
    project_id = db.Column(db.Integer, db.ForeignKey("projects.id"), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    is_team_leader = db.Column(db.Boolean, nullable=False, default=False)
    assigned_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)


class DailyProjectReport(db.Model):
    __tablename__ = "daily_project_reports"
    __table_args__ = (
        db.UniqueConstraint("user_id", "project_id", "report_date", name="uq_daily_project_report"),
    )

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    project_id = db.Column(db.Integer, db.ForeignKey("projects.id"), nullable=False, index=True)
    report_date = db.Column(db.Date, nullable=False, index=True)
    work_summary = db.Column(db.String(500), nullable=False)
    blockers = db.Column(db.String(255), nullable=True)
    progress_percent = db.Column(db.Integer, nullable=False, default=0)
    submitted_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)


class AttendanceRecord(db.Model):
    __tablename__ = "attendance_records"
    __table_args__ = (
        db.UniqueConstraint("user_id", "record_date", name="uq_user_daily_attendance"),
    )

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    record_date = db.Column(db.Date, nullable=False)
    login_time = db.Column(db.DateTime, nullable=True)
    logout_time = db.Column(db.DateTime, nullable=True)
    duration_hours = db.Column(db.Float, nullable=True)
    coffee_break_minutes = db.Column(db.Integer, nullable=False, default=0)
    food_break_minutes = db.Column(db.Integer, nullable=False, default=0)
    meeting_break_minutes = db.Column(db.Integer, nullable=False, default=0)
    active_break_type = db.Column(db.String(20), nullable=True)
    break_started_at = db.Column(db.DateTime, nullable=True)

    @property
    def total_break_minutes(self):
        return (
            int(self.coffee_break_minutes or 0)
            + int(self.food_break_minutes or 0)
            + int(self.meeting_break_minutes or 0)
        )


class LeaveRequest(db.Model):
    __tablename__ = "leave_requests"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    start_date = db.Column(db.Date, nullable=False, index=True)
    end_date = db.Column(db.Date, nullable=False, index=True)
    leave_type = db.Column(db.String(50), nullable=False, default="Planned Leave")
    reason = db.Column(db.String(255), nullable=False)
    status = db.Column(db.String(20), nullable=False, default="Pending")
    admin_note = db.Column(db.String(255), nullable=True)
    applied_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    reviewed_at = db.Column(db.DateTime, nullable=True)

    @property
    def total_days(self):
        day_count = 0
        current_day = self.start_date
        while current_day <= self.end_date:
            if current_day.weekday() < 5:
                day_count += 1
            current_day += timedelta(days=1)
        return day_count


class PastProjectPerformance(db.Model):
    __tablename__ = "past_project_performances"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    project_name = db.Column(db.String(150), nullable=False)
    score = db.Column(db.Float, nullable=False)  # Legacy aggregate score 0..100
    rating = db.Column(db.Float, nullable=False, default=3.0)  # 1..5
    deadline_met = db.Column(db.Boolean, nullable=False, default=True)
    tasks_completed = db.Column(db.Integer, nullable=False, default=0)
    tasks_assigned = db.Column(db.Integer, nullable=False, default=0)
    completed_on = db.Column(db.Date, nullable=False)


class ProjectFeedback(db.Model):
    __tablename__ = "project_feedbacks"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    project_name = db.Column(db.String(150), nullable=False)
    feedback_score = db.Column(db.Float, nullable=False)  # 1..5
    feedback_note = db.Column(db.String(255), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)


class Notification(db.Model):
    __tablename__ = "notifications"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    message = db.Column(db.String(255), nullable=False)
    target_url = db.Column(db.String(255), nullable=True)
    is_read = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)


class ProjectAlertLog(db.Model):
    __tablename__ = "project_alert_logs"
    __table_args__ = (
        db.UniqueConstraint("user_id", "project_id", "alert_type", "trigger_date", name="uq_project_alert_log"),
    )

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    project_id = db.Column(db.Integer, db.ForeignKey("projects.id"), nullable=False, index=True)
    alert_type = db.Column(db.String(40), nullable=False, index=True)
    trigger_date = db.Column(db.Date, nullable=False, index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
