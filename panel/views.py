from flask import (
    Response,
    current_app,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

from .auth import authenticate, is_logged_in, login_required
from .models import ConversionBatch, RelayServer, db
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
    get_country_groups,
    get_country_profile,
    get_dashboard_stats,
    persist_conversion,
    sync_payload_render_fields,
)
from .zero_client import ZeroAPIError, ZeroClient
from .zero_service import (
    attach_zero_sync_to_records,
    build_zero_batch_status,
    create_ports_for_payload,
    summarize_forward_endpoints,
    sync_lines_into_relay_servers,
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
            "zero_dry_run": current_app.config["ZERO_DRY_RUN"],
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
        forward_endpoints = []
        zero_health = None

        if has_zero_config():
            try:
                forward_endpoints = fetch_forward_endpoints()
                zero_health = get_zero_health_payload()
            except ZeroAPIError:
                zero_health = {"ok": False, "error": "Zero API unavailable"}

        return render_template(
            "dashboard.html",
            relays=relays,
            stats=get_dashboard_stats(),
            country_groups=get_country_groups(),
            recent_batches=recent_batches,
            active_tab=request.args.get("tab", "text"),
            current_batch=None,
            default_remark_prefix=build_country_remark_prefix(""),
            zero_health=zero_health,
            forward_endpoints=forward_endpoints,
            default_forward_endpoint_ids=current_app.config["ZERO_DEFAULT_FORWARD_ENDPOINT_IDS"],
            default_chain_fixed_hops_num=current_app.config["ZERO_DEFAULT_CHAIN_FIXED_HOPS_NUM"],
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
        sync_to_zero = request.form.get("sync_to_zero") == "on"
        chain_fixed_hops_num = request.form.get("chain_fixed_hops_num", type=int) or current_app.config[
            "ZERO_DEFAULT_CHAIN_FIXED_HOPS_NUM"
        ]
        enable_udp = request.form.get("enable_udp") == "on"
        forward_endpoint_ids = request.form.getlist("forward_endpoint_ids")
        selected_forward_endpoint_ids = [int(item) for item in forward_endpoint_ids if item.isdigit()]

        if not relay_id:
            flash("请选择中转服务器。", "danger")
            return redirect(url_for("dashboard", tab=source_type))

        relay_server = RelayServer.query.get_or_404(relay_id)
        if not relay_server.is_active:
            flash("当前中转服务器已停用，请更换后再试。", "danger")
            return redirect(url_for("dashboard", tab=source_type))

        if not country:
            flash("请输入国家或地区。", "danger")
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
                    raise ConversionError("请先粘贴原始代理内容。")
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

            if sync_to_zero:
                if not has_zero_config():
                    raise ConversionError("Zero API 尚未配置，无法同步。")
                if not relay_server.zero_line_id:
                    raise ConversionError("当前中转服务器未绑定 Zero line，请先同步线路。")

                client = get_zero_client()
                effective_forward_endpoint_ids = (
                    selected_forward_endpoint_ids or current_app.config["ZERO_DEFAULT_FORWARD_ENDPOINT_IDS"]
                )
                results = create_ports_for_payload(
                    client,
                    payload,
                    forward_endpoint_ids=effective_forward_endpoint_ids,
                    chain_fixed_hops_num=chain_fixed_hops_num,
                    enable_udp=enable_udp,
                )
                attach_zero_sync_to_records(payload, results)
                sync_payload_render_fields(payload)
                payload.zero_summary = {
                    "enabled": True,
                    "ok": sum(1 for item in results if item.ok),
                    "failed": sum(1 for item in results if not item.ok),
                    "dry_run": any(item.dry_run for item in results),
                }

            batch = persist_conversion(payload)
        except ConversionError as exc:
            flash(str(exc), "danger")
            return redirect(url_for("dashboard", tab=source_type))
        except ZeroAPIError as exc:
            flash(f"Zero 同步失败: {exc}", "danger")
            return redirect(url_for("dashboard", tab=source_type))
        except Exception as exc:  # pragma: no cover
            flash(f"转换失败，请检查输入内容。错误信息: {exc}", "danger")
            return redirect(url_for("dashboard", tab=source_type))

        if payload.errors:
            flash(f"转换完成，跳过 {len(payload.errors)} 行无法识别的数据。", "warning")
        else:
            flash("转换成功，结果已保存到历史记录。", "success")

        if payload.zero_summary.get("enabled"):
            summary = payload.zero_summary
            if summary["dry_run"]:
                flash(f"Zero 演练模式：已模拟同步 {summary['ok']}/{payload.success_count} 条。", "warning")
            elif summary["failed"]:
                flash(f"Zero 已同步 {summary['ok']}/{payload.success_count} 条，失败 {summary['failed']} 条。", "warning")
            else:
                flash(f"已同步 {summary['ok']}/{payload.success_count} 条到 Zero 面板。", "success")

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
            flash("请完整填写名称、地址和端口范围。", "danger")
            return redirect(url_for("relay_list"))

        if port_range_start >= port_range_end:
            flash("端口起始值必须小于结束值。", "danger")
            return redirect(url_for("relay_list"))

        existing = RelayServer.query.filter(RelayServer.name == name).first()
        if existing and existing.id != relay_id:
            flash("中转服务器名称已存在，请更换名称。", "danger")
            return redirect(url_for("relay_list"))

        relay = RelayServer.query.get(relay_id) if relay_id else RelayServer()
        if relay.zero_line_id:
            relay.notes = notes
        else:
            relay.name = name
            relay.host = host
            relay.port_range_start = port_range_start
            relay.port_range_end = port_range_end
            relay.notes = notes
            relay.is_active = True

        if not relay_id:
            db.session.add(relay)

        db.session.commit()
        flash("中转服务器已保存。", "success")
        return redirect(url_for("relay_list"))

    @app.post("/relays/<int:relay_id>/toggle")
    @login_required
    def relay_toggle(relay_id: int):
        relay = RelayServer.query.get_or_404(relay_id)
        relay.is_active = not relay.is_active
        db.session.commit()
        flash("中转服务器状态已更新。", "success")
        return redirect(url_for("relay_list"))

    @app.post("/relays/sync")
    @login_required
    def relay_sync():
        if not has_zero_config():
            flash("Zero API 尚未配置。", "danger")
            return redirect(url_for("relay_list"))

        try:
            result = sync_lines_into_relay_servers(get_zero_client())
        except ZeroAPIError as exc:
            flash(f"同步 Zero 线路失败: {exc}", "danger")
            return redirect(url_for("relay_list"))

        flash(
            f"Zero 线路同步完成：新增 {result['created']}，更新 {result['updated']}，停用 {result['disabled']}。",
            "success",
        )
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
        return render_template(
            "batch_detail.html",
            batch=batch,
            zero_status=build_zero_batch_status(list(batch.records)),
        )

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

    @app.get("/api/zero/health")
    @login_required
    def zero_health():
        if not has_zero_config():
            return jsonify({"ok": False, "error": "missing_config"})

        try:
            return jsonify(get_zero_health_payload())
        except ZeroAPIError as exc:
            return jsonify({"ok": False, "error": str(exc)}), 502

    @app.get("/api/zero/forward-endpoints")
    @login_required
    def zero_forward_endpoints():
        if not has_zero_config():
            return jsonify({"items": []})

        try:
            items = fetch_forward_endpoints()
        except ZeroAPIError as exc:
            return jsonify({"items": [], "error": str(exc)}), 502
        return jsonify({"items": items})


def has_zero_config() -> bool:
    config = current_app.config
    return bool(config.get("ZERO_API_BASE") and config.get("ZERO_API_KEY"))


def get_zero_client() -> ZeroClient:
    config = current_app.config
    return ZeroClient(
        base_url=config["ZERO_API_BASE"],
        api_key=config["ZERO_API_KEY"],
        timeout=config["ZERO_API_TIMEOUT"],
        dry_run=config["ZERO_DRY_RUN"],
    )


def get_zero_health_payload() -> dict:
    data, _ = get_zero_client().get_subscription()
    lines = data.get("lines") or []
    return {
        "ok": True,
        "subscription_valid_until": data.get("valid_until") or data.get("expired_at") or "",
        "lines_count": len(lines),
        "is_admin": data.get("is_admin"),
        "dry_run": current_app.config["ZERO_DRY_RUN"],
    }


def fetch_forward_endpoints() -> list[dict]:
    data, _ = get_zero_client().list_forward_endpoints()
    raw_items = data if isinstance(data, list) else data.get("items") or data.get("data") or []
    return summarize_forward_endpoints(raw_items)
