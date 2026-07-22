#!/usr/bin/env python3
import json
import math
import os
import struct
import termios
import time

PORT = "/dev/ttyACM2"


def parse_float4(b):
    mantis = (b[0] & 0xFF) + ((b[1] & 0xFF) << 8) + (((b[2] & 0x7F) | 0x80) << 16)
    exp = (b[3] & 0x7F) * 2 + (1 if (b[2] & 0x80) else 0)
    if b[3] & 0x80:
        mantis = -mantis
    return math.ldexp(mantis, exp - 127 - 23) if (mantis or exp) else 0.0


def setup(fd):
    attrs = termios.tcgetattr(fd)
    attrs[0] = 0
    attrs[1] = 0
    attrs[2] = termios.CS8 | termios.CREAD | termios.CLOCAL
    attrs[3] = 0
    attrs[4] = termios.B115200
    attrs[5] = termios.B115200
    attrs[6][termios.VMIN] = 0
    attrs[6][termios.VTIME] = 10
    termios.tcsetattr(fd, termios.TCSANOW, attrs)


def read_exact(fd, n, timeout=2.0):
    end = time.time() + timeout
    out = bytearray()
    while len(out) < n and time.time() < end:
        try:
            chunk = os.read(fd, n - len(out))
        except BlockingIOError:
            chunk = b""
        if chunk:
            out.extend(chunk)
        else:
            time.sleep(0.02)
    if len(out) != n:
        raise TimeoutError(f"wanted {n} bytes, got {len(out)}")
    return bytes(out)


def read_some(fd, timeout=1.0):
    end = time.time() + timeout
    chunks = []
    while time.time() < end:
        try:
            data = os.read(fd, 256)
        except BlockingIOError:
            data = b""
        if data:
            chunks.append(data)
            time.sleep(0.05)
        else:
            time.sleep(0.02)
    return b"".join(chunks)


fd = os.open(PORT, os.O_RDWR | os.O_NOCTTY)
try:
    setup(fd)
    termios.tcflush(fd, termios.TCIOFLUSH)

    os.write(fd, b"V\r")
    version = read_some(fd, timeout=1.0).decode("latin1", "replace").strip()

    cmd = bytes([0xBF, 0xB2, 0xB1, 0xF4, 0x9E, 0x99, 0xF3, 0xF5, 0xF2, 0x00])
    termios.tcflush(fd, termios.TCIFLUSH)
    os.write(fd, cmd)

    acceleration = parse_float4(read_exact(fd, 4))
    orientation = parse_float4(read_exact(fd, 4))
    inclination = parse_float4(read_exact(fd, 4))
    _prox = read_exact(fd, 16)
    _ambient = read_exact(fd, 16)
    _mics = read_exact(fd, 8)
    _battery = read_exact(fd, 2)
    gyro = struct.unpack('<3h', read_exact(fd, 6))
    tof_mm = struct.unpack('<H', read_exact(fd, 2))[0]
    button = read_exact(fd, 1)[0]
    microsd = read_exact(fd, 1)[0]

    termios.tcflush(fd, termios.TCIFLUSH)
    os.write(fd, b"C\r")
    selector = read_some(fd, timeout=1.0).decode("latin1", "replace").strip()

    print(json.dumps({
        "port": PORT,
        "version_raw": version,
        "selector_raw": selector,
        "acceleration": round(acceleration, 3),
        "orientation": round(orientation, 3),
        "inclination": round(inclination, 3),
        "gyro_raw": list(gyro),
        "tof_mm": tof_mm,
        "button": button,
        "microsd": microsd,
    }, indent=2))
finally:
    os.close(fd)
