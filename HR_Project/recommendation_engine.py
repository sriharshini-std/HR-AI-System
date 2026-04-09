import random
from datetime import date, timedelta
from typing import Dict, List

from models import Course, Skill, db, employee_skills, project_skills, resume_skills


def calculate_attendance_metrics(employee) -> Dict:
    """Calculate attendance KPIs for the last 30 days (Mon-Fri working days)."""
    end_date = date.today()
    start_date = end_date - timedelta(days=29)

    all_days = [start_date + timedelta(days=offset) for offset in range(30)]
    working_days = [day for day in all_days if day.weekday() < 5]
    working_days_count = len(working_days)

    attendance_by_date = {row.record_date: row for row in employee.attendance_records}
    present_days = 0
    late_arrivals = 0
    total_hours_worked = 0.0
    on_time_days = 0

    # On-time if login is on or before 09:30 AM.
    for working_day in working_days:
        row = attendance_by_date.get(working_day)
        if not row or not row.login_time or not row.logout_time or row.duration_hours is None:
            continue

        present_days += 1
        total_hours_worked += float(row.duration_hours)

        is_on_time = (
            row.login_time.hour < 9
            or (row.login_time.hour == 9 and row.login_time.minute <= 30)
        )
        if is_on_time:
            on_time_days += 1
        else:
            late_arrivals += 1

    days_absent = max(0, working_days_count - present_days)
    expected_hours = working_days_count * 8.5

    attendance_percentage = 0.0 if working_days_count == 0 else (present_days / working_days_count) * 100
    punctuality_percentage = 0.0 if present_days == 0 else (on_time_days / present_days) * 100
    work_hour_completion_percentage = 0.0 if expected_hours == 0 else (total_hours_worked / expected_hours) * 100

    attendance_score = (
        (0.6 * attendance_percentage)
        + (0.2 * punctuality_percentage)
        + (0.2 * work_hour_completion_percentage)
    )

    return {
        "working_days": working_days_count,
        "present_days": present_days,
        "absent_days": days_absent,
        "late_arrivals": late_arrivals,
        "total_hours_worked": round(total_hours_worked, 2),
        "expected_hours": round(expected_hours, 2),
        "attendance_percentage": round(attendance_percentage, 2),
        "punctuality_percentage": round(punctuality_percentage, 2),
        "work_hour_completion_percentage": round(work_hour_completion_percentage, 2),
        "attendance_score": round(attendance_score, 2),
    }


def calculate_performance_score(employee) -> float:
    """Performance score using rating, tasks, deadline adherence, and peer feedback."""
    return calculate_performance_metrics(employee)["performance_score"]


def calculate_performance_metrics(employee) -> Dict:
    """
    Project Rating % = (Rating / 5) * 100
    Task Completion % = (Completed / Assigned) * 100
    Deadline Adherence % = On-time projects / Total projects * 100
    Peer Feedback % = (Feedback / 5) * 100

    Performance Score =
      (0.4 * Project Rating %)
      + (0.3 * Task Completion %)
      + (0.2 * Deadline Adherence %)
      + (0.1 * Peer Feedback %)
    """
    perf_rows = employee.past_performance_records
    feedback_rows = employee.feedback_records

    if perf_rows:
        avg_rating = sum(float(getattr(row, "rating", 0.0) or 0.0) for row in perf_rows) / len(perf_rows)
        project_rating_percentage = (avg_rating / 5.0) * 100

        total_tasks_completed = sum(max(0, int(getattr(row, "tasks_completed", 0) or 0)) for row in perf_rows)
        total_tasks_assigned = sum(max(0, int(getattr(row, "tasks_assigned", 0) or 0)) for row in perf_rows)
        task_completion_percentage = (
            0.0 if total_tasks_assigned == 0 else (total_tasks_completed / total_tasks_assigned) * 100
        )

        on_time_count = sum(1 for row in perf_rows if bool(getattr(row, "deadline_met", False)))
        deadline_adherence_percentage = (on_time_count / len(perf_rows)) * 100
    else:
        project_rating_percentage = 0.0
        task_completion_percentage = 0.0
        deadline_adherence_percentage = 0.0
        total_tasks_completed = 0
        total_tasks_assigned = 0
        on_time_count = 0

    if feedback_rows:
        avg_feedback = sum(float(row.feedback_score) for row in feedback_rows) / len(feedback_rows)
        peer_feedback_percentage = (avg_feedback / 5.0) * 100
    else:
        peer_feedback_percentage = 0.0

    performance_score = (
        (0.4 * project_rating_percentage)
        + (0.3 * task_completion_percentage)
        + (0.2 * deadline_adherence_percentage)
        + (0.1 * peer_feedback_percentage)
    )

    return {
        "project_rating_percentage": round(project_rating_percentage, 2),
        "task_completion_percentage": round(task_completion_percentage, 2),
        "deadline_adherence_percentage": round(deadline_adherence_percentage, 2),
        "peer_feedback_percentage": round(peer_feedback_percentage, 2),
        "performance_score": round(performance_score, 2),
        "total_projects": len(perf_rows),
        "projects_on_time": on_time_count,
        "tasks_completed": total_tasks_completed,
        "tasks_assigned": total_tasks_assigned,
    }


def calculate_attendance_score(employee) -> float:
    """Attendance score using weighted formula requested by business rules."""
    return calculate_attendance_metrics(employee)["attendance_score"]


def calculate_skill_score(employee) -> float:
    """Skill score without project context using resume + updated skills."""
    proficiency_map = _employee_skill_proficiency_map(employee.id)
    if not proficiency_map:
        return 0.0
    numerator = sum(proficiency_map.values())
    denominator = len(proficiency_map) * 4  # Expert = 4 max
    return round((numerator / denominator) * 100, 2) if denominator else 0.0


def calculate_overall_employee_score(employee) -> float:
    """
    Overall Score =
      (0.4 * Skill Score) +
      (0.3 * Performance Score) +
      (0.3 * Attendance Score)
    """
    skill_score = calculate_skill_score(employee)
    performance_score = calculate_performance_score(employee)
    attendance_score = calculate_attendance_score(employee)

    overall_score = (
        (0.4 * skill_score)
        + (0.3 * performance_score)
        + (0.3 * attendance_score)
    )
    return round(overall_score, 2)


def _employee_skill_proficiency_map(employee_id: int) -> Dict[int, int]:
    """Return best proficiency per skill using resume and updated skill mappings."""
    proficiency_map: Dict[int, int] = {}

    updated_rows = db.session.execute(
        db.select(employee_skills.c.skill_id, employee_skills.c.proficiency).where(employee_skills.c.user_id == employee_id)
    ).all()
    for skill_id, proficiency in updated_rows:
        proficiency_map[skill_id] = max(proficiency_map.get(skill_id, 0), int(proficiency))

    resume_rows = db.session.execute(
        db.select(resume_skills.c.skill_id, resume_skills.c.proficiency).where(resume_skills.c.user_id == employee_id)
    ).all()
    for skill_id, proficiency in resume_rows:
        proficiency_map[skill_id] = max(proficiency_map.get(skill_id, 0), int(proficiency))

    return proficiency_map


def calculate_project_skill_score(employee, project) -> float:
    """
    Skill Score =
      Sum(Employee proficiency for matched skills)
      /
      Sum(Max possible proficiency for required skills)
      * 100
    """
    required_rows = db.session.execute(
        db.select(project_skills.c.skill_id).where(project_skills.c.project_id == project.id)
    ).all()
    required_skill_ids = [int(row[0]) for row in required_rows]
    if not required_skill_ids:
        return 100.0

    employee_prof_map = _employee_skill_proficiency_map(employee.id)
    numerator = sum(employee_prof_map.get(skill_id, 0) for skill_id in required_skill_ids)
    denominator = len(required_skill_ids) * 4  # Expert = 4 max

    if denominator == 0:
        return 0.0
    return round((numerator / denominator) * 100, 2)


def evaluate_employee_for_project(employee, project) -> Dict:
    """Return project fit with matched skills + performance and skill scores."""
    project_skills_set = {skill.name for skill in project.required_skills}
    employee_skill_names = {skill.name for skill in employee.skills}

    performance_score = calculate_performance_score(employee)
    skill_score = calculate_project_skill_score(employee, project)

    if not project_skills_set:
        return {
            "employee": employee,
            "match_percentage": 100.0,
            "matched_skills": sorted(list(employee_skill_names)),
            "missing_skills": [],
            "performance_score": performance_score,
            "skill_score": skill_score,
            "overall_score": round((performance_score * 0.5) + (skill_score * 0.5), 2),
        }

    matched = sorted(list(project_skills_set.intersection(employee_skill_names)))
    missing = sorted(list(project_skills_set.difference(employee_skill_names)))
    match_percentage = round((len(matched) / len(project_skills_set)) * 100, 2)

    overall_score = round(
        (match_percentage * 0.50) + (performance_score * 0.25) + (skill_score * 0.25),
        2,
    )

    return {
        "employee": employee,
        "match_percentage": match_percentage,
        "matched_skills": matched,
        "missing_skills": missing,
        "performance_score": performance_score,
        "skill_score": skill_score,
        "overall_score": overall_score,
    }


def rank_employees_for_project(project, employees) -> List[Dict]:
    """Rank employees by fit. Excludes zero-skill-match rows when project has required skills."""
    scored = [evaluate_employee_for_project(employee, project) for employee in employees]

    required_skills_set = {skill.name for skill in project.required_skills}
    if required_skills_set:
        scored = [row for row in scored if row["matched_skills"]]

    return sorted(
        scored,
        key=lambda row: (
            row["overall_score"],
            row["match_percentage"],
            row["performance_score"],
            row["skill_score"],
            len(row["matched_skills"]),
        ),
        reverse=True,
    )


def suggest_teams_for_project(project, employees, team_size: int | None = None, num_teams: int = 4) -> List[Dict]:
    """Suggest multiple strategic teams using matched skills + performance + skill scores."""
    required_skills_set = {skill.name for skill in project.required_skills}
    ranked = rank_employees_for_project(project, employees)
    if not ranked:
        return []

    eligible_rows = [row for row in ranked if row["matched_skills"]]
    if len(eligible_rows) < 5:
        return []

    min_team_size = 5
    max_team_size = min(10, len(eligible_rows))
    if max_team_size < min_team_size:
        return []

    if team_size is None:
        base_team_size = random.randint(min_team_size, max_team_size)
    else:
        base_team_size = max(min_team_size, min(10, team_size, len(eligible_rows)))

    suggestions: List[Dict] = []

    step = max(1, base_team_size // 2)
    start_indexes = list(range(0, len(eligible_rows), step))

    for start_idx in start_indexes:
        current_team_size = random.randint(min_team_size, max_team_size) if team_size is None else base_team_size
        selected = []
        for offset in range(current_team_size):
            idx = (start_idx + offset) % len(eligible_rows)
            selected.append(eligible_rows[idx])

        uniq = []
        seen_ids = set()
        for row in selected:
            emp_id = row["employee"].id
            if emp_id in seen_ids:
                continue
            seen_ids.add(emp_id)
            uniq.append(row)
        selected = uniq

        if len(selected) < 5:
            continue

        covered = set()
        for member in selected:
            covered.update(member["matched_skills"])
        uncovered = required_skills_set.difference(covered)

        coverage = 100.0
        if required_skills_set:
            coverage = round((len(covered.intersection(required_skills_set)) / len(required_skills_set)) * 100, 2)

        avg_perf = round(sum(m["performance_score"] for m in selected) / len(selected), 2)
        avg_skill = round(sum(m["skill_score"] for m in selected) / len(selected), 2)

        suggestions.append(
            {
                "members": selected,
                "coverage_percentage": coverage,
                "team_missing_skills": sorted(list(uncovered)),
                "avg_performance_score": avg_perf,
                "avg_skill_score": avg_skill,
            }
        )

        if len(suggestions) >= num_teams:
            break

    return suggestions


def get_employee_learning_targets(employee, selected_skill_names: List[str] | None = None) -> Dict:
    assigned_projects = [
        assignment.project
        for assignment in employee.assignments
        if assignment.project.computed_status in {"Ongoing", "Upcoming"}
    ]
    required_skills = {
        skill.name: skill
        for project in assigned_projects
        for skill in project.required_skills
    }

    owned_skill_names = {skill.name for skill in employee.skills}.union({skill.name for skill in employee.resume_skills})
    missing_skill_names = sorted([skill_name for skill_name in required_skills if skill_name not in owned_skill_names])
    available_search_skill_names = sorted(
        set(required_skills.keys())
        .union(owned_skill_names)
        .union(skill.name for skill in Skill.query.order_by(Skill.name.asc()).all())
    )
    selected_skill_names = selected_skill_names or []
    filtered_selected_skills = [
        skill_name for skill_name in selected_skill_names if skill_name in available_search_skill_names
    ]
    target_skill_names = filtered_selected_skills or missing_skill_names or sorted(required_skills.keys())

    return {
        "assigned_projects": assigned_projects,
        "required_skill_names": sorted(required_skills.keys()),
        "missing_skill_names": missing_skill_names,
        "target_skill_names": target_skill_names,
        "selected_skill_names": filtered_selected_skills,
        "available_search_skill_names": available_search_skill_names,
    }


def recommend_courses_for_employee(employee, filters: Dict | None = None) -> Dict:
    filters = filters or {}
    learning_targets = get_employee_learning_targets(
        employee,
        selected_skill_names=filters.get("selected_skill_names", []),
    )
    target_skill_names = learning_targets["target_skill_names"]
    if not target_skill_names:
        return {**learning_targets, "courses": []}

    query = Course.query
    if filters.get("platforms"):
        query = query.filter(Course.platform.in_(filters["platforms"]))
    if filters.get("price_type"):
        query = query.filter(Course.price_type == filters["price_type"])
    if filters.get("delivery_mode"):
        query = query.filter(Course.delivery_mode == filters["delivery_mode"])
    if filters.get("level"):
        query = query.filter(Course.level == filters["level"])
    if filters.get("duration_category"):
        query = query.filter(Course.duration_category == filters["duration_category"])

    target_skill_set = set(target_skill_names)
    missing_skill_set = set(learning_targets["missing_skill_names"])
    ranked_courses = []

    for course in query.all():
        course_skill_names = {skill.name for skill in course.skills}
        matched_targets = sorted(course_skill_names.intersection(target_skill_set))
        if not matched_targets:
            continue

        priority_score = len(course_skill_names.intersection(missing_skill_set)) * 10
        priority_score += len(matched_targets) * 5
        if course.price_type == "Free":
            priority_score += 2
        if course.delivery_mode == "Recorded":
            priority_score += 1

        ranked_courses.append(
            {
                "course": course,
                "matched_targets": matched_targets,
                "priority_score": priority_score,
            }
        )

    ranked_courses.sort(
        key=lambda row: (
            row["priority_score"],
            len(row["matched_targets"]),
            row["course"].platform,
            row["course"].title,
        ),
        reverse=True,
    )

    return {
        **learning_targets,
        "courses": ranked_courses,
    }
