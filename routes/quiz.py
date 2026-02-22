from flask import Blueprint, render_template, session, redirect, url_for, request, jsonify, flash
from config import get_db, init_db_pool
import uuid
import random
import re
from markupsafe import Markup, escape

quiz = Blueprint("quiz", __name__)

def login_required_custom(f):
    from functools import wraps
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user_id" not in session:
            return redirect(url_for("auth.login"))
        return f(*args, **kwargs)
    return decorated


def _get_quiz_state():
    quiz_session_id = session.get("quiz_session_id")
    question_ids = session.get("quiz_question_ids")
    current = session.get("quiz_current")

    if not quiz_session_id:
        return None
    if not isinstance(question_ids, list) or not question_ids:
        return None
    if not isinstance(current, int) or current < 0:
        return None

    return quiz_session_id, question_ids, current


def _clear_quiz_state():
    session.pop("quiz_session_id", None)
    session.pop("quiz_question_ids", None)
    session.pop("quiz_current", None)


def _format_explanation_text(text):
    if not text:
        return Markup("")

    raw = str(text).replace("\r\n", "\n").strip()
    if not raw:
        return Markup("")

    # If explanation is a single long paragraph, split into smaller readable chunks.
    if "\n" not in raw:
        sentences = re.split(r"(?<=[.!?])\s+(?=[A-Z])", raw)
        if len(sentences) >= 3:
            parts = [" ".join(sentences[i:i + 2]).strip() for i in range(0, len(sentences), 2)]
        else:
            parts = [raw]
    else:
        parts = [line.strip() for line in raw.split("\n") if line.strip()]

    html_blocks = []
    list_items = []

    for part in parts:
        match = re.match(r"^(?:[-*•]\s+|\d+[.)]\s+)(.+)$", part)
        if match:
            list_items.append(f"<li>{escape(match.group(1))}</li>")
            continue

        if list_items:
            html_blocks.append("<ul class=\"explanation-list\">" + "".join(list_items) + "</ul>")
            list_items = []

        html_blocks.append(f"<p>{escape(part)}</p>")

    if list_items:
        html_blocks.append("<ul class=\"explanation-list\">" + "".join(list_items) + "</ul>")

    return Markup("".join(html_blocks))


def _build_results_payload(cur, quiz_session_id, user_id):
    cur.execute("SELECT * FROM sessions WHERE id = %s AND user_id = %s", (quiz_session_id, user_id))
    session_data = cur.fetchone()
    if not session_data:
        return None, None

    cur.execute("""
        SELECT a.*, q.question_text, q.question_type, q.explanation, q.section
        FROM attempts a
        JOIN questions q ON a.question_id = q.id
        WHERE a.session_id = %s
        ORDER BY a.id
    """, (quiz_session_id,))
    attempts = cur.fetchall()

    attempts_list = []
    for attempt in attempts:
        att = dict(attempt)
        att["explanation_formatted"] = _format_explanation_text(att.get("explanation"))

        if att["question_type"] == "BOF":
            cur.execute("""
                SELECT * FROM options
                WHERE question_id = %s
                ORDER BY option_label
            """, (att["question_id"],))
            att["bof_options"] = cur.fetchall()
            att["tf_statements"] = []
        else:
            cur.execute("""
                SELECT * FROM tf_statements
                WHERE question_id = %s
                ORDER BY statement_number
            """, (att["question_id"],))
            att["tf_statements"] = cur.fetchall()
            att["bof_options"] = []

        attempts_list.append(att)

    return session_data, attempts_list


@quiz.route("/start", methods=["GET", "POST"])
@login_required_custom
def start():
    if request.method == "GET":
        try:
            conn = get_db()
            try:
                cur = conn.cursor()
                cur.execute("SELECT * FROM sections ORDER BY id")
                sections = cur.fetchall()
                cur.close()
            finally:
                pool = init_db_pool()
                pool.putconn(conn)
            return render_template("start_quiz.html", sections=sections)
        except Exception:
            return redirect(url_for("dashboard.home"))

    # POST - process form
    user_id = session["user_id"]
    question_type = request.form.get("question_type", "both")
    num_questions = int(request.form.get("num_questions", 60))
    time_limit = int(request.form.get("time_limit", 3600))
    selected_sections = request.form.getlist("sections")

    if not selected_sections:
        return redirect(url_for("quiz.start"))

    # Build section filter string for display
    section_filter = "ALL" if len(selected_sections) >= 22 else ", ".join(selected_sections[:3]) + ("..." if len(selected_sections) > 3 else "")

    # Calculate split based on type
    if question_type == "both":
        bof_count = num_questions // 2
        tf_count = num_questions - bof_count
    elif question_type == "BOF":
        bof_count = num_questions
        tf_count = 0
    else:  # TF
        bof_count = 0
        tf_count = num_questions

    try:
        conn = get_db()
        try:
            cur = conn.cursor()

            # Fetch BOF questions
            selected_bof = []
            if bof_count > 0:
                placeholders = ','.join(['%s'] * len(selected_sections))
                cur.execute(f"""
                    SELECT id FROM questions
                    WHERE question_type = 'BOF'
                    AND section IN ({placeholders})
                """, selected_sections)
                bof_ids = [r["id"] for r in cur.fetchall()]
                selected_bof = random.sample(bof_ids, min(bof_count, len(bof_ids)))

            # Fetch TF questions
            selected_tf = []
            if tf_count > 0:
                placeholders = ','.join(['%s'] * len(selected_sections))
                cur.execute(f"""
                    SELECT id FROM questions
                    WHERE question_type = 'TF'
                    AND section IN ({placeholders})
                """, selected_sections)
                tf_ids = [r["id"] for r in cur.fetchall()]
                selected_tf = random.sample(tf_ids, min(tf_count, len(tf_ids)))

            # Default order: TF first then BOF (as requested)
            all_question_ids = selected_tf + selected_bof

            if not all_question_ids:
                flash("No questions found for selected options. Please try different settings.", "warning")
                cur.close()
                return redirect(url_for("quiz.start"))

            # Create session
            session_id = str(uuid.uuid4())
            cur.execute("""
                INSERT INTO sessions (id, user_id, section_filter, total_questions, bof_count, tf_count, time_limit_seconds)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
            """, (session_id, user_id, section_filter, len(all_question_ids), len(selected_bof), len(selected_tf), time_limit))

            for i, qid in enumerate(all_question_ids):
                cur.execute("""
                    INSERT INTO session_questions (session_id, question_id, question_order)
                    VALUES (%s, %s, %s)
                """, (session_id, qid, i + 1))

            conn.commit()
            cur.close()

            session["quiz_session_id"] = session_id
            session["quiz_question_ids"] = all_question_ids
            session["quiz_current"] = 0

            return redirect(url_for("quiz.question"))
        finally:
            pool = init_db_pool()
            pool.putconn(conn)
    except Exception:
        return redirect(url_for("dashboard.home"))


@quiz.route("/question")
@login_required_custom
def question():
    quiz_state = _get_quiz_state()
    if not quiz_state:
        return redirect(url_for("quiz.start"))

    quiz_session_id, question_ids, current = quiz_state

    if not quiz_session_id:
        return redirect(url_for("quiz.start"))
    if current >= len(question_ids):
        return redirect(url_for("quiz.finish"))

    question_id = question_ids[current]

    try:
        conn = get_db()
        try:
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

            # Skip malformed questions so user is not blocked on submit validation.
            should_skip = False
            if not question_data:
                should_skip = True
            elif question_data["question_type"] == "BOF" and not options:
                should_skip = True
            elif question_data["question_type"] == "TF" and not tf_statements:
                should_skip = True

            if should_skip:
                cur.close()
                session["quiz_current"] = current + 1
                session.modified = True
                flash("A malformed question was skipped automatically.", "warning")
                if session["quiz_current"] >= len(question_ids):
                    return redirect(url_for("quiz.finish"))
                return redirect(url_for("quiz.question"))

            cur.execute("SELECT started_at, time_limit_seconds FROM sessions WHERE id = %s", (quiz_session_id,))
            sess_data = cur.fetchone()

            cur.close()
        finally:
            pool = init_db_pool()
            pool.putconn(conn)

        time_limit = sess_data["time_limit_seconds"] if sess_data else 3600
        started_at = sess_data["started_at"] if sess_data else None
        started_at_epoch = int(started_at.timestamp()) if started_at else None

        return render_template("quiz.html",
                               question=question_data,
                               options=options,
                               tf_statements=tf_statements,
                               current=current + 1,
                               total=len(question_ids),
                               session_id=quiz_session_id,
                               time_limit=time_limit,
                               started_at_epoch=started_at_epoch)
    except Exception as e:
        # Log error in production: logger.error(f"Question load error: {e}")
        return redirect(url_for("dashboard.home"))


@quiz.route("/submit_answer", methods=["POST"])
@login_required_custom
def submit_answer():
    user_id = session["user_id"]
    quiz_state = _get_quiz_state()
    if not quiz_state:
        return redirect(url_for("quiz.start"))

    quiz_session_id, question_ids, current = quiz_state
    if current >= len(question_ids):
        return redirect(url_for("quiz.finish"))

    question_id = question_ids[current]
    data = request.form

    try:
        conn = get_db()
        try:
            cur = conn.cursor()

            cur.execute("SELECT id FROM attempts WHERE session_id = %s AND question_id = %s", (quiz_session_id, question_id))
            if cur.fetchone():
                # Double-submit: already recorded, just advance and redirect
                cur.close()
                session["quiz_current"] = current + 1
                
                if session["quiz_current"] >= len(question_ids):
                    return redirect(url_for("quiz.finish"))
                return redirect(url_for("quiz.question"))

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
                answered_count = 0
                correct_count = 0
                wrong_count = 0
                for stmt in tf_stmts:
                    raw_ans = data.get(f"tf_{stmt['statement_number']}")
                    if raw_ans == "true":
                        user_ans = True
                    elif raw_ans == "false":
                        user_ans = False
                    else:
                        user_ans = None

                    tf_answers.append(user_ans)
                    if user_ans is None:
                        continue

                    answered_count += 1
                    if user_ans == stmt["is_true"]:
                        correct_count += 1
                    else:
                        wrong_count += 1

                # True/False scoring rule:
                # +0.2 for each answered-correct statement, -0.2 for each answered-wrong statement,
                # unanswered statements contribute 0.
                raw_marks = (correct_count * 0.2) - (wrong_count * 0.2)
                marks = round(max(0, raw_marks), 1)
                is_correct = bool(tf_stmts) and answered_count == len(tf_stmts) and wrong_count == 0

            cur.execute("""
                INSERT INTO attempts (session_id, user_id, question_id, question_type, bof_answer, tf_answers, is_correct, marks_obtained)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """, (quiz_session_id, user_id, question_id, q_type, bof_answer, tf_answers, is_correct, marks))

            conn.commit()
            cur.close()

            session["quiz_current"] = current + 1
            session.modified = True

            if session["quiz_current"] >= len(question_ids):
                return redirect(url_for("quiz.finish"))

            return redirect(url_for("quiz.question"))
        finally:
            pool = init_db_pool()
            pool.putconn(conn)
    except Exception as e:
        # Log error in production: logger.error(f"Submit answer error: {e}")
        return redirect(url_for("quiz.question"))


@quiz.route("/finish")
@login_required_custom
def finish():
    user_id = session["user_id"]
    quiz_state = _get_quiz_state()
    if not quiz_state:
        return redirect(url_for("quiz.start"))

    quiz_session_id, _, _ = quiz_state

    try:
        conn = get_db()
        try:
            cur = conn.cursor()

            cur.execute("""
                SELECT completed
                FROM sessions
                WHERE id = %s AND user_id = %s
            """, (quiz_session_id, user_id))
            sess = cur.fetchone()
            if not sess:
                cur.close()
                _clear_quiz_state()
                return redirect(url_for("quiz.start"))

            # Idempotent finish: avoid duplicate progress updates on reload/revisit.
            if sess["completed"]:
                cur.close()
                return redirect(url_for("quiz.results"))

            cur.execute("SELECT marks_obtained, is_correct FROM attempts WHERE session_id = %s", (quiz_session_id,))
            attempts = cur.fetchall()

            total_marks = sum(a["marks_obtained"] for a in attempts)
            total_possible = len(attempts)
            percentage = round((total_marks / total_possible) * 100, 2) if total_possible > 0 else 0

            cur.execute("""
                UPDATE sessions
                SET score = %s, total_score = %s, percentage = %s, completed = TRUE, completed_at = NOW()
                WHERE id = %s AND user_id = %s
            """, (total_marks, total_possible, percentage, quiz_session_id, user_id))

            # Get attempts with their sections to update progress per section
            cur.execute("""
                SELECT a.is_correct, a.marks_obtained, q.section
                FROM attempts a
                JOIN questions q ON a.question_id = q.id
                WHERE a.session_id = %s
            """, (quiz_session_id,))
            attempts_by_section = cur.fetchall()

            # Group attempts by section and update progress for each section
            from collections import defaultdict
            section_stats = defaultdict(lambda: {"total": 0, "correct": 0, "marks": 0.0})
            
            for attempt in attempts_by_section:
                section_name = attempt["section"]
                section_stats[section_name]["total"] += 1
                section_stats[section_name]["marks"] += float(attempt["marks_obtained"] or 0)
                if attempt["is_correct"]:
                    section_stats[section_name]["correct"] += 1

            # Update section_progress for each section
            for section_name, stats in section_stats.items():
                section_percentage = round((stats["marks"] / stats["total"]) * 100, 2) if stats["total"] > 0 else 0
                
                cur.execute("""
                    SELECT * FROM section_progress WHERE user_id = %s AND section = %s
                """, (user_id, section_name))
                existing = cur.fetchone()

                if existing:
                    cur.execute("""
                        UPDATE section_progress
                        SET questions_attempted = questions_attempted + %s,
                            questions_correct = questions_correct + %s,
                            best_score_percentage = GREATEST(best_score_percentage, %s),
                            last_attempted = NOW()
                        WHERE user_id = %s AND section = %s
                    """, (stats["total"], stats["correct"], section_percentage, user_id, section_name))
                else:
                    cur.execute("""
                        INSERT INTO section_progress (user_id, section, questions_attempted, questions_correct, best_score_percentage, last_attempted)
                        VALUES (%s, %s, %s, %s, %s, NOW())
                    """, (user_id, section_name, stats["total"], stats["correct"], section_percentage))

            conn.commit()
            cur.close()

            return redirect(url_for("quiz.results"))
        finally:
            pool = init_db_pool()
            pool.putconn(conn)
    except Exception as e:
        # Log error in production: logger.error(f"Quiz finish error: {e}")
        return redirect(url_for("quiz.results"))


@quiz.route("/results")
@login_required_custom
def results():
    user_id = session["user_id"]
    quiz_session_id = session.get("quiz_session_id")
    if not quiz_session_id:
        return redirect(url_for("quiz.start"))

    try:
        conn = get_db()
        try:
            cur = conn.cursor()

            session_data, attempts_list = _build_results_payload(cur, quiz_session_id, user_id)
            if not session_data:
                cur.close()
                _clear_quiz_state()
                return redirect(url_for("quiz.start"))
            if not session_data["completed"]:
                cur.close()
                return redirect(url_for("quiz.finish"))

            cur.close()
        finally:
            pool = init_db_pool()
            pool.putconn(conn)

        return render_template("results.html",
                               session_data=session_data,
                               attempts=attempts_list)
    except Exception:
        return redirect(url_for("dashboard.home"))


@quiz.route("/results/<session_id>")
@login_required_custom
def results_by_session(session_id):
    user_id = session["user_id"]

    try:
        conn = get_db()
        try:
            cur = conn.cursor()
            session_data, attempts_list = _build_results_payload(cur, session_id, user_id)
            cur.close()
        finally:
            pool = init_db_pool()
            pool.putconn(conn)

        if not session_data or not session_data["completed"]:
            return redirect(url_for("dashboard.home"))

        return render_template("results.html",
                               session_data=session_data,
                               attempts=attempts_list)
    except Exception:
        return redirect(url_for("dashboard.home"))


@quiz.route("/bookmark/<int:question_id>", methods=["POST"])
@login_required_custom
def bookmark(question_id):
    user_id = session["user_id"]

    try:
        conn = get_db()
        try:
            cur = conn.cursor()

            cur.execute("SELECT id FROM bookmarks WHERE user_id = %s AND question_id = %s", (user_id, question_id))
            existing = cur.fetchone()

            if existing:
                cur.execute("DELETE FROM bookmarks WHERE user_id = %s AND question_id = %s", (user_id, question_id))
                conn.commit()
                cur.close()
                return jsonify({"status": "removed", "question_id": question_id})
            else:
                cur.execute("SELECT id FROM questions WHERE id = %s", (question_id,))
                if not cur.fetchone():
                    cur.close()
                    return jsonify({"status": "error", "message": "Question not found"}), 404
                cur.execute("INSERT INTO bookmarks (user_id, question_id) VALUES (%s, %s)", (user_id, question_id))
                conn.commit()
                cur.close()
                return jsonify({"status": "added", "question_id": question_id})
        finally:
            pool = init_db_pool()
            pool.putconn(conn)
    except Exception as e:
        # Log error in production: logger.error(f"Bookmark error: {e}")
        return jsonify({"status": "error", "message": "An error occurred"}), 500


@quiz.route("/bookmarks")
@login_required_custom
def bookmarks():
    user_id = session["user_id"]

    try:
        conn = get_db()
        try:
            cur = conn.cursor()
            cur.execute("""
                SELECT b.id AS bookmark_id, b.question_id, q.question_text, q.question_type, q.section, q.explanation
                FROM bookmarks b
                JOIN questions q ON q.id = b.question_id
                WHERE b.user_id = %s
                ORDER BY b.id DESC
            """, (user_id,))
            bookmarks_data = cur.fetchall()

            bookmarks_list = []
            for row in bookmarks_data:
                item = dict(row)
                question_id = item["question_id"]
                item["explanation_formatted"] = _format_explanation_text(item.get("explanation"))

                cur.execute("""
                    SELECT a.bof_answer, a.tf_answers, a.is_correct, a.marks_obtained
                    FROM attempts a
                    JOIN sessions s ON s.id = a.session_id
                    WHERE s.user_id = %s AND a.question_id = %s
                    ORDER BY a.id DESC
                    LIMIT 1
                """, (user_id, question_id))
                last_attempt = cur.fetchone()
                item["last_attempt"] = dict(last_attempt) if last_attempt else None

                if item["question_type"] == "BOF":
                    cur.execute("""
                        SELECT option_label, option_text, is_correct
                        FROM options
                        WHERE question_id = %s
                        ORDER BY option_label
                    """, (question_id,))
                    item["bof_options"] = cur.fetchall()
                    item["tf_statements"] = []
                else:
                    cur.execute("""
                        SELECT statement_number, statement_text, is_true
                        FROM tf_statements
                        WHERE question_id = %s
                        ORDER BY statement_number
                    """, (question_id,))
                    item["tf_statements"] = cur.fetchall()
                    item["bof_options"] = []

                bookmarks_list.append(item)
            cur.close()
        finally:
            pool = init_db_pool()
            pool.putconn(conn)

        return render_template("bookmarks.html", bookmarks=bookmarks_list)
    except Exception:
        return redirect(url_for("dashboard.home"))
