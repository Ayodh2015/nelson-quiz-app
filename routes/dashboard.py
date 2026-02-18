from flask import Blueprint, render_template, session, redirect, url_for
from config import get_db_connection

dashboard = Blueprint("dashboard", __name__)

def login_required_custom(f):
    from functools import wraps
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
        with get_db_connection() as conn:
            cur = conn.cursor()

            # Get recent completed sessions
            cur.execute("""
                SELECT * FROM sessions
                WHERE user_id = %s AND completed = TRUE
                ORDER BY completed_at DESC
                LIMIT 10
            """, (user_id,))
            sessions_data = cur.fetchall()

            # Get section progress
            cur.execute("""
                SELECT * FROM section_progress
                WHERE user_id = %s
            """, (user_id,))
            progress = cur.fetchall()

            # Get bookmarks count
            cur.execute("""
                SELECT COUNT(*) as count FROM bookmarks
                WHERE user_id = %s
            """, (user_id,))
            bookmarks_count = cur.fetchone()["count"]

            # Get all sections
            cur.execute("SELECT * FROM sections ORDER BY id")
            sections = cur.fetchall()

            cur.close()

        # Calculate stats
        avg_score = round(sum(s["percentage"] for s in sessions_data) / len(sessions_data), 1) if sessions_data else 0
        best_score = max((s["percentage"] for s in sessions_data), default=0)

        stats = {
            "total_sessions": len(sessions_data),
            "avg_score": avg_score,
            "best_score": best_score,
            "bookmarks_count": bookmarks_count
        }

        return render_template("dashboard.html",
                               sessions=sessions_data,
                               progress=progress,
                               sections=sections,
                               stats=stats)
    except Exception as e:
        # Log error in production: logger.error(f"Dashboard load error: {e}")
        return redirect(url_for("auth.login"))
