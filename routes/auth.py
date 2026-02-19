from flask import Blueprint, render_template, request, redirect, url_for, flash, session, current_app
from config import get_db_connection
import bcrypt
import uuid

auth = Blueprint("auth", __name__)

@auth.route("/")
@auth.route("/login", methods=["GET", "POST"])
def login():
    if session.get("user_id"):
        return redirect(url_for("dashboard.home"))
    if request.method == "POST":
        email = (request.form.get("email") or "").strip().lower()
        password = request.form.get("password") or ""

        if not email or not password:
            flash("Please enter both email and password.", "danger")
            return render_template("login.html")

        try:
            with get_db_connection() as conn:
                cur = conn.cursor()
                cur.execute("SELECT * FROM users WHERE email = %s", (email,))
                user = cur.fetchone()
                cur.close()

                if user:
                    pwd_hash = user["password_hash"]
                    pwd_bytes = pwd_hash.encode("utf-8") if isinstance(pwd_hash, str) else pwd_hash
                    if bcrypt.checkpw(password.encode("utf-8"), pwd_bytes):
                        session["user_id"] = user["id"]
                        session["username"] = user["username"]
                        cur = conn.cursor()
                        cur.execute("UPDATE users SET last_login = NOW() WHERE id = %s", (user["id"],))
                        conn.commit()
                        cur.close()
                        return redirect(url_for("dashboard.home"))
                    else:
                        flash("Incorrect password. Please try again.", "danger")
                else:
                    flash("No account found with that email.", "danger")
        except Exception as e:
            flash("An error occurred. Please try again.", "danger")
            # Log error in production: logger.error(f"Login error: {e}")

    return render_template("login.html")


@auth.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username = (request.form.get("username") or "").strip()
        email = (request.form.get("email") or "").strip().lower()
        password = request.form.get("password") or ""
        confirm = request.form.get("confirm_password") or ""

        if not username or not email or not password:
            flash("Please fill in all required fields.", "danger")
            return render_template("register.html")

        if password != confirm:
            flash("Passwords do not match.", "danger")
            return render_template("register.html")

        try:
            with get_db_connection() as conn:
                cur = conn.cursor()

                cur.execute("SELECT id FROM users WHERE email = %s", (email,))
                existing = cur.fetchone()

                if existing:
                    flash("Email already registered. Please login.", "warning")
                    return redirect(url_for("auth.login"))

                hashed = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
                user_id = str(uuid.uuid4())

                cur.execute(
                    "INSERT INTO users (id, username, email, password_hash) VALUES (%s, %s, %s, %s)",
                    (user_id, username, email, hashed)
                )
                conn.commit()
                cur.close()

            flash("Account created successfully! Please login.", "success")
            return redirect(url_for("auth.login"))
        except Exception as e:
            current_app.logger.exception("Registration error: %s", e)
            msg = "An error occurred during registration. Please try again."
            if current_app.debug:
                msg += f" ({type(e).__name__}: {e})"
            flash(msg, "danger")

    return render_template("register.html")


@auth.route("/logout", methods=["GET", "POST"])
def logout():
    session.clear()
    flash("You have been logged out.", "info")
    resp = redirect(url_for("auth.login"))
    resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    return resp
