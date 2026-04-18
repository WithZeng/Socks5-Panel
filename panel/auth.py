from functools import wraps

from flask import current_app, flash, redirect, request, session, url_for


def is_logged_in() -> bool:
    return bool(session.get("is_admin_authenticated"))


def authenticate(username: str, password: str) -> bool:
    expected_username = current_app.config["ADMIN_USERNAME"]
    expected_password = current_app.config["ADMIN_PASSWORD"]
    return username == expected_username and password == expected_password


def login_required(view_func):
    @wraps(view_func)
    def wrapped_view(*args, **kwargs):
        if not is_logged_in():
            flash("请先使用管理员账号登录。", "warning")
            return redirect(url_for("login", next=request.path))
        return view_func(*args, **kwargs)

    return wrapped_view
