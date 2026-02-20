from flask import Blueprint, render_template, session, redirect, url_for
from config import get_db, init_db_pool
from functools import wraps
from collections import defaultdict

dashboard = Blueprint("dashboard", __name__)

def login_required_custom(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user_id" not in session:
            return redirect(url_for("auth.login"))
        return f(*args, **kwargs)
    return decorated

@dashboard.route("/dashboard")
@login_required_custom
def home():
    user_id = session["user_id"]

    try:
        conn = get_db()
        try:
            cur = conn.cursor()

            # Recent completed sessions
            cur.execute("""
                SELECT * FROM sessions
                WHERE user_id = %s AND completed = TRUE
                ORDER BY completed_at DESC
            """, (user_id,))
            sessions_data = cur.fetchall()

            # Section progress
            cur.execute("""
                SELECT a.session_id, q.section, a.is_correct, s.completed_at
                FROM attempts a
                JOIN sessions s ON a.session_id = s.id
                JOIN questions q ON a.question_id = q.id
                WHERE s.user_id = %s AND s.completed = TRUE
            """, (user_id,))
            progress_attempt_rows = cur.fetchall()

            # Bookmarks count
            cur.execute("""
                SELECT COUNT(*) as count FROM bookmarks
                WHERE user_id = %s
            """, (user_id,))
            bookmarks_count = cur.fetchone()["count"]

            # All sections with question counts
            cur.execute("SELECT * FROM sections ORDER BY id")
            sections = cur.fetchall()

            # Get all attempts across all completed sessions for detailed stats
            cur.execute("""
                SELECT a.is_correct, a.marks_obtained, a.question_type
                FROM attempts a
                JOIN sessions s ON a.session_id = s.id
                WHERE s.user_id = %s AND s.completed = TRUE
            """, (user_id,))
            all_attempts = cur.fetchall()

            cur.close()
        finally:
            pool = init_db_pool()
            pool.putconn(conn)

        # Build section progress from all completed attempts so dashboard stays correct
        # even if section_progress table is stale/missing older updates.
        section_totals = defaultdict(lambda: {
            "section": "",
            "questions_attempted": 0,
            "questions_correct": 0,
            "best_score_percentage": 0.0,
            "last_attempted": None
        })
        session_section = defaultdict(lambda: {"total": 0, "correct": 0})

        for row in progress_attempt_rows:
            section = row["section"]
            sid = row["session_id"]
            key = (sid, section)

            session_section[key]["total"] += 1
            if row["is_correct"]:
                session_section[key]["correct"] += 1

            section_totals[section]["section"] = section
            section_totals[section]["questions_attempted"] += 1
            if row["is_correct"]:
                section_totals[section]["questions_correct"] += 1

            completed_at = row["completed_at"]
            if completed_at and (
                section_totals[section]["last_attempted"] is None
                or completed_at > section_totals[section]["last_attempted"]
            ):
                section_totals[section]["last_attempted"] = completed_at

        for (sid, section), stat in session_section.items():
            pct = round((stat["correct"] / stat["total"]) * 100, 2) if stat["total"] else 0
            if pct > section_totals[section]["best_score_percentage"]:
                section_totals[section]["best_score_percentage"] = pct

        progress = list(section_totals.values())
        progress_map = {p["section"]: p for p in progress}

        # Calculate basic stats
        percentages = [float(s["percentage"]) for s in sessions_data if s.get("percentage") is not None]
        avg_score = round(sum(percentages) / len(percentages), 1) if percentages else 0
        best_score = max(percentages, default=0)

        # Calculate detailed performance stats
        total_questions = len(all_attempts)
        total_correct = sum(1 for a in all_attempts if a["is_correct"])
        total_wrong = total_questions - total_correct
        total_marks = sum(float(a["marks_obtained"] or 0) for a in all_attempts)

        # BOF vs T/F breakdown
        bof_attempts = [a for a in all_attempts if a["question_type"] == "BOF"]
        tf_attempts = [a for a in all_attempts if a["question_type"] == "TF"]
        bof_correct = sum(1 for a in bof_attempts if a["is_correct"])
        tf_correct = sum(1 for a in tf_attempts if a["is_correct"])

        stats = {
            "total_sessions": len(sessions_data),
            "avg_score": avg_score,
            "best_score": best_score,
            "bookmarks_count": bookmarks_count,
            "total_questions": total_questions,
            "total_correct": total_correct,
            "total_wrong": total_wrong,
            "total_marks": round(total_marks, 1),
            "bof_total": len(bof_attempts),
            "bof_correct": bof_correct,
            "tf_total": len(tf_attempts),
            "tf_correct": tf_correct
        }

        return render_template("dashboard.html",
                               sessions=sessions_data,
                               progress=progress,
                               progress_map=progress_map,
                               sections=sections,
                               stats=stats)
    except Exception:
        return render_template("dashboard.html",
                               sessions=[],
                               progress=[],
                               progress_map={},
                               sections=[],
                               stats={
                                   "total_sessions": 0, "avg_score": 0, "best_score": 0, "bookmarks_count": 0,
                                   "total_questions": 0, "total_correct": 0, "total_wrong": 0, "total_marks": 0,
                                   "bof_total": 0, "bof_correct": 0, "tf_total": 0, "tf_correct": 0
                               })
