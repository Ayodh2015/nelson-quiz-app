from flask import Blueprint, render_template, session, redirect, url_for
from config import supabase

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

    # Get completed sessions
    sessions = supabase.table("sessions")\
        .select("*")\
        .eq("user_id", user_id)\
        .eq("completed", True)\
        .order("completed_at", desc=True)\
        .limit(10)\
        .execute()

    # Get section progress
    progress = supabase.table("section_progress")\
        .select("*")\
        .eq("user_id", user_id)\
        .execute()

    # Get bookmarks count
    bookmarks = supabase.table("bookmarks")\
        .select("id", count="exact")\
        .eq("user_id", user_id)\
        .execute()

    # Get sections list
    sections = supabase.table("sections").select("*").order("id").execute()

    stats = {
        "total_sessions": len(sessions.data),
        "avg_score": round(sum(s["percentage"] for s in sessions.data) / len(sessions.data), 1) if sessions.data else 0,
        "best_score": max((s["percentage"] for s in sessions.data), default=0),
        "bookmarks_count": bookmarks.count or 0
    }

    return render_template("dashboard.html",
                           sessions=sessions.data,
                           progress=progress.data,
                           sections=sections.data,
                           stats=stats)
