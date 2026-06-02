#!/usr/bin/env python3
"""Log live Home Assistant KNX events to a local JSONL file."""

from __future__ import annotations

import argparse
import asyncio
from datetime import datetime
import json
import os
import signal
import sys
from urllib.parse import urlparse, urlunparse

DEFAULT_ADDRESSES = ("5/0/75", "5/0/79", "5/0/81", "1/4/1")
DEFAULT_OUTPUT = ".knx-events.log"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Subscribe to Home Assistant knx_event events and append them as JSONL."
    )
    parser.add_argument(
        "--url",
        default=os.environ.get("HA_URL", "http://127.0.0.1:8123"),
        help="Home Assistant base URL. Default: HA_URL or http://127.0.0.1:8123",
    )
    parser.add_argument(
        "--token",
        default=os.environ.get("HA_TOKEN") or os.environ.get("SUPERVISOR_TOKEN"),
        help="Long-lived HA token. Default: HA_TOKEN or SUPERVISOR_TOKEN.",
    )
    parser.add_argument(
        "--token-file",
        default=os.environ.get("HA_TOKEN_FILE", ".ha-token"),
        help="File containing a long-lived HA token. Default: HA_TOKEN_FILE or .ha-token.",
    )
    parser.add_argument(
        "--address",
        action="append",
        dest="addresses",
        help="Group address to log. Can be passed multiple times.",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Log all knx_event events instead of only the selected addresses.",
    )
    parser.add_argument(
        "--output",
        default=DEFAULT_OUTPUT,
        help=f"JSONL output path. Default: {DEFAULT_OUTPUT}",
    )
    parser.add_argument(
        "--print",
        action="store_true",
        dest="print_events",
        help="Also print matching events to stdout.",
    )
    return parser.parse_args()


def websocket_url(base_url: str) -> str:
    parsed = urlparse(base_url)
    scheme = "wss" if parsed.scheme == "https" else "ws"
    return urlunparse((scheme, parsed.netloc, "/api/websocket", "", "", ""))


def dpt9(payload) -> float | None:
    if not isinstance(payload, list) or len(payload) != 2:
        return None
    raw = (payload[0] << 8) | payload[1]
    sign = -1 if raw & 0x8000 else 1
    exponent = (raw >> 11) & 0x0F
    mantissa = raw & 0x07FF
    return sign * 0.01 * mantissa * (2**exponent)


def normalize_event(event: dict) -> dict:
    data = event.get("data", {})
    payload = data.get("data", data.get("payload"))
    return {
        "logged_at": datetime.now().isoformat(timespec="milliseconds"),
        "time_fired": event.get("time_fired"),
        "source": data.get("source"),
        "destination": data.get("destination"),
        "direction": data.get("direction"),
        "telegramtype": data.get("telegramtype"),
        "payload": payload,
        "dpt9": dpt9(payload),
        "raw": data,
    }


async def subscribe(ws) -> None:
    auth_required = await ws.receive_json()
    if auth_required.get("type") != "auth_required":
        raise RuntimeError(f"Unexpected websocket greeting: {auth_required}")

    await ws.send_json({"type": "auth", "access_token": subscribe.token})
    auth_response = await ws.receive_json()
    if auth_response.get("type") != "auth_ok":
        raise RuntimeError(f"Authentication failed: {auth_response}")

    await ws.send_json({"id": 1, "type": "subscribe_events", "event_type": "knx_event"})
    subscribe_response = await ws.receive_json()
    if not subscribe_response.get("success"):
        raise RuntimeError(f"Subscription failed: {subscribe_response}")


subscribe.token = ""


async def run(args: argparse.Namespace) -> None:
    try:
        import aiohttp
    except ImportError as err:
        print("Missing Python package: aiohttp", file=sys.stderr)
        print("Run this on the Home Assistant host or in an environment with aiohttp.", file=sys.stderr)
        raise SystemExit(2) from err

    token = args.token
    if not token and args.token_file:
        try:
            token = open(args.token_file, encoding="utf-8").read().strip()
        except FileNotFoundError:
            token = None

    if not token:
        raise SystemExit("Set HA_TOKEN to a Home Assistant long-lived access token.")

    subscribe.token = token
    addresses = set(args.addresses or DEFAULT_ADDRESSES)
    output_path = args.output
    stop_event = asyncio.Event()

    def stop(*_):
        stop_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop)

    url = websocket_url(args.url)
    print(f"Connecting to {url}", file=sys.stderr)
    if not args.all:
        print(f"Logging addresses: {', '.join(sorted(addresses))}", file=sys.stderr)
    print(f"Writing JSONL to {output_path}", file=sys.stderr)

    async with aiohttp.ClientSession() as session:
        async with session.ws_connect(url, heartbeat=30) as ws:
            await subscribe(ws)
            with open(output_path, "a", encoding="utf-8") as log_file:
                while not stop_event.is_set():
                    msg = await ws.receive(timeout=1)
                    if msg.type == aiohttp.WSMsgType.TIMEOUT:
                        continue
                    if msg.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
                        break
                    if msg.type != aiohttp.WSMsgType.TEXT:
                        continue

                    packet = json.loads(msg.data)
                    if packet.get("type") != "event":
                        continue
                    event = packet.get("event", {})
                    event_data = event.get("data", {})
                    destination = str(event_data.get("destination"))
                    if not args.all and destination not in addresses:
                        continue

                    entry = normalize_event(event)
                    line = json.dumps(entry, ensure_ascii=False, separators=(",", ":"))
                    log_file.write(line + "\n")
                    log_file.flush()
                    if args.print_events:
                        print(line)


def main() -> None:
    asyncio.run(run(parse_args()))


if __name__ == "__main__":
    main()
