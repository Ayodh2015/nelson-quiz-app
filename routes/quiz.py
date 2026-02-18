from flask import Blueprint, render_template, session, redirect, url_for, request, jsonify
from config import get_db
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
    time_limit = int(request.form.get("time_limit", 3600))

    conn = get_db()
    cur = conn.cursor()

    # Fetch BOF question IDs
    if section_filter == "ALL":
        cur.execute("SELECT id FROM questions WHERE question_type = 'BOF'")
    else:
        cur.execute("SELECT id FROM questions WHERE question_type = 'BOF' AND section = %s", (section_filter,))
    bof_ids = [r["id"] for r in cur.fetchall()]

    # Fetch TF question IDs
    if section_filter == "ALL":
        cur.execute("SELECT id FROM questions WHERE question_type = 'TF'")
    else:
        cur.execute("SELECT id FROM questions WHERE question_type = 'TF' AND section = %s", (section_filter,))
    tf_ids = [r["id"] for r in cur.fetchall()]

    selected_bof = random.sample(bof_ids, min(30, len(bof_ids)))
    selected_tf = random.sample(tf_ids, min(30, len(tf_ids)))
    all_question_ids = selected_bof + selected_tf
    random.shuffle(all_question_ids)

    if not all_question_ids:
        cur.close()
        conn.close()
        return redirect(url_for("dashboard.home"))

    # Create session
    session_id = str(uuid.uuid4())
    cur.execute("""
        INSERT INTO sessions (id, user_id, section_filter, total_questions, bof_count, tf_count, time_limit_seconds)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
    """, (session_id, user_id, section_filter, len(all_question_ids), len(selected_bof), len(selected_tf), time_limit))

    # Insert session questions
    for i, qid in enumerate(all_question_ids):
        cur.execute("""
            INSERT INTO session_questions (session_id, question_id, question_order)
            VALUES (%s, %s, %s)
        """, (session_id, qid, i + 1))

    conn.commit()
    cur.close()
    conn.close()

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

    conn = get_db()
    cur = conn.cursor()

    cur.execute("SELECT * FROM questions WHERE id = %s", (question_id,))
    question_data = cur.fetchone()

    options = []
    tf_statements = []

    if question_data:
        if question_data["question_type"] == "BOF":
            cur.execute("SELECT * FROM options WHERE question_id = %s ORDER BY option_label", (question_id,))
            options = cur.fetchall()
        else:
            cur.execute("SELECT * FROM tf_statements WHERE question_id = %s ORDER BY statement_number", (question_id,))
            tf_statements = cur.fetchall()

    cur.execute("SELECT started_at, time_limit_seconds FROM sessions WHERE id = %s", (quiz_session_id,))
    sess_data = cur.fetchone()

    cur.close()
    conn.close()

    return render_template("quiz.html",
                           question=question_data,
                           options=options,
                           tf_statements=tf_statements,
                           current=current + 1,
                           total=len(question_ids),
                           session_id=quiz_session_id,
                           time_limit=sess_data["time_limit_seconds"] if sess_data else 3600,
                           started_at=sess_data["started_at"] if sess_data else None)


@quiz.route("/submit_answer", methods=["POST"])
@login_required_custom
def submit_answer():
    user_id = session["user_id"]
    quiz_session_id = session.get("quiz_session_id")
    question_ids = session.get("quiz_question_ids", [])
    current = session.get("quiz_current", 0)

    question_id = question_ids[current]
    data = request.form

    conn = get_db()
    cur = conn.cursor()

    cur.execute("SELECT question_type FROM questions WHERE id = %s", (question_id,))
    q = cur.fetchone()
    q_type = q["question_type"] if q else None

    is_correct = False
    marks = 0
    bof_answer = None
    tf_answers = None

    if q_type == "BOF":
        bof_answer = data.get("bof_answer")
        cur.execute("SELECT option_label FROM options WHERE question_id = %s AND is_correct = TRUE", (question_id,))
        correct = cur.fetchone()
        correct_label = correct["option_label"] if correct else None
        is_correct = bof_answer == correct_label
        marks = 1 if is_correct else 0

    elif q_type == "TF":
        cur.execute("SELECT * FROM tf_statements WHERE question_id = %s ORDER BY statement_number", (question_id,))
        tf_stmts = cur.fetchall()
        tf_answers = []
        correct_count = 0
        for stmt in tf_stmts:
            user_ans = data.get(f"tf_{stmt['statement_number']}") == "true"
            tf_answers.append(user_ans)
            if user_ans == stmt["is_true"]:
                correct_count += 1
        is_correct = correct_count == len(tf_stmts)
        marks = round(correct_count / len(tf_stmts), 1) if tf_stmts else 0

    cur.execute("""
        INSERT INTO attempts (session_id, user_id, question_id, question_type, bof_answer, tf_answers, is_correct, marks_obtained)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
    """, (quiz_session_id, user_id, question_id, q_type, bof_answer, tf_answers, is_correct, marks))

    conn.commit()
    cur.close()
    conn.close()

    session["quiz_current"] = current + 1

    if session["quiz_current"] >= len(question_ids):
        return redirect(url_for("quiz.finish"))

    return redirect(url_for("quiz.question"))


@quiz.route("/finish")
@login_required_custom
def finish():
    user_id = session["user_id"]
    quiz_session_id = session.get("quiz_session_id")

    conn = get_db()
    cur = conn.cursor()

    cur.execute("SELECT marks_obtained, is_correct FROM attempts WHERE session_id = %s", (quiz_session_id,))
    attempts = cur.fetchall()

    total_marks = sum(a["marks_obtained"] for a in attempts)
    total_possible = len(attempts)
    percentage = round((total_marks / total_possible) * 100, 2) if total_possible > 0 else 0

    cur.execute("""
        UPDATE sessions
        SET score = %s, total_score = %s, percentage = %s, completed = TRUE, completed_at = NOW()
        WHERE id = %s
    """, (total_marks, total_possible, percentage, quiz_session_id))

    cur.execute("SELECT section_filter FROM sessions WHERE id = %s", (quiz_session_id,))
    sess = cur.fetchone()
    section = sess["section_filter"] if sess else "ALL"

    correct_count = sum(1 for a in attempts if a["is_correct"])

    cur.execute("""
        SELECT * FROM section_progress WHERE user_id = %s AND section = %s
    """, (user_id, section))
    existing = cur.fetchone()

    if existing:
        cur.execute("""
            UPDATE section_progress
            SET questions_attempted = questions_attempted + %s,
                questions_correct = questions_correct + %s,
                best_score_percentage = GREATEST(best_score_percentage, %s),
                last_attempted = NOW()
            WHERE user_id = %s AND section = %s
        """, (total_possible, correct_count, percentage, user_id, section))
    else:
        cur.execute("""
            INSERT INTO section_progress (user_id, section, questions_attempted, questions_correct, best_score_percentage, last_attempted)
            VALUES (%s, %s, %s, %s, %s, NOW())
        """, (user_id, section, total_possible, correct_count, percentage))

    conn.commit()
    cur.close()
    conn.close()

    return redirect(url_for("quiz.results"))


@quiz.route("/results")
@login_required_custom
def results():
    quiz_session_id = session.get("quiz_session_id")

    conn = get_db()
    cur = conn.cursor()

    cur.execute("SELECT * FROM sessions WHERE id = %s", (quiz_session_id,))
    session_data = cur.fetchone()

    cur.execute("""
        SELECT a.*, q.question_text, q.question_type, q.explanation, q.section
        FROM attempts a
        JOIN questions q ON a.question_id = q.id
        WHERE a.session_id = %s
    """, (quiz_session_id,))
    attempts = cur.fetchall()

    cur.close()
    conn.close()

    return render_template("results.html",
                           session_data=session_data,
                           attempts=attempts)


@quiz.route("/bookmark/<int:question_id>", methods=["POST"])
@login_required_custom
def bookmark(question_id):
    user_id = session["user_id"]

    conn = get_db()
    cur = conn.cursor()

    cur.execute("SELECT id FROM bookmarks WHERE user_id = %s AND question_id = %s", (user_id, question_id))
    existing = cur.fetchone()

    if existing:
        cur.execute("DELETE FROM bookmarks WHERE user_id = %s AND question_id = %s", (user_id, question_id))
        conn.commit()
        cur.close()
        conn.close()
        return jsonify({"status": "removed"})
    else:
        cur.execute("INSERT INTO bookmarks (user_id, question_id) VALUES (%s, %s)", (user_id, question_id))
        conn.commit()
        cur.close()
        conn.close()
        return jsonify({"status": "added"})
