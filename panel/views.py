import json

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
from .models import AppSetting, ConversionBatch, RelayServer, ZeroPreset, db
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
    reconcile_batch,
    retry_failed_records,
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
            "zero_dry_run": get_zero_runtime_config()["dry_run"],
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
            default_forward_endpoint_ids=get_zero_runtime_config()["default_forward_endpoint_ids"],
            default_chain_fixed_hops_num=get_zero_runtime_config()["default_chain_fixed_hops_num"],
            zero_presets=ZeroPreset.query.order_by(ZeroPreset.is_default.desc(), ZeroPreset.name.asc()).all(),
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
        preset_id = request.form.get("preset_id", type=int)
        chain_fixed_hops_num = request.form.get("chain_fixed_hops_num", type=int) or get_zero_runtime_config()["default_chain_fixed_hops_num"]
        forward_chain_fixed_last_hops_num = request.form.get("forward_chain_fixed_last_hops_num", type=int) or 0
        enable_udp = request.form.get("enable_udp") == "on"
        chain_mode = request.form.get("chain_mode") == "on"
        forward_chain_smart_select = request.form.get("forward_chain_smart_select") == "on"
        balance_strategy = request.form.get("balance_strategy", type=int)
        target_select_mode = request.form.get("target_select_mode", type=int)
        test_method = request.form.get("test_method", type=int)
        accept_proxy_protocol = request.form.get("accept_proxy_protocol", type=int) == 1
        send_proxy_protocol_version = request.form.get("send_proxy_protocol_version", "").strip()
        custom_config_text = request.form.get("custom_config", "").strip()
        tags_text = request.form.get("tags", "").strip()
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
                    selected_forward_endpoint_ids or get_zero_runtime_config()["default_forward_endpoint_ids"]
                )
                custom_config = None
                if custom_config_text:
                    try:
                        custom_config = json.loads(custom_config_text)
                    except ValueError as exc:
                        raise ConversionError(f"自定义配置 JSON 非法: {exc}") from exc

                runtime_defaults = get_zero_runtime_config()
                preset = ZeroPreset.query.get(preset_id) if preset_id else None
                zero_options = {
                    "chain_mode": chain_mode,
                    "forward_endpoints": effective_forward_endpoint_ids,
                    "forward_chain_smart_select": forward_chain_smart_select,
                    "forward_chain_fixed_hops_num": chain_fixed_hops_num,
                    "forward_chain_fixed_last_hops_num": forward_chain_fixed_last_hops_num,
                    "balance_strategy": 0 if balance_strategy is None else balance_strategy,
                    "target_select_mode": 0 if target_select_mode is None else target_select_mode,
                    "test_method": runtime_defaults.get("default_test_method", 1) if test_method is None else test_method,
                    "enable_udp": enable_udp,
                    "accept_proxy_protocol": accept_proxy_protocol,
                    "send_proxy_protocol_version": None if not send_proxy_protocol_version else int(send_proxy_protocol_version),
                    "custom_config": custom_config,
                    "tags": [item.strip() for item in tags_text.split(",") if item.strip()],
                }
                payload.preset_snapshot_json = json.dumps(
                    {
                        "preset_id": preset.id if preset else None,
                        "preset_name": preset.name if preset else "",
                        "config": zero_options,
                    },
                    ensure_ascii=False,
                )
                results = create_ports_for_payload(
                    client,
                    payload,
                    zero_options=zero_options,
                )
                attach_zero_sync_to_records(payload, results)
                current_app.config["ZERO_LAST_DEBUG_PAYLOAD"] = {
                    "batch_code": payload.batch_code,
                    "relay_name": relay_server.name,
                    "preset_id": preset.id if preset else None,
                    "requests": getattr(payload, "last_zero_payloads", []),
                    "result_summary": {
                        "ok": sum(1 for item in results if item.ok),
                        "failed": sum(1 for item in results if not item.ok),
                        "dry_run": any(item.dry_run for item in results),
                    },
                }
                sync_payload_render_fields(payload)
                payload.zero_summary = {
                    "enabled": True,
                    "ok": sum(1 for item in results if item.ok),
                    "failed": sum(1 for item in results if not item.ok),
                    "dry_run": any(item.dry_run for item in results),
                }
                if preset:
                    preset.usage_count += 1

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

    @app.route("/settings/zero", methods=["GET", "POST"])
    @login_required
    def zero_settings():
        current_settings = get_zero_runtime_config()

        if request.method == "POST":
            base_url = request.form.get("zero_api_base", "").strip().rstrip("/")
            api_key = request.form.get("zero_api_key", "").strip()
            timeout = request.form.get("zero_api_timeout", type=float) or 10
            dry_run = request.form.get("zero_dry_run") == "on"
            default_forward_endpoint_ids = normalize_forward_endpoint_ids(request.form.get("zero_default_forward_endpoint_ids", ""))
            default_chain_fixed_hops_num = request.form.get("zero_default_chain_fixed_hops_num", type=int) or 2

            set_app_setting("ZERO_API_BASE", base_url)
            set_app_setting("ZERO_API_KEY", api_key)
            set_app_setting("ZERO_API_TIMEOUT", str(timeout))
            set_app_setting("ZERO_DRY_RUN", "true" if dry_run else "false")
            set_app_setting(
                "ZERO_DEFAULT_FORWARD_ENDPOINT_IDS",
                ",".join(str(item) for item in default_forward_endpoint_ids),
            )
            set_app_setting("ZERO_DEFAULT_CHAIN_FIXED_HOPS_NUM", str(default_chain_fixed_hops_num))
            db.session.commit()

            flash("Zero 配置已保存。", "success")
            return redirect(url_for("zero_settings"))

        zero_health = None
        if has_zero_config():
            try:
                zero_health = get_zero_health_payload()
            except ZeroAPIError as exc:
                zero_health = {"ok": False, "error": str(exc)}

        return render_template(
            "zero_settings.html",
            zero_settings=current_settings,
            zero_health=zero_health,
            zero_presets=ZeroPreset.query.order_by(ZeroPreset.is_default.desc(), ZeroPreset.name.asc()).all(),
        )

    @app.route("/settings/zero/presets", methods=["POST"])
    @login_required
    def zero_preset_save():
        preset_id = request.form.get("preset_id", type=int)
        name = request.form.get("name", "").strip()
        description = request.form.get("description", "").strip()
        is_default = request.form.get("is_default") == "on"

        if not name:
            flash("预设名称不能为空。", "danger")
            return redirect(url_for("zero_settings"))

        preset = ZeroPreset.query.get(preset_id) if preset_id else ZeroPreset()
        if preset.is_system and preset_id:
            flash("系统预设不允许直接修改，请复制后再编辑。", "danger")
            return redirect(url_for("zero_settings"))

        config_payload = {
            "chain_mode": request.form.get("chain_mode") == "on",
            "forward_endpoints": normalize_forward_endpoint_ids(request.form.get("forward_endpoints", "")),
            "forward_chain_smart_select": request.form.get("forward_chain_smart_select") == "on",
            "forward_chain_fixed_hops_num": request.form.get("forward_chain_fixed_hops_num", type=int) or 0,
            "forward_chain_fixed_last_hops_num": request.form.get("forward_chain_fixed_last_hops_num", type=int) or 0,
            "balance_strategy": request.form.get("balance_strategy", type=int) or 0,
            "target_select_mode": request.form.get("target_select_mode", type=int) or 0,
            "test_method": request.form.get("test_method", type=int) or 1,
            "enable_udp": request.form.get("enable_udp") == "on",
            "accept_proxy_protocol": request.form.get("accept_proxy_protocol") == "on",
            "send_proxy_protocol_version": None if not request.form.get("send_proxy_protocol_version", "").strip() else int(request.form.get("send_proxy_protocol_version")),
            "custom_config": None,
            "tags": [item.strip() for item in request.form.get("tags", "").split(",") if item.strip()],
        }

        preset.name = name
        preset.description = description
        preset.config_json = json.dumps(config_payload, ensure_ascii=False)
        if not preset_id:
            db.session.add(preset)

        if is_default:
            ZeroPreset.query.update({"is_default": False})
        preset.is_default = is_default
        db.session.commit()
        flash("Zero 预设已保存。", "success")
        return redirect(url_for("zero_settings"))

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

    @app.post("/history/<batch_code>/reconcile")
    @login_required
    def batch_reconcile(batch_code: str):
        batch = ConversionBatch.query.filter_by(batch_code=batch_code).first_or_404()
        if not has_zero_config():
            flash("Zero API 尚未配置，无法对账。", "danger")
            return redirect(url_for("batch_detail", batch_code=batch_code))

        report = reconcile_batch(get_zero_client(), batch, triggered_by="manual")
        flash(
            f"对账完成：一致 {report['counts'].get('in_sync', 0)}，漂移 {report['counts'].get('drifted', 0)}，Zero 缺失 {report['counts'].get('missing_on_zero', 0)}。",
            "success",
        )
        return redirect(url_for("batch_detail", batch_code=batch_code))

    @app.post("/history/<batch_code>/retry-zero")
    @login_required
    def batch_retry_zero(batch_code: str):
        batch = ConversionBatch.query.filter_by(batch_code=batch_code).first_or_404()
        if not has_zero_config():
            flash("Zero API 尚未配置，无法重试同步。", "danger")
            return redirect(url_for("batch_detail", batch_code=batch_code))

        runtime_defaults = get_zero_runtime_config()
        zero_options = {
            "chain_mode": bool(runtime_defaults["default_forward_endpoint_ids"]),
            "forward_endpoints": runtime_defaults["default_forward_endpoint_ids"],
            "forward_chain_smart_select": True,
            "forward_chain_fixed_hops_num": runtime_defaults["default_chain_fixed_hops_num"],
            "forward_chain_fixed_last_hops_num": 0,
            "balance_strategy": 0,
            "target_select_mode": 0,
            "test_method": runtime_defaults.get("default_test_method", 1),
            "enable_udp": True,
            "accept_proxy_protocol": False,
            "send_proxy_protocol_version": None,
            "custom_config": None,
            "tags": [],
        }
        retried = retry_failed_records(get_zero_client(), batch, zero_options=zero_options)
        flash(f"已重试 {retried} 条失败记录。", "success" if retried else "warning")
        return redirect(url_for("batch_detail", batch_code=batch_code))

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

    @app.get("/api/zero/presets")
    @login_required
    def zero_presets():
        presets = ZeroPreset.query.order_by(ZeroPreset.is_default.desc(), ZeroPreset.name.asc()).all()
        return jsonify(
            {
                "items": [
                    {
                        "id": preset.id,
                        "name": preset.name,
                        "description": preset.description,
                        "config": json.loads(preset.config_json or "{}"),
                        "is_default": preset.is_default,
                        "is_system": preset.is_system,
                    }
                    for preset in presets
                ]
            }
        )

    @app.get("/api/zero/debug/last-payload")
    @login_required
    def zero_debug_last_payload():
        if not current_app.debug:
            return {"error": "not_found"}, 404
        return jsonify(current_app.config.get("ZERO_LAST_DEBUG_PAYLOAD") or {})


def has_zero_config() -> bool:
    config = get_zero_runtime_config()
    return bool(config.get("base_url") and config.get("api_key"))


def get_zero_client() -> ZeroClient:
    config = get_zero_runtime_config()
    return ZeroClient(
        base_url=config["base_url"],
        api_key=config["api_key"],
        timeout=config["timeout"],
        dry_run=config["dry_run"],
    )


def get_zero_health_payload() -> dict:
    data, _ = get_zero_client().get_subscription()
    lines = data.get("lines") or []
    return {
        "ok": True,
        "subscription_valid_until": data.get("valid_until") or data.get("expired_at") or "",
        "lines_count": len(lines),
        "is_admin": data.get("is_admin"),
        "dry_run": get_zero_runtime_config()["dry_run"],
    }


def fetch_forward_endpoints() -> list[dict]:
    data, _ = get_zero_client().list_forward_endpoints()
    raw_items = data if isinstance(data, list) else data.get("items") or data.get("data") or []
    return summarize_forward_endpoints(raw_items)


def get_app_setting(key: str) -> str | None:
    setting = AppSetting.query.filter_by(key=key).first()
    return setting.value if setting else None


def set_app_setting(key: str, value: str) -> None:
    setting = AppSetting.query.filter_by(key=key).first()
    if setting is None:
        setting = AppSetting(key=key, value=value)
        db.session.add(setting)
    else:
        setting.value = value


def normalize_forward_endpoint_ids(raw_value: str) -> list[int]:
    return [int(item.strip()) for item in raw_value.split(",") if item.strip().isdigit()]


def get_zero_runtime_config() -> dict:
    app_config = current_app.config

    base_url = get_app_setting("ZERO_API_BASE")
    api_key = get_app_setting("ZERO_API_KEY")
    timeout = get_app_setting("ZERO_API_TIMEOUT")
    dry_run = get_app_setting("ZERO_DRY_RUN")
    default_forward_endpoint_ids = get_app_setting("ZERO_DEFAULT_FORWARD_ENDPOINT_IDS")
    default_chain_fixed_hops_num = get_app_setting("ZERO_DEFAULT_CHAIN_FIXED_HOPS_NUM")

    return {
        "base_url": (base_url if base_url is not None else app_config["ZERO_API_BASE"]).rstrip("/"),
        "api_key": api_key if api_key is not None else app_config["ZERO_API_KEY"],
        "timeout": float(timeout if timeout is not None else app_config["ZERO_API_TIMEOUT"]),
        "dry_run": (dry_run if dry_run is not None else str(app_config["ZERO_DRY_RUN"]).lower()) == "true",
        "default_forward_endpoint_ids": normalize_forward_endpoint_ids(default_forward_endpoint_ids)
        if default_forward_endpoint_ids is not None
        else list(app_config["ZERO_DEFAULT_FORWARD_ENDPOINT_IDS"]),
        "default_chain_fixed_hops_num": int(
            default_chain_fixed_hops_num
            if default_chain_fixed_hops_num is not None
            else app_config["ZERO_DEFAULT_CHAIN_FIXED_HOPS_NUM"]
        ),
        "default_test_method": int(app_config.get("ZERO_DEFAULT_TEST_METHOD", 1)),
    }
