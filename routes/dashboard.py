from flask import Blueprint, render_template, session, redirect, url_for, abort, request
from config import get_db, init_db_pool
from functools import wraps
from collections import defaultdict
import os
import re

dashboard = Blueprint("dashboard", __name__)
STUDY_DIR = "v22"
TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)
TITLE_PREFIX_RE = re.compile(
    r"^\s*(Nelson Pediatrics|Postgraduate Pead MSQ Exam Help Tool)\s*[—-]\s*",
    re.IGNORECASE
)
STUDY_BRAND_REPLACEMENTS = (
    ("Nelson Pediatrics — ", "Postgraduate Pead MSQ Exam Help Tool — "),
    ("Nelson Textbook of Pediatrics · 22nd Edition · 2024", "Postgraduate Pead MSQ Exam Help Tool"),
    ("Nelson Textbook of Pediatrics · 22nd Ed. · 2024", "Postgraduate Pead MSQ Exam Help Tool"),
)

def login_required_custom(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user_id" not in session:
            return redirect(url_for("auth.login"))
        return f(*args, **kwargs)
    return decorated


def _get_study_pages():
    template_root = os.path.join(dashboard.root_path, "..", "templates", STUDY_DIR)
    pages = []

    if not os.path.isdir(template_root):
        return pages

    for fname in os.listdir(template_root):
        if not fname.lower().endswith(".html"):
            continue

        slug = os.path.splitext(fname)[0]
        file_path = os.path.join(template_root, fname)

        label = ""
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                title_match = TITLE_RE.search(f.read())
                if title_match:
                    # Normalize whitespace to keep hub card labels clean.
                    label = " ".join(title_match.group(1).split())
                    label = TITLE_PREFIX_RE.sub("", label).strip()
        except OSError:
            pass

        if not label:
            label_base = slug.replace("_", " ").strip()
            label_base = re.sub(r"([A-Za-z])(\d)", r"\1 \2", label_base)
            label = label_base.title()

        num_match = re.search(r"\d+", slug)
        sort_num = int(num_match.group(0)) if num_match else 10**9

        pages.append({
            "slug": slug,
            "filename": fname,
            "label": label,
            "sort_num": sort_num
        })

    pages.sort(key=lambda p: (p["sort_num"], p["label"]))
    return pages


def _apply_study_page_overrides(html):
    favicon_link = """
<link rel="icon" type="image/svg+xml" href="/static/favicon-go.svg">
<link rel="shortcut icon" href="/static/favicon-go.svg">
"""
    override_css = """
<style id="study-overrides">
  :root {
    --bg: #0a1628 !important;
    --surface: #112240 !important;
    --surface2: #1a3a6b !important;
    --border: rgba(79, 195, 247, 0.15) !important;
    --accent: #4fc3f7 !important;
    --accent2: #26c6a2 !important;
    --accent3: #f4c542 !important;
    --danger: #ef5350 !important;
    --text: #e8edf5 !important;
    --text-muted: #8899bb !important;
    --text-dim: #6f84a6 !important;
  }

  body {
    background: var(--bg) !important;
    color: var(--text) !important;
    background-image:
      radial-gradient(ellipse at 20% 20%, rgba(26,58,107,0.4) 0%, transparent 60%),
      radial-gradient(ellipse at 80% 80%, rgba(38,198,162,0.08) 0%, transparent 50%) !important;
  }

  /* Hide search UI on all study pages */
  .search-bar,
  .search-inner,
  .search-input,
  .chapter-count {
    display: none !important;
  }
</style>
"""
    if 'rel="icon"' not in html and "rel='icon'" not in html:
        if "</head>" in html:
            html = html.replace("</head>", f"{favicon_link}\n</head>", 1)
        else:
            html = f"{favicon_link}\n{html}"

    if "</head>" in html:
        return html.replace("</head>", f"{override_css}\n</head>", 1)
    return f"{override_css}\n{html}"


def _sanitize_study_branding(html):
    cleaned = html
    for old, new in STUDY_BRAND_REPLACEMENTS:
        cleaned = cleaned.replace(old, new)
    return cleaned

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
            raw_sessions = cur.fetchall()

            # Section progress
            cur.execute("""
                SELECT a.session_id, a.question_id, q.section, a.is_correct, a.marks_obtained, s.completed_at
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
            cur.execute("""
                SELECT section, COUNT(*) AS question_count
                FROM questions
                GROUP BY section
            """)
            section_counts_rows = cur.fetchall()
            cur.execute("SELECT COUNT(*) AS total_questions FROM questions")
            total_bank_questions = int(cur.fetchone()["total_questions"] or 0)

            # Get all attempts across all completed sessions for detailed stats
            cur.execute("""
                SELECT a.question_id, a.is_correct, a.marks_obtained, a.question_type
                FROM attempts a
                JOIN sessions s ON a.session_id = s.id
                WHERE s.user_id = %s AND s.completed = TRUE
            """, (user_id,))
            all_attempts = cur.fetchall()

            cur.close()
        finally:
            pool = init_db_pool()
            pool.putconn(conn)

        sessions_data = []
        for s in raw_sessions:
            row = dict(s)
            pct = float(row["percentage"] or 0)
            completed_at = row["completed_at"]
            if completed_at and hasattr(completed_at, "strftime"):
                completed_date = completed_at.strftime("%Y-%m-%d")
            elif completed_at:
                completed_date = str(completed_at)[:10]
            else:
                completed_date = "-"
            row["percentage_value"] = pct
            row["completed_date"] = completed_date
            sessions_data.append(row)

        # Build section progress from all completed attempts so dashboard stays correct
        # even if section_progress table is stale/missing older updates.
        section_totals = defaultdict(lambda: {
            "section": "",
            "questions_attempted": 0,
            "unique_questions_covered": 0,
            "questions_correct": 0,
            "average_score_percentage": 0.0,
            "last_attempted": None
        })
        section_unique_questions = defaultdict(set)
        section_marks_sum = defaultdict(float)

        for row in progress_attempt_rows:
            section = row["section"]
            marks = float(row["marks_obtained"] or 0)

            section_totals[section]["section"] = section
            section_totals[section]["questions_attempted"] += 1
            section_unique_questions[section].add(row["question_id"])
            section_marks_sum[section] += marks
            if row["is_correct"]:
                section_totals[section]["questions_correct"] += 1

            completed_at = row["completed_at"]
            if completed_at and (
                section_totals[section]["last_attempted"] is None
                or completed_at > section_totals[section]["last_attempted"]
            ):
                section_totals[section]["last_attempted"] = completed_at

        for section, seen_ids in section_unique_questions.items():
            section_totals[section]["unique_questions_covered"] = len(seen_ids)
            attempts = section_totals[section]["questions_attempted"]
            avg_pct = round((section_marks_sum[section] / attempts) * 100, 2) if attempts else 0
            section_totals[section]["average_score_percentage"] = avg_pct

        progress = list(section_totals.values())
        progress_map = {p["section"]: p for p in progress}
        section_question_counts = {r["section"]: int(r["question_count"]) for r in section_counts_rows}

        # Calculate basic stats
        percentages = [s["percentage_value"] for s in sessions_data]
        avg_score = round(sum(percentages) / len(percentages), 1) if percentages else 0
        best_score = max(percentages, default=0)
        last_attempt_score = sessions_data[0]["percentage_value"] if sessions_data else 0

        # Calculate detailed performance stats
        total_attempts = len(all_attempts)
        total_correct = sum(1 for a in all_attempts if a["is_correct"])
        total_wrong = total_attempts - total_correct
        total_marks = sum(float(a["marks_obtained"] or 0) for a in all_attempts)
        unique_questions_covered = len({a["question_id"] for a in all_attempts})
        overall_coverage_pct = round((unique_questions_covered / total_bank_questions) * 100, 1) if total_bank_questions > 0 else 0

        # BOF vs T/F breakdown
        bof_attempts = [a for a in all_attempts if a["question_type"] == "BOF"]
        tf_attempts = [a for a in all_attempts if a["question_type"] == "TF"]
        bof_correct = sum(1 for a in bof_attempts if a["is_correct"])
        tf_points = round(sum(float(a["marks_obtained"] or 0) for a in tf_attempts), 1)

        stats = {
            "total_sessions": len(sessions_data),
            "avg_score": avg_score,
            "best_score": best_score,
            "last_attempt_score": last_attempt_score,
            "bookmarks_count": bookmarks_count,
            "total_questions": total_attempts,
            "total_attempts": total_attempts,
            "total_correct": total_correct,
            "total_wrong": total_wrong,
            "total_marks": round(total_marks, 1),
            "bof_total": len(bof_attempts),
            "bof_correct": bof_correct,
            "tf_total": len(tf_attempts),
            "tf_points": tf_points,
            "unique_questions_covered": unique_questions_covered,
            "total_bank_questions": total_bank_questions,
            "overall_coverage_pct": overall_coverage_pct
        }

        return render_template("dashboard.html",
                               sessions=sessions_data,
                               progress=progress,
                               progress_map=progress_map,
                               section_question_counts=section_question_counts,
                               sections=sections,
                               stats=stats)
    except Exception:
        return render_template("dashboard.html",
                               sessions=[],
                               progress=[],
                               progress_map={},
                               section_question_counts={},
                               sections=[],
                               stats={
                                   "total_sessions": 0, "avg_score": 0, "best_score": 0, "last_attempt_score": 0, "bookmarks_count": 0,
                                   "total_questions": 0, "total_attempts": 0, "total_correct": 0, "total_wrong": 0, "total_marks": 0,
                                   "bof_total": 0, "bof_correct": 0, "tf_total": 0, "tf_points": 0,
                                   "unique_questions_covered": 0, "total_bank_questions": 0, "overall_coverage_pct": 0
                               })


@dashboard.route("/study", methods=["GET", "POST"])
@login_required_custom
def study():
    pages = _get_study_pages()
    pages_by_slug = {p["slug"]: p for p in pages}

    selected_slug = None
    if request.method == "POST":
        selected_slug = (request.form.get("slug") or "").strip()
    else:
        selected_slug = session.pop("study_slug", None)

    if selected_slug:
        page = pages_by_slug.get(selected_slug)
        if not page:
            abort(404)
        html = render_template(f"{STUDY_DIR}/{page['filename']}")
        html = _sanitize_study_branding(html)
        return _apply_study_page_overrides(html)

    return render_template("study_index.html", pages=pages)


@dashboard.route("/study/<slug>")
@login_required_custom
def study_page(slug):
    pages = _get_study_pages()
    page = next((p for p in pages if p["slug"] == slug), None)
    if not page:
        abort(404)

    # Preserve old deep links but normalize to /study URL.
    session["study_slug"] = slug
    return redirect(url_for("dashboard.study"))
