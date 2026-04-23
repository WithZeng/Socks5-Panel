import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Any

from .models import ProxyRecord, RelayServer, beijing_now, db


@dataclass
class CreateResult:
    ok: bool
    zero_port_id: int | None = None
    port_v4: int | None = None
    error: str = ""
    dry_run: bool = False


def build_zero_port_payload(
    *,
    relay_server: RelayServer,
    record: dict[str, Any],
    forward_endpoint_ids: list[int],
    chain_fixed_hops_num: int,
    enable_udp: bool,
) -> dict[str, Any]:
    payload = {
        "display_name": record["remark"],
        "outbound_endpoint_id": relay_server.zero_line_id,
        "target_address_list": [f'{record["origin_host"]}:{record["origin_port"]}'],
        "forward_endpoints": forward_endpoint_ids,
        "chain_mode": bool(forward_endpoint_ids),
        "forward_chain_smart_select": True,
        "forward_chain_fixed_hops_num": chain_fixed_hops_num,
        "enable_udp": enable_udp,
        "target_select_mode": 0,
        "test_method": 1,
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
    forward_endpoint_ids: list[int],
    chain_fixed_hops_num: int,
    enable_udp: bool,
    max_workers: int = 5,
) -> list[CreateResult]:
    relay_server = payload.relay_server
    if not relay_server.zero_line_id:
        raise ValueError("Selected relay server is not linked to a Zero line.")

    results: list[CreateResult] = [CreateResult(ok=False, error="pending") for _ in payload.records]

    def submit_one(index: int, record: dict[str, Any]) -> tuple[int, CreateResult]:
        try:
            zero_payload = build_zero_port_payload(
                relay_server=relay_server,
                record=record,
                forward_endpoint_ids=forward_endpoint_ids,
                chain_fixed_hops_num=chain_fixed_hops_num,
                enable_udp=enable_udp,
            )
            response_data, _ = client.create_port(zero_payload)
            if response_data.get("dry_run"):
                return index, CreateResult(ok=True, dry_run=True, port_v4=record["assigned_port"])

            zero_port_id = response_data.get("id")
            port_v4 = response_data.get("port_v4") or record["assigned_port"]
            return index, CreateResult(ok=True, zero_port_id=zero_port_id, port_v4=port_v4)
        except Exception as exc:
            return index, CreateResult(ok=False, error=str(exc))

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
    for record, result in zip(payload.records, results):
        record["zero_port_id"] = result.zero_port_id
        if result.dry_run:
            record["zero_sync_status"] = "pending"
        else:
            record["zero_sync_status"] = "ok" if result.ok else "failed"
        record["zero_sync_error"] = result.error
        if result.port_v4:
            record["assigned_port"] = result.port_v4
            record["forward_line"] = (
                f'{payload.relay_server.host}:{result.port_v4}:{record["username"]}:{record["password"]}'
                f'{{{record["remark"]}}}'
            )
            json_entry = json.loads(record["json_entry"])
            json_entry["listen_port"] = result.port_v4
            record["json_entry"] = json.dumps(json_entry, ensure_ascii=False)


def build_zero_batch_status(records: list[ProxyRecord]) -> dict[str, int]:
    ok_count = sum(1 for record in records if record.zero_sync_status == "ok")
    failed_count = sum(1 for record in records if record.zero_sync_status == "failed")
    pending_count = sum(1 for record in records if record.zero_sync_status == "pending")
    return {"ok": ok_count, "failed": failed_count, "pending": pending_count}
