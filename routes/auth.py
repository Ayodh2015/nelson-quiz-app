from flask import Blueprint, render_template, request, redirect, url_for, flash, session
from config import get_db
import bcrypt
import uuid

auth = Blueprint("auth", __name__)

@auth.route("/")
@auth.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email").strip().lower()
        password = request.form.get("password")

        conn = get_db()
        cur = conn.cursor()
        cur.execute("SELECT * FROM users WHERE email = %s", (email,))
        user = cur.fetchone()
        cur.close()
        conn.close()

        if user:
            if bcrypt.checkpw(password.encode("utf-8"), user["password_hash"].encode("utf-8")):
                session["user_id"] = user["id"]
                session["username"] = user["username"]
                conn = get_db()
                cur = conn.cursor()
                cur.execute("UPDATE users SET last_login = NOW() WHERE id = %s", (user["id"],))
                conn.commit()
                cur.close()
                conn.close()
                return redirect(url_for("dashboard.home"))
            else:
                flash("Incorrect password. Please try again.", "danger")
        else:
            flash("No account found with that email.", "danger")

    return render_template("login.html")


@auth.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username = request.form.get("username").strip()
        email = request.form.get("email").strip().lower()
        password = request.form.get("password")
        confirm = request.form.get("confirm_password")

        if password != confirm:
            flash("Passwords do not match.", "danger")
            return render_template("register.html")

        conn = get_db()
        cur = conn.cursor()

        cur.execute("SELECT id FROM users WHERE email = %s", (email,))
        existing = cur.fetchone()

        if existing:
            flash("Email already registered. Please login.", "warning")
            cur.close()
            conn.close()
            return redirect(url_for("auth.login"))

        hashed = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
        user_id = str(uuid.uuid4())

        cur.execute(
            "INSERT INTO users (id, username, email, password_hash) VALUES (%s, %s, %s, %s)",
            (user_id, username, email, hashed)
        )
        conn.commit()
        cur.close()
        conn.close()

        flash("Account created successfully! Please login.", "success")
        return redirect(url_for("auth.login"))

    return render_template("register.html")


@auth.route("/logout")
def logout():
    session.clear()
    flash("You have been logged out.", "info")
    return redirect(url_for("auth.login"))
