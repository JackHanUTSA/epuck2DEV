#!/usr/bin/env python3
import math
import os
import struct
import termios
import time
import tkinter as tk
from tkinter import messagebox

PORT = "/dev/ttyACM2"
POLL_MS = 500
WINDOW_TITLE = "e-puck2 Gyro Reader"


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


def read_gyro_sample(port=PORT):
    fd = os.open(port, os.O_RDWR | os.O_NOCTTY)
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
        read_exact(fd, 16)  # prox
        read_exact(fd, 16)  # ambient
        read_exact(fd, 8)   # mics
        read_exact(fd, 2)   # battery
        gyro = struct.unpack("<3h", read_exact(fd, 6))
        tof_mm = struct.unpack("<H", read_exact(fd, 2))[0]
        button = read_exact(fd, 1)[0]
        microsd = read_exact(fd, 1)[0]

        termios.tcflush(fd, termios.TCIFLUSH)
        os.write(fd, b"C\r")
        selector = read_some(fd, timeout=1.0).decode("latin1", "replace").strip()

        return {
            "port": port,
            "version_raw": version,
            "selector_raw": selector,
            "acceleration": round(acceleration, 3),
            "orientation": round(orientation, 3),
            "inclination": round(inclination, 3),
            "gyro_x": gyro[0],
            "gyro_y": gyro[1],
            "gyro_z": gyro[2],
            "tof_mm": tof_mm,
            "button": button,
            "microsd": microsd,
        }
    finally:
        os.close(fd)


class GyroApp:
    def __init__(self, root):
        self.root = root
        self.root.title(WINDOW_TITLE)
        self.auto_refresh = False

        self.port_var = tk.StringVar(value=PORT)
        self.status_var = tk.StringVar(value="Ready")
        self.value_vars = {
            "selector_raw": tk.StringVar(value="-"),
            "acceleration": tk.StringVar(value="-"),
            "orientation": tk.StringVar(value="-"),
            "inclination": tk.StringVar(value="-"),
            "gyro_x": tk.StringVar(value="-"),
            "gyro_y": tk.StringVar(value="-"),
            "gyro_z": tk.StringVar(value="-"),
            "tof_mm": tk.StringVar(value="-"),
            "button": tk.StringVar(value="-"),
            "microsd": tk.StringVar(value="-"),
        }

        self._build_ui()

    def _build_ui(self):
        frame = tk.Frame(self.root, padx=12, pady=12)
        frame.pack(fill="both", expand=True)

        tk.Label(frame, text="Port:").grid(row=0, column=0, sticky="w")
        tk.Entry(frame, textvariable=self.port_var, width=24).grid(row=0, column=1, sticky="ew", padx=(6, 0))

        tk.Button(frame, text="Read Once", command=self.read_once).grid(row=0, column=2, padx=(10, 0))
        self.auto_button = tk.Button(frame, text="Start Auto Refresh", command=self.toggle_auto)
        self.auto_button.grid(row=0, column=3, padx=(6, 0))

        fields = [
            ("Selector", "selector_raw"),
            ("Acceleration", "acceleration"),
            ("Orientation", "orientation"),
            ("Inclination", "inclination"),
            ("Gyro X", "gyro_x"),
            ("Gyro Y", "gyro_y"),
            ("Gyro Z", "gyro_z"),
            ("ToF mm", "tof_mm"),
            ("Button", "button"),
            ("microSD", "microsd"),
        ]

        for idx, (label_text, key) in enumerate(fields, start=1):
            tk.Label(frame, text=label_text + ":").grid(row=idx, column=0, sticky="w", pady=2)
            tk.Label(frame, textvariable=self.value_vars[key], anchor="w", width=24, relief="sunken").grid(
                row=idx, column=1, columnspan=3, sticky="ew", padx=(6, 0), pady=2
            )

        tk.Label(frame, textvariable=self.status_var, anchor="w", fg="blue").grid(
            row=len(fields) + 1, column=0, columnspan=4, sticky="ew", pady=(12, 0)
        )

        frame.columnconfigure(1, weight=1)

    def update_values(self, data):
        for key, var in self.value_vars.items():
            var.set(str(data.get(key, "-")))
        self.status_var.set(f"Last read ok from {data['port']}")

    def read_once(self):
        try:
            data = read_gyro_sample(self.port_var.get().strip())
            self.update_values(data)
        except Exception as exc:
            self.status_var.set(f"Read failed: {exc}")
            if not self.auto_refresh:
                messagebox.showerror("Gyro read failed", str(exc))

    def auto_step(self):
        if not self.auto_refresh:
            return
        self.read_once()
        self.root.after(POLL_MS, self.auto_step)

    def toggle_auto(self):
        self.auto_refresh = not self.auto_refresh
        if self.auto_refresh:
            self.auto_button.config(text="Stop Auto Refresh")
            self.status_var.set("Auto refresh started")
            self.auto_step()
        else:
            self.auto_button.config(text="Start Auto Refresh")
            self.status_var.set("Auto refresh stopped")


def main():
    root = tk.Tk()
    app = GyroApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
