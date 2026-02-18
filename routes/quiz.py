from flask import Blueprint, render_template, session, redirect, url_for, request, jsonify
from config import supabase
import uuid
import random

quiz = Blueprint("quiz", __name__)

def login_required_custom(f):
    from functools import wraps
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user_id" not in session:
            return redirect(url_for("auth.login"))
        return f(*args, **kwargs)
    return decorated


@quiz.route("/start", methods=["GET", "POST"])
@login_required_custom
def start():
    user_id = session["user_id"]
    section_filter = request.form.get("section", "ALL")
    time_limit = int(request.form.get("time_limit", 3600))  # default 60 min

    # Fetch 30 BOF questions
    bof_query = supabase.table("questions").select("id").eq("question_type", "BOF")
    if section_filter != "ALL":
        bof_query = bof_query.eq("section", section_filter)
    bof_result = bof_query.execute()

    # Fetch 30 TF questions
    tf_query = supabase.table("questions").select("id").eq("question_type", "TF")
    if section_filter != "ALL":
        tf_query = tf_query.eq("section", section_filter)
    tf_result = tf_query.execute()

    bof_ids = [q["id"] for q in bof_result.data]
    tf_ids = [q["id"] for q in tf_result.data]

    # Randomly pick 30 from each
    selected_bof = random.sample(bof_ids, min(30, len(bof_ids)))
    selected_tf = random.sample(tf_ids, min(30, len(tf_ids)))
    all_question_ids = selected_bof + selected_tf
    random.shuffle(all_question_ids)

    if len(all_question_ids) == 0:
        return redirect(url_for("dashboard.home"))

    # Create session
    session_id = str(uuid.uuid4())
    supabase.table("sessions").insert({
        "id": session_id,
        "user_id": user_id,
        "section_filter": section_filter,
        "total_questions": len(all_question_ids),
        "bof_count": len(selected_bof),
        "tf_count": len(selected_tf),
        "time_limit_seconds": time_limit
    }).execute()

    # Insert session questions
    session_questions = [
        {"session_id": session_id, "question_id": qid, "question_order": i+1}
        for i, qid in enumerate(all_question_ids)
    ]
    supabase.table("session_questions").insert(session_questions).execute()

    session["quiz_session_id"] = session_id
    session["quiz_question_ids"] = all_question_ids
    session["quiz_current"] = 0

    return redirect(url_for("quiz.question"))


@quiz.route("/question")
@login_required_custom
def question():
    quiz_session_id = session.get("quiz_session_id")
    question_ids = session.get("quiz_question_ids", [])
    current = session.get("quiz_current", 0)

    if not quiz_session_id or current >= len(question_ids):
        return redirect(url_for("quiz.results"))

    question_id = question_ids[current]

    # Fetch question
    q_result = supabase.table("questions").select("*").eq("id", question_id).execute()
    question_data = q_result.data[0] if q_result.data else None

    options = []
    tf_statements = []

    if question_data:
        if question_data["question_type"] == "BOF":
            opt_result = supabase.table("options").select("*").eq("question_id", question_id).order("option_label").execute()
            options = opt_result.data
        else:
            tf_result = supabase.table("tf_statements").select("*").eq("question_id", question_id).order("statement_number").execute()
            tf_statements = tf_result.data

    # Get session time info
    sess_result = supabase.table("sessions").select("started_at, time_limit_seconds").eq("id", quiz_session_id).execute()
    sess_data = sess_result.data[0] if sess_result.data else {}

    return render_template("quiz.html",
                           question=question_data,
                           options=options,
                           tf_statements=tf_statements,
                           current=current + 1,
                           total=len(question_ids),
                           session_id=quiz_session_id,
                           time_limit=sess_data.get("time_limit_seconds", 3600),
                           started_at=sess_data.get("started_at"))


@quiz.route("/submit_answer", methods=["POST"])
@login_required_custom
def submit_answer():
    user_id = session["user_id"]
    quiz_session_id = session.get("quiz_session_id")
    question_ids = session.get("quiz_question_ids", [])
    current = session.get("quiz_current", 0)

    question_id = question_ids[current]
    data = request.form

    # Fetch correct answer
    q_result = supabase.table("questions").select("question_type").eq("id", question_id).execute()
    q_type = q_result.data[0]["question_type"] if q_result.data else None

    is_correct = False
    marks = 0
    bof_answer = None
    tf_answers = None

    if q_type == "BOF":
        bof_answer = data.get("bof_answer")
        correct_opt = supabase.table("options").select("option_label").eq("question_id", question_id).eq("is_correct", True).execute()
        correct_label = correct_opt.data[0]["option_label"] if correct_opt.data else None
        is_correct = bof_answer == correct_label
        marks = 1 if is_correct else 0

    elif q_type == "TF":
        tf_statements = supabase.table("tf_statements").select("*").eq("question_id", question_id).order("statement_number").execute()
        tf_answers = []
        correct_count = 0
        total_statements = len(tf_statements.data)
        for stmt in tf_statements.data:
            user_ans = data.get(f"tf_{stmt['statement_number']}") == "true"
            tf_answers.append(user_ans)
            if user_ans == stmt["is_true"]:
                correct_count += 1
        is_correct = correct_count == total_statements
        marks = round(correct_count / total_statements, 1)

    # Save attempt
    supabase.table("attempts").insert({
        "session_id": quiz_session_id,
        "user_id": user_id,
        "question_id": question_id,
        "question_type": q_type,
        "bof_answer": bof_answer,
        "tf_answers": tf_answers,
        "is_correct": is_correct,
        "marks_obtained": marks
    }).execute()

    # Move to next question
    session["quiz_current"] = current + 1

    if session["quiz_current"] >= len(question_ids):
        return redirect(url_for("quiz.finish"))

    return redirect(url_for("quiz.question"))


@quiz.route("/finish")
@login_required_custom
def finish():
    user_id = session["user_id"]
    quiz_session_id = session.get("quiz_session_id")

    # Calculate score
    attempts = supabase.table("attempts").select("marks_obtained, is_correct").eq("session_id", quiz_session_id).execute()
    total_marks = sum(a["marks_obtained"] for a in attempts.data)
    total_possible = len(attempts.data)
    percentage = round((total_marks / total_possible) * 100, 2) if total_possible > 0 else 0

    # Update session
    supabase.table("sessions").update({
        "score": total_marks,
        "total_score": total_possible,
        "percentage": percentage,
        "completed": True,
        "completed_at": "now()"
    }).eq("id", quiz_session_id).execute()

    # Update section progress
    sess_info = supabase.table("sessions").select("section_filter").eq("id", quiz_session_id).execute()
    section = sess_info.data[0]["section_filter"] if sess_info.data else "ALL"

    existing = supabase.table("section_progress").select("*").eq("user_id", user_id).eq("section", section).execute()
    correct_count = sum(1 for a in attempts.data if a["is_correct"])

    if existing.data:
        prev = existing.data[0]
        supabase.table("section_progress").update({
            "questions_attempted": prev["questions_attempted"] + total_possible,
            "questions_correct": prev["questions_correct"] + correct_count,
            "best_score_percentage": max(prev["best_score_percentage"], percentage),
            "last_attempted": "now()"
        }).eq("user_id", user_id).eq("section", section).execute()
    else:
        supabase.table("section_progress").insert({
            "user_id": user_id,
            "section": section,
            "questions_attempted": total_possible,
            "questions_correct": correct_count,
            "best_score_percentage": percentage,
            "last_attempted": "now()"
        }).execute()

    return redirect(url_for("quiz.results"))


@quiz.route("/results")
@login_required_custom
def results():
    quiz_session_id = session.get("quiz_session_id")
    user_id = session["user_id"]

    sess = supabase.table("sessions").select("*").eq("id", quiz_session_id).execute()
    session_data = sess.data[0] if sess.data else {}

    # Get all attempts with question details
    attempts = supabase.table("attempts").select("*, questions(question_text, question_type, explanation, section)").eq("session_id", quiz_session_id).execute()

    return render_template("results.html",
                           session_data=session_data,
                           attempts=attempts.data)


@quiz.route("/bookmark/<int:question_id>", methods=["POST"])
@login_required_custom
def bookmark(question_id):
    user_id = session["user_id"]
    existing = supabase.table("bookmarks").select("id").eq("user_id", user_id).eq("question_id", question_id).execute()
    if existing.data:
        supabase.table("bookmarks").delete().eq("user_id", user_id).eq("question_id", question_id).execute()
        return jsonify({"status": "removed"})
    else:
        supabase.table("bookmarks").insert({"user_id": user_id, "question_id": question_id}).execute()
        return jsonify({"status": "added"})
