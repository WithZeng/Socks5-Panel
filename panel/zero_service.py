import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Any

from .models import ProxyRecord, ReconcileRun, RelayServer, beijing_now, db
from .zero_client import ZeroAPIError


RECONCILE_STATES = {
    "in_sync",
    "missing_on_zero",
    "drifted",
    "orphan_on_zero",
    "pending",
}


@dataclass
class CreateResult:
    ok: bool
    zero_port_id: int | None = None
    port_v4: int | None = None
    error: str = ""
    dry_run: bool = False
    request_payload: dict[str, Any] | None = None


def build_zero_port_payload(
    *,
    relay_server: RelayServer,
    record: dict[str, Any],
    zero_options: dict[str, Any],
) -> dict[str, Any]:
    payload = {
        "display_name": record["remark"],
        "outbound_endpoint_id": relay_server.zero_line_id,
        "target_address_list": [f'{record["origin_host"]}:{record["origin_port"]}'],
        "chain_mode": zero_options["chain_mode"],
        "forward_endpoints": zero_options["forward_endpoints"],
        "forward_chain_smart_select": zero_options["forward_chain_smart_select"],
        "forward_chain_fixed_hops_num": zero_options["forward_chain_fixed_hops_num"],
        "forward_chain_fixed_last_hops_num": zero_options["forward_chain_fixed_last_hops_num"],
        "balance_strategy": zero_options["balance_strategy"],
        "target_select_mode": zero_options["target_select_mode"],
        "test_method": zero_options["test_method"],
        "enable_udp": zero_options["enable_udp"],
        "accept_proxy_protocol": zero_options["accept_proxy_protocol"],
        "send_proxy_protocol_version": zero_options["send_proxy_protocol_version"],
        "custom_config": zero_options["custom_config"],
        "tags": zero_options["tags"],
    }
    if record.get("assigned_port"):
        payload["port_v4"] = record["assigned_port"]
    return payload


def sync_lines_into_relay_servers(client) -> dict[str, int]:
    lines_data, _ = client.list_lines()
    lines = lines_data if isinstance(lines_data, list) else lines_data.get("lines", [])
    synced_ids: set[int] = set()
    created = 0
    updated = 0

    for item in lines:
        zero_line_id = item.get("id")
        if zero_line_id is None:
            continue
        synced_ids.add(zero_line_id)

        relay = RelayServer.query.filter_by(zero_line_id=zero_line_id).first()
        if relay is None:
            relay = RelayServer.query.filter_by(name=item.get("display_name", "")).first()

        is_new = relay is None
        if relay is None:
            relay = RelayServer()
            db.session.add(relay)

        relay.name = item.get("display_name") or f"line-{zero_line_id}"
        relay.host = item.get("ip_addr") or relay.host or "unknown"
        relay.port_range_start = int(item.get("port_start") or 1)
        relay.port_range_end = int(item.get("port_end") or relay.port_range_start)
        relay.is_active = bool(item.get("is_online")) and not bool(item.get("is_suspended"))
        relay.zero_line_id = zero_line_id
        relay.synced_at = beijing_now()
        relay.notes = build_relay_notes(item, original_notes=relay.notes)
        relay.raw_meta = json.dumps(item, ensure_ascii=False)

        if is_new:
            created += 1
        else:
            updated += 1

    disabled = 0
    if synced_ids:
        stale_relays = RelayServer.query.filter(
            RelayServer.zero_line_id.isnot(None),
            RelayServer.zero_line_id.not_in(synced_ids),
            RelayServer.is_active.is_(True),
        ).all()
        for relay in stale_relays:
            relay.is_active = False
            disabled += 1

    db.session.commit()
    return {"created": created, "updated": updated, "disabled": disabled, "total": len(lines)}


def build_relay_notes(line: dict[str, Any], *, original_notes: str) -> str:
    summary = [
        "Synced from Zero",
        f"line_id={line.get('id')}",
        f"online={line.get('is_online')}",
        f"suspended={line.get('is_suspended')}",
        f"allow_forward={line.get('allow_forward')}",
        f"traffic_scale={line.get('traffic_scale')}",
    ]
    if original_notes and "Synced from Zero" not in original_notes:
        summary.append("")
        summary.append(original_notes)
    return "\n".join(summary).strip()


def create_ports_for_payload(
    client,
    payload,
    *,
    zero_options: dict[str, Any],
    max_workers: int = 5,
    max_retries: int = 3,
) -> list[CreateResult]:
    relay_server = payload.relay_server
    if not relay_server.zero_line_id:
        raise ValueError("Selected relay server is not linked to a Zero line.")

    results: list[CreateResult] = [CreateResult(ok=False, error="pending") for _ in payload.records]

    def submit_one(index: int, record: dict[str, Any]) -> tuple[int, CreateResult]:
        zero_payload = build_zero_port_payload(
            relay_server=relay_server,
            record=record,
            zero_options=zero_options,
        )

        last_error = ""
        for attempt in range(max_retries):
            try:
                response_data, _ = client.create_port(zero_payload)
                if response_data.get("dry_run"):
                    return index, CreateResult(
                        ok=True,
                        dry_run=True,
                        port_v4=record["assigned_port"],
                        request_payload=zero_payload,
                    )

                zero_port_id = response_data.get("id")
                port_v4 = response_data.get("port_v4") or record["assigned_port"]
                return index, CreateResult(
                    ok=True,
                    zero_port_id=zero_port_id,
                    port_v4=port_v4,
                    request_payload=zero_payload,
                )
            except ZeroAPIError as exc:
                last_error = translate_zero_error(exc, record["remark"])
                if exc.status in {429, 500, 502, 503, 504} and attempt < max_retries - 1:
                    time.sleep([0.5, 1.5, 3.5][attempt])
                    continue
                break
            except Exception as exc:  # pragma: no cover
                last_error = str(exc)
                break

        return index, CreateResult(ok=False, error=last_error, request_payload=zero_payload)

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [
            executor.submit(submit_one, index, record)
            for index, record in enumerate(payload.records)
        ]
        for future in as_completed(futures):
            index, result = future.result()
            results[index] = result

    return results


def summarize_forward_endpoints(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for item in items:
        endpoint_id = item.get("id")
        if endpoint_id is None:
            continue
        normalized.append(
            {
                "id": endpoint_id,
                "name": item.get("display_name") or item.get("name") or f"endpoint-{endpoint_id}",
                "tag": item.get("tag") or "",
                "is_group": bool(item.get("is_group")),
                "endpoint_ids": item.get("endpoint_ids") or [],
            }
        )
    return normalized


def attach_zero_sync_to_records(payload, results: list[CreateResult]) -> None:
    dry_run_logs: list[dict[str, Any]] = []

    for record, result in zip(payload.records, results):
        record["zero_port_id"] = result.zero_port_id
        if result.dry_run:
            record["zero_sync_status"] = "pending"
            dry_run_logs.append(
                {
                    "remark": record["remark"],
                    "assigned_port": record["assigned_port"],
                    "payload": result.request_payload,
                }
            )
        else:
            record["zero_sync_status"] = "ok" if result.ok else "failed"
        record["zero_sync_error"] = result.error
        record["reconcile_state"] = "pending"
        record["reconcile_note"] = "Waiting for reconciliation"
        if result.port_v4:
            record["assigned_port"] = result.port_v4
            record["forward_line"] = (
                f'{payload.relay_server.host}:{result.port_v4}:{record["username"]}:{record["password"]}'
                f'{{{record["remark"]}}}'
            )
            json_entry = json.loads(record["json_entry"])
            json_entry["listen_port"] = result.port_v4
            record["json_entry"] = json.dumps(json_entry, ensure_ascii=False)

    if dry_run_logs:
        payload.error_summary = append_dry_run_log(payload.error_summary, dry_run_logs)


def append_dry_run_log(existing_summary: str, dry_run_logs: list[dict[str, Any]]) -> str:
    log_block = "Zero dry-run payloads:\n" + json.dumps(dry_run_logs, ensure_ascii=False, indent=2)
    if existing_summary.strip():
        return f"{existing_summary}\n\n{log_block}"
    return log_block


def build_zero_batch_status(records: list[ProxyRecord]) -> dict[str, int]:
    ok_count = sum(1 for record in records if record.zero_sync_status == "ok")
    failed_count = sum(1 for record in records if record.zero_sync_status == "failed")
    pending_count = sum(1 for record in records if record.zero_sync_status == "pending")
    in_sync_count = sum(1 for record in records if record.reconcile_state == "in_sync")
    drifted_count = sum(1 for record in records if record.reconcile_state == "drifted")
    missing_count = sum(1 for record in records if record.reconcile_state == "missing_on_zero")
    orphan_count = sum(1 for record in records if record.reconcile_state == "orphan_on_zero")
    return {
        "ok": ok_count,
        "failed": failed_count,
        "pending": pending_count,
        "in_sync": in_sync_count,
        "drifted": drifted_count,
        "missing_on_zero": missing_count,
        "orphan_on_zero": orphan_count,
    }


def reconcile_batch(client, batch, *, triggered_by: str = "manual") -> dict[str, Any]:
    records = list(batch.records)
    if not records:
        return {"counts": {}, "diffs": []}

    relay = batch.relay_server
    zero_ports = list(client.iter_all_ports(outbound_endpoint_id=relay.zero_line_id))
    zero_by_id = {item.get("id"): item for item in zero_ports if item.get("id") is not None}
    local_zero_ids = {record.zero_port_id for record in records if record.zero_port_id}

    counts = {state: 0 for state in RECONCILE_STATES}
    diffs: list[dict[str, Any]] = []

    for record in records:
        if not record.zero_port_id:
            record.reconcile_state = "pending"
            record.reconcile_note = "Record has not been pushed to Zero yet."
            counts["pending"] += 1
            continue

        zero_port = zero_by_id.get(record.zero_port_id)
        if zero_port is None:
            record.reconcile_state = "missing_on_zero"
            record.reconcile_note = "Zero port was not found."
            counts["missing_on_zero"] += 1
            diffs.append({"record_id": record.id, "state": "missing_on_zero", "fields": []})
            continue

        field_diffs = compare_record_to_zero(record, zero_port)
        if field_diffs:
            record.reconcile_state = "drifted"
            record.reconcile_note = "; ".join(field_diffs)
            counts["drifted"] += 1
            diffs.append({"record_id": record.id, "state": "drifted", "fields": field_diffs})
        else:
            record.reconcile_state = "in_sync"
            record.reconcile_note = "Local record matches Zero."
            counts["in_sync"] += 1

    for zero_port in zero_ports:
        zero_port_id = zero_port.get("id")
        if zero_port_id and zero_port_id not in local_zero_ids:
            counts["orphan_on_zero"] += 1
            diffs.append(
                {
                    "record_id": None,
                    "zero_port_id": zero_port_id,
                    "state": "orphan_on_zero",
                    "fields": [zero_port.get("display_name") or ""],
                }
            )

    run = ReconcileRun(
        scope="batch",
        scope_ref=batch.batch_code,
        finished_at=beijing_now(),
        counts_json=json.dumps(counts, ensure_ascii=False),
        diffs_json=json.dumps(diffs[:100], ensure_ascii=False),
        triggered_by=triggered_by,
    )
    db.session.add(run)
    db.session.commit()
    return {"counts": counts, "diffs": diffs}


def compare_record_to_zero(record: ProxyRecord, zero_port: dict[str, Any]) -> list[str]:
    diffs: list[str] = []
    if zero_port.get("display_name") != record.remark:
        diffs.append("display_name")

    local_target = [f"{record.origin_host}:{record.origin_port}"]
    if (zero_port.get("target_address_list") or []) != local_target:
        diffs.append("target_address_list")

    zero_forward_endpoints = zero_port.get("forward_endpoints") or []
    local_json = {}
    try:
        local_json = json.loads(record.json_entry)
    except ValueError:
        local_json = {}

    if local_json.get("forward_endpoints") and local_json.get("forward_endpoints") != zero_forward_endpoints:
        diffs.append("forward_endpoints")

    return diffs


def retry_failed_records(client, batch, *, zero_options: dict[str, Any]) -> int:
    failed_records = [record for record in batch.records if record.zero_sync_status == "failed"]
    if not failed_records:
        return 0

    temp_payload = type("RetryPayload", (), {"relay_server": batch.relay_server, "records": []})()
    for record in failed_records:
        temp_payload.records.append(
            {
                "remark": record.remark,
                "origin_host": record.origin_host,
                "origin_port": record.origin_port,
                "username": record.username,
                "password": record.password,
                "assigned_port": record.assigned_port,
                "forward_line": record.forward_line,
                "json_entry": record.json_entry,
            }
        )

    results = create_ports_for_payload(client, temp_payload, zero_options=zero_options)
    success_count = 0
    for record, result in zip(failed_records, results):
        if result.ok and not result.dry_run:
            record.zero_port_id = result.zero_port_id
            record.zero_sync_status = "ok"
            record.zero_sync_error = ""
            record.reconcile_state = "pending"
            record.reconcile_note = "Retried successfully. Reconcile again to verify."
            success_count += 1
        else:
            record.zero_sync_error = result.error or record.zero_sync_error
    db.session.commit()
    return success_count


def translate_zero_error(exc: ZeroAPIError, remark: str) -> str:
    body = (exc.body or "").lower()
    if "target" in body and "invalid" in body:
        return "原始代理地址格式非法，请检查 host:port。"
    if "duplicate" in body and "display_name" in body:
        return f"备注 {remark} 在 Zero 已存在，请更换备注。"
    if "occupied" in body or "port" in body:
        return "端口已被占用，请改用自动分配或调整起始端口。"
    if exc.status == 403:
        return "API Key 无权操作当前线路。"
    if exc.status == 429:
        return "Zero 触发限流，请稍后重试。"
    if exc.status >= 500:
        return "Zero 服务异常，请稍后重试。"
    return str(exc)
