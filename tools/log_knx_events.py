#!/usr/bin/env python3
"""Log live Home Assistant KNX events to a local JSONL file."""

from __future__ import annotations

import argparse
import base64
from datetime import datetime
import hashlib
import json
import os
import signal
import socket
import ssl
import struct
import sys
from collections.abc import Iterable
from urllib.parse import urlparse, urlunparse

DEFAULT_ADDRESSES = ("5/0/75", "5/0/79", "5/0/81", "1/4/1")
DEFAULT_OUTPUT = ".knx-events.log"


def address_values(values: list[str] | None) -> list[str]:
    if not values:
        return []
    addresses = []
    for value in values:
        addresses.extend(address.strip() for address in value.split(",") if address.strip())
    return addresses


def normalize_address(value) -> str | None:
    if value is None:
        return None
    address = str(value).strip()
    return address or None


def event_addresses(data: dict) -> set[str]:
    keys = (
        "destination",
        "destination_address",
        "group_address",
        "address",
    )
    addresses = set()
    for key in keys:
        value = data.get(key)
        if isinstance(value, str):
            address = normalize_address(value)
            if address:
                addresses.add(address)
        elif isinstance(value, Iterable):
            for item in value:
                address = normalize_address(item)
                if address:
                    addresses.add(address)
        else:
            address = normalize_address(value)
            if address:
                addresses.add(address)
    return addresses


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Subscribe to Home Assistant knx_event events and append them as JSONL."
    )
    parser.add_argument(
        "address",
        nargs="*",
        help=(
            "Group address to log. Can be passed multiple times or comma-separated, "
            "for example: 2/3/0 2/3/10 or 2/3/0,2/3/10."
        ),
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
        "--addresses",
        action="append",
        dest="address_options",
        help="Group address to log. Can be passed multiple times. Positional addresses also work.",
    )
    parser.add_argument(
        "--default-addresses",
        action="store_true",
        help=f"Log the legacy default addresses: {', '.join(DEFAULT_ADDRESSES)}.",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Log all knx_event events instead of only the selected addresses.",
    )
    parser.add_argument(
        "--service-events",
        action="store_true",
        help="Also log Home Assistant call_service events for climate.set_temperature.",
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
    parser.add_argument(
        "--print-unmatched",
        action="store_true",
        help="Print filtered-out knx_event addresses to stderr for troubleshooting.",
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


class WebSocket:
    """Small blocking WebSocket client for Home Assistant's JSON API."""

    def __init__(self, url: str) -> None:
        self._url = url
        self._socket = self._connect(url)

    def close(self) -> None:
        try:
            self._socket.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        self._socket.close()

    def send_json(self, data: dict) -> None:
        self._send_frame(json.dumps(data, separators=(",", ":")).encode(), opcode=0x1)

    def receive_json(self) -> dict:
        while True:
            opcode, payload = self._receive_frame()
            if opcode == 0x1:
                return json.loads(payload.decode())
            if opcode == 0x8:
                raise RuntimeError("WebSocket closed by server")
            if opcode == 0x9:
                self._send_frame(payload, opcode=0xA)

    @staticmethod
    def _connect(url: str):
        parsed = urlparse(url)
        if parsed.scheme not in {"ws", "wss"}:
            raise ValueError(f"Unsupported WebSocket scheme: {parsed.scheme}")

        host = parsed.hostname
        if host is None:
            raise ValueError(f"Invalid WebSocket URL: {url}")
        port = parsed.port or (443 if parsed.scheme == "wss" else 80)
        path = parsed.path or "/"
        if parsed.query:
            path += f"?{parsed.query}"

        raw_socket = socket.create_connection((host, port), timeout=20)
        if parsed.scheme == "wss":
            context = ssl.create_default_context()
            sock = context.wrap_socket(raw_socket, server_hostname=host)
        else:
            sock = raw_socket

        key = base64.b64encode(os.urandom(16)).decode()
        request = (
            f"GET {path} HTTP/1.1\r\n"
            f"Host: {host}:{port}\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\n"
            "Sec-WebSocket-Version: 13\r\n"
            "\r\n"
        )
        sock.sendall(request.encode())

        response = b""
        while b"\r\n\r\n" not in response:
            chunk = sock.recv(4096)
            if not chunk:
                raise RuntimeError("No WebSocket handshake response")
            response += chunk

        header = response.split(b"\r\n", 1)[0]
        if b" 101 " not in header:
            raise RuntimeError(f"WebSocket handshake failed: {header.decode(errors='replace')}")

        accept = base64.b64encode(
            hashlib.sha1((key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode()).digest()
        ).decode()
        if f"Sec-WebSocket-Accept: {accept}".lower() not in response.decode(
            errors="ignore"
        ).lower():
            raise RuntimeError("WebSocket handshake accept header did not match")

        sock.settimeout(None)
        return sock

    def _send_frame(self, payload: bytes, opcode: int) -> None:
        first = 0x80 | opcode
        mask_bit = 0x80
        length = len(payload)
        if length < 126:
            header = struct.pack("!BB", first, mask_bit | length)
        elif length < 65536:
            header = struct.pack("!BBH", first, mask_bit | 126, length)
        else:
            header = struct.pack("!BBQ", first, mask_bit | 127, length)

        mask = os.urandom(4)
        masked = bytes(byte ^ mask[index % 4] for index, byte in enumerate(payload))
        self._socket.sendall(header + mask + masked)

    def _receive_frame(self) -> tuple[int, bytes]:
        first, second = self._read_exact(2)
        opcode = first & 0x0F
        masked = bool(second & 0x80)
        length = second & 0x7F
        if length == 126:
            length = struct.unpack("!H", self._read_exact(2))[0]
        elif length == 127:
            length = struct.unpack("!Q", self._read_exact(8))[0]

        mask = self._read_exact(4) if masked else None
        payload = self._read_exact(length)
        if mask is not None:
            payload = bytes(byte ^ mask[index % 4] for index, byte in enumerate(payload))
        return opcode, payload

    def _read_exact(self, length: int) -> bytes:
        chunks = bytearray()
        while len(chunks) < length:
            chunk = self._socket.recv(length - len(chunks))
            if not chunk:
                raise RuntimeError("WebSocket connection closed")
            chunks.extend(chunk)
        return bytes(chunks)


def authenticate(ws: WebSocket, token: str) -> None:
    auth_required = ws.receive_json()
    if auth_required.get("type") != "auth_required":
        raise RuntimeError(f"Unexpected websocket greeting: {auth_required}")

    ws.send_json({"type": "auth", "access_token": token})
    auth_response = ws.receive_json()
    if auth_response.get("type") != "auth_ok":
        raise RuntimeError(f"Authentication failed: {auth_response}")


def subscribe(ws: WebSocket, event_type: str, subscription_id: int) -> None:
    ws.send_json({"id": subscription_id, "type": "subscribe_events", "event_type": event_type})
    subscribe_response = ws.receive_json()
    if not subscribe_response.get("success"):
        raise RuntimeError(f"Subscription failed: {subscribe_response}")


def run(args: argparse.Namespace) -> None:
    token = args.token
    if not token and args.token_file:
        try:
            token = open(args.token_file, encoding="utf-8").read().strip()
        except FileNotFoundError:
            token = None

    if not token:
        raise SystemExit("Set HA_TOKEN to a Home Assistant long-lived access token.")

    selected_addresses = address_values(args.address) + address_values(args.address_options)
    if args.default_addresses:
        selected_addresses.extend(DEFAULT_ADDRESSES)
    if not selected_addresses and not args.all:
        raise SystemExit(
            "Pass at least one group address, use --all, or use --default-addresses."
        )
    addresses = set(selected_addresses)
    output_path = args.output
    stopping = False
    ws = None

    def stop(*_):
        nonlocal stopping
        stopping = True
        if ws is not None:
            ws.close()

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)

    url = websocket_url(args.url)
    print(f"Connecting to {url}", file=sys.stderr)
    if not args.all:
        print(f"Logging addresses: {', '.join(sorted(addresses))}", file=sys.stderr)
    print(f"Writing JSONL to {output_path}", file=sys.stderr)

    ws = WebSocket(url)
    try:
        authenticate(ws, token)
        subscribe(ws, "knx_event", 1)
        if args.service_events:
            subscribe(ws, "call_service", 2)
        with open(output_path, "a", encoding="utf-8") as log_file:
            while not stopping:
                try:
                    packet = ws.receive_json()
                except (OSError, RuntimeError):
                    if stopping:
                        break
                    raise
                if packet.get("type") != "event":
                    continue
                event = packet.get("event", {})
                event_data = event.get("data", {})
                if event.get("event_type") == "call_service":
                    if event_data.get("domain") != "climate":
                        continue
                    if event_data.get("service") != "set_temperature":
                        continue
                    entry = {
                        "logged_at": datetime.now().isoformat(timespec="milliseconds"),
                        "time_fired": event.get("time_fired"),
                        "event_type": "call_service",
                        "domain": event_data.get("domain"),
                        "service": event_data.get("service"),
                        "service_data": event_data.get("service_data"),
                        "context": event.get("context"),
                    }
                    line = json.dumps(entry, ensure_ascii=False, separators=(",", ":"))
                    log_file.write(line + "\n")
                    log_file.flush()
                    if args.print_events:
                        print(line)
                    continue

                packet_addresses = event_addresses(event_data)
                if not args.all and not packet_addresses.intersection(addresses):
                    if args.print_unmatched and packet_addresses:
                        print(
                            f"Ignored knx_event addresses: {', '.join(sorted(packet_addresses))}",
                            file=sys.stderr,
                        )
                    continue

                entry = normalize_event(event)
                entry["event_type"] = "knx_event"
                line = json.dumps(entry, ensure_ascii=False, separators=(",", ":"))
                log_file.write(line + "\n")
                log_file.flush()
                if args.print_events:
                    print(line)
    finally:
        if ws is not None:
            ws.close()


def main() -> None:
    run(parse_args())


if __name__ == "__main__":
    main()
