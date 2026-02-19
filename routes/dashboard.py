from flask import Blueprint, render_template, session, redirect, url_for
from config import get_db, init_db_pool
from functools import wraps

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
                LIMIT 10
            """, (user_id,))
            sessions_data = cur.fetchall()

            # Section progress
            cur.execute("""
                SELECT * FROM section_progress
                WHERE user_id = %s
            """, (user_id,))
            progress = cur.fetchall()

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

        # Calculate basic stats
        avg_score = round(
            sum(float(s["percentage"]) for s in sessions_data) / len(sessions_data), 1
        ) if sessions_data else 0
        best_score = max((float(s["percentage"]) for s in sessions_data), default=0)

        # Calculate detailed performance stats
        total_questions = len(all_attempts)
        total_correct = sum(1 for a in all_attempts if a["is_correct"])
        total_wrong = total_questions - total_correct
        total_marks = sum(float(a["marks_obtained"]) for a in all_attempts)

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
                               sections=sections,
                               stats=stats)
    except Exception:
        return render_template("dashboard.html",
                               sessions=[],
                               progress=[],
                               sections=[],
                               stats={
                                   "total_sessions": 0, "avg_score": 0, "best_score": 0, "bookmarks_count": 0,
                                   "total_questions": 0, "total_correct": 0, "total_wrong": 0, "total_marks": 0,
                                   "bof_total": 0, "bof_correct": 0, "tf_total": 0, "tf_correct": 0
                               })