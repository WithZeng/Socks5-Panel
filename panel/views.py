from flask import (
    Response,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

from .auth import authenticate, is_logged_in, login_required
from .models import ConversionBatch, RelayServer
from .services import (
    COMMON_COUNTRIES,
    ConversionError,
    build_conversion_payload,
    build_country_remark_prefix,
    build_excel_bytes,
    build_excel_rows_from_batch,
    extract_lines_from_excel,
    extract_lines_from_text,
    find_next_available_start_port,
    get_country_profile,
    get_country_groups,
    get_dashboard_stats,
    persist_conversion,
)


def register_routes(app):
    @app.template_filter("datetime_cn")
    def datetime_cn(value):
        if not value:
            return "-"
        return value.strftime("%Y-%m-%d %H:%M:%S")

    @app.context_processor
    def inject_globals():
        return {
            "admin_logged_in": is_logged_in(),
            "common_countries": COMMON_COUNTRIES,
        }

    @app.get("/health")
    def health():
        return {"status": "ok"}

    @app.route("/login", methods=["GET", "POST"])
    def login():
        if is_logged_in():
            return redirect(url_for("dashboard"))

        if request.method == "POST":
            username = request.form.get("username", "").strip()
            password = request.form.get("password", "")
            if authenticate(username, password):
                session.clear()
                session["is_admin_authenticated"] = True
                session["admin_username"] = username
                flash("登录成功。", "success")
                next_url = request.args.get("next")
                return redirect(next_url or url_for("dashboard"))

            flash("管理员账号或密码错误。", "danger")

        return render_template("login.html")

    @app.post("/logout")
    @login_required
    def logout():
        session.clear()
        flash("已退出登录。", "success")
        return redirect(url_for("login"))

    @app.get("/")
    @login_required
    def dashboard():
        relays = RelayServer.query.order_by(RelayServer.is_active.desc(), RelayServer.updated_at.desc()).all()
        recent_batches = ConversionBatch.query.order_by(ConversionBatch.created_at.desc()).limit(8).all()
        return render_template(
            "dashboard.html",
            relays=relays,
            stats=get_dashboard_stats(),
            country_groups=get_country_groups(),
            recent_batches=recent_batches,
            active_tab=request.args.get("tab", "text"),
            current_batch=None,
            default_remark_prefix=build_country_remark_prefix(""),
        )

    @app.post("/convert")
    @login_required
    def convert():
        relay_id = request.form.get("relay_server_id", type=int)
        source_type = request.form.get("source_type", "text").strip() or "text"
        country = request.form.get("country", "").strip()
        remark_prefix = request.form.get("remark_prefix", "").strip()
        remark_start = request.form.get("remark_start", type=int) or 1
        manual_start_port = request.form.get("start_port", type=int)

        if not relay_id:
            flash("请选择中转服务器备选项。", "danger")
            return redirect(url_for("dashboard", tab=source_type))

        relay_server = RelayServer.query.get_or_404(relay_id)
        if not relay_server.is_active:
            flash("当前中转服务器已停用，请启用后再使用。", "danger")
            return redirect(url_for("dashboard", tab=source_type))

        if not country:
            flash("请输入国家或地区，用于后续分组管理。", "danger")
            return redirect(url_for("dashboard", tab=source_type))

        try:
            if source_type == "excel":
                uploaded_file = request.files.get("excel_file")
                if not uploaded_file or not uploaded_file.filename:
                    raise ConversionError("请先上传 Excel 文件。")
                lines = extract_lines_from_excel(uploaded_file)
            else:
                raw_text = request.form.get("raw_text", "")
                if not raw_text.strip():
                    raise ConversionError("请先粘贴原始 IP 内容。")
                lines = extract_lines_from_text(raw_text)

            payload = build_conversion_payload(
                source_type=source_type,
                lines=lines,
                relay_server=relay_server,
                country=country,
                remark_prefix=remark_prefix,
                remark_start=remark_start,
                manual_start_port=manual_start_port,
            )
            batch = persist_conversion(payload)
        except ConversionError as exc:
            flash(str(exc), "danger")
            return redirect(url_for("dashboard", tab=source_type))
        except Exception as exc:  # pragma: no cover - defensive fallback
            flash(f"转换失败，请检查输入内容。错误信息: {exc}", "danger")
            return redirect(url_for("dashboard", tab=source_type))

        if payload.errors:
            flash(f"已完成转换，跳过 {len(payload.errors)} 行无法识别的数据。", "warning")
        else:
            flash("转换成功，结果已保存到历史记录。", "success")

        return redirect(url_for("batch_detail", batch_code=batch.batch_code))

    @app.get("/relays")
    @login_required
    def relay_list():
        relays = RelayServer.query.order_by(RelayServer.is_active.desc(), RelayServer.updated_at.desc()).all()
        edit_id = request.args.get("edit", type=int)
        relay_to_edit = RelayServer.query.get(edit_id) if edit_id else None
        return render_template("relays.html", relays=relays, relay_to_edit=relay_to_edit)

    @app.post("/relays/save")
    @login_required
    def relay_save():
        relay_id = request.form.get("relay_id", type=int)
        name = request.form.get("name", "").strip()
        host = request.form.get("host", "").strip()
        port_range_start = request.form.get("port_range_start", type=int)
        port_range_end = request.form.get("port_range_end", type=int)
        notes = request.form.get("notes", "").strip()

        if not all([name, host, port_range_start, port_range_end]):
            flash("请完整填写中转服务器名称、地址和端口范围。", "danger")
            return redirect(url_for("relay_list"))

        if port_range_start >= port_range_end:
            flash("端口范围起始值必须小于结束值。", "danger")
            return redirect(url_for("relay_list"))

        existing = RelayServer.query.filter(RelayServer.name == name).first()
        if existing and existing.id != relay_id:
            flash("中转服务器名称已存在，请换一个名称。", "danger")
            return redirect(url_for("relay_list"))

        relay = RelayServer.query.get(relay_id) if relay_id else RelayServer()
        relay.name = name
        relay.host = host
        relay.port_range_start = port_range_start
        relay.port_range_end = port_range_end
        relay.notes = notes
        relay.is_active = True

        if not relay_id:
            from .models import db

            db.session.add(relay)

        from .models import db

        db.session.commit()
        flash("中转服务器备选项已保存。", "success")
        return redirect(url_for("relay_list"))

    @app.post("/relays/<int:relay_id>/toggle")
    @login_required
    def relay_toggle(relay_id: int):
        relay = RelayServer.query.get_or_404(relay_id)
        relay.is_active = not relay.is_active

        from .models import db

        db.session.commit()
        flash("中转服务器状态已更新。", "success")
        return redirect(url_for("relay_list"))

    @app.get("/history")
    @login_required
    def history():
        country_filter = request.args.get("country", "").strip()
        relay_filter = request.args.get("relay_id", type=int)

        query = ConversionBatch.query.order_by(ConversionBatch.created_at.desc())
        if country_filter:
            query = query.filter(ConversionBatch.country == country_filter)
        if relay_filter:
            query = query.filter(ConversionBatch.relay_server_id == relay_filter)

        batches = query.limit(100).all()
        relays = RelayServer.query.order_by(RelayServer.name.asc()).all()
        countries = [country for country, in ConversionBatch.query.with_entities(ConversionBatch.country).distinct().all()]

        return render_template(
            "history.html",
            batches=batches,
            relays=relays,
            countries=countries,
            selected_country=country_filter,
            selected_relay_id=relay_filter,
        )

    @app.get("/history/<batch_code>")
    @login_required
    def batch_detail(batch_code: str):
        batch = ConversionBatch.query.filter_by(batch_code=batch_code).first_or_404()
        return render_template("batch_detail.html", batch=batch)

    @app.get("/history/<batch_code>/download/json")
    @login_required
    def download_json(batch_code: str):
        batch = ConversionBatch.query.filter_by(batch_code=batch_code).first_or_404()
        return Response(
            batch.result_json,
            headers={
                "Content-Disposition": f'attachment; filename="{batch.batch_code}.json"',
                "Content-Type": "application/json; charset=utf-8",
            },
        )

    @app.get("/history/<batch_code>/download/excel")
    @login_required
    def download_excel(batch_code: str):
        batch = ConversionBatch.query.filter_by(batch_code=batch_code).first_or_404()
        excel_rows = build_excel_rows_from_batch(batch)
        payload = build_excel_bytes(excel_rows)
        return Response(
            payload,
            headers={
                "Content-Disposition": f'attachment; filename="{batch.batch_code}.xlsx"',
                "Content-Type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            },
        )

    @app.get("/api/relays/<int:relay_id>/next-port")
    @login_required
    def relay_next_port(relay_id: int):
        relay = RelayServer.query.get_or_404(relay_id)
        count = request.args.get("count", default=1, type=int) or 1
        next_port = find_next_available_start_port(relay, required_count=count)
        return jsonify(
            {
                "relayId": relay.id,
                "nextPort": next_port,
                "rangeStart": relay.port_range_start,
                "rangeEnd": relay.port_range_end,
                "hasCapacity": next_port is not None,
            }
        )

    @app.get("/api/countries/profile")
    @login_required
    def country_profile():
        country = request.args.get("country", "").strip()
        return jsonify(get_country_profile(country))
