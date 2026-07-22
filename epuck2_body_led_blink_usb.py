#!/usr/bin/env python3
"""Blink the e-puck2 body LED over the verified USB SerCom interface.

Default behavior:
- port: /dev/ttyACM2
- baud: 115200
- no motion commands
- body LED on/off repeated N times
- final cleanup with S (stop + turn off leds)

Example:
  python3 epuck2_body_led_blink_usb.py --port /dev/ttyACM2 --blinks 8
"""

from __future__ import annotations

import argparse
import json
import os
import termios
import time
from typing import List, Dict, Any


DEFAULT_PORT = "/dev/ttyACM2"
DEFAULT_BAUD = termios.B115200


def configure_port(fd: int) -> None:
    attrs = termios.tcgetattr(fd)
    attrs[0] = 0
    attrs[1] = 0
    attrs[2] = termios.CS8 | termios.CREAD | termios.CLOCAL
    attrs[3] = 0
    attrs[4] = DEFAULT_BAUD
    attrs[5] = DEFAULT_BAUD
    attrs[6][termios.VMIN] = 0
    attrs[6][termios.VTIME] = 10
    termios.tcsetattr(fd, termios.TCSANOW, attrs)


def read_some(fd: int, timeout: float = 0.45) -> bytes:
    end = time.time() + timeout
    chunks: list[bytes] = []
    while time.time() < end:
        try:
            data = os.read(fd, 256)
        except BlockingIOError:
            data = b""
        if data:
            chunks.append(data)
            time.sleep(0.03)
        else:
            time.sleep(0.02)
    return b"".join(chunks)


def send_command(fd: int, command: bytes, timeout: float = 0.45) -> str:
    termios.tcflush(fd, termios.TCIFLUSH)
    os.write(fd, command)
    response = read_some(fd, timeout=timeout)
    return response.decode("latin1", "replace").strip()


def run_blink_sequence(
    port: str,
    blinks: int,
    on_pause: float,
    off_pause: float,
    read_timeout: float,
) -> Dict[str, Any]:
    rows: List[Dict[str, Any]] = []
    fd = os.open(port, os.O_RDWR | os.O_NOCTTY)
    try:
        configure_port(fd)
        termios.tcflush(fd, termios.TCIOFLUSH)

        for i in range(1, blinks + 1):
            t0 = time.time()
            on_resp = send_command(fd, b"B,1\r", timeout=read_timeout)
            rows.append(
                {
                    "step": f"body_on_{i}",
                    "command": "B,1",
                    "response_raw": on_resp,
                    "elapsed_ms": round((time.time() - t0) * 1000, 1),
                }
            )
            time.sleep(on_pause)

            t0 = time.time()
            off_resp = send_command(fd, b"B,0\r", timeout=read_timeout)
            rows.append(
                {
                    "step": f"body_off_{i}",
                    "command": "B,0",
                    "response_raw": off_resp,
                    "elapsed_ms": round((time.time() - t0) * 1000, 1),
                }
            )
            time.sleep(off_pause)

        t0 = time.time()
        stop_resp = send_command(fd, b"S\r", timeout=read_timeout)
        rows.append(
            {
                "step": "stop_cleanup",
                "command": "S",
                "response_raw": stop_resp,
                "elapsed_ms": round((time.time() - t0) * 1000, 1),
            }
        )
    finally:
        os.close(fd)

    return {
        "port": port,
        "blink_count": blinks,
        "sequence": rows,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Blink the e-puck2 body LED over USB")
    parser.add_argument("--port", default=DEFAULT_PORT, help="STM32 ACM port, e.g. /dev/ttyACM2")
    parser.add_argument("--blinks", type=int, default=8, help="Number of body LED blinks")
    parser.add_argument("--on-pause", type=float, default=0.35, help="Seconds to pause after LED on")
    parser.add_argument("--off-pause", type=float, default=0.20, help="Seconds to pause after LED off")
    parser.add_argument("--read-timeout", type=float, default=0.45, help="Seconds to wait for each ack")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result = run_blink_sequence(
        port=args.port,
        blinks=args.blinks,
        on_pause=args.on_pause,
        off_pause=args.off_pause,
        read_timeout=args.read_timeout,
    )
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
