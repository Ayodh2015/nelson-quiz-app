from flask import Blueprint, render_template, request, redirect, url_for, flash, session
from flask_login import login_user, logout_user, login_required
from config import supabase
import bcrypt
import uuid

auth = Blueprint("auth", __name__)

@auth.route("/")
@auth.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email").strip().lower()
        password = request.form.get("password")

        # Fetch user from Supabase
        result = supabase.table("users").select("*").eq("email", email).execute()

        if result.data:
            user = result.data[0]
            if bcrypt.checkpw(password.encode("utf-8"), user["password_hash"].encode("utf-8")):
                session["user_id"] = user["id"]
                session["username"] = user["username"]
                # Update last login
                supabase.table("users").update({"last_login": "now()"}).eq("id", user["id"]).execute()
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

        # Check if email already exists
        existing = supabase.table("users").select("id").eq("email", email).execute()
        if existing.data:
            flash("Email already registered. Please login.", "warning")
            return redirect(url_for("auth.login"))

        # Hash password
        hashed = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")

        # Insert user
        new_user = {
            "id": str(uuid.uuid4()),
            "username": username,
            "email": email,
            "password_hash": hashed
        }
        supabase.table("users").insert(new_user).execute()

        flash("Account created successfully! Please login.", "success")
        return redirect(url_for("auth.login"))

    return render_template("register.html")


@auth.route("/logout")
def logout():
    session.clear()
    flash("You have been logged out.", "info")
    return redirect(url_for("auth.login"))
