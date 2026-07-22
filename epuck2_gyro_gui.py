#!/usr/bin/env python3
import argparse
import csv
import json
import math
import os
import struct
import sys
import termios
import time
import tkinter as tk
from collections import deque
from datetime import datetime
from tkinter import messagebox

PORT = "/dev/ttyACM2"
POLL_MS = 500
WINDOW_TITLE = "e-puck2 Gyro + Proximity Reader"
HISTORY_SIZE = 120
PLOT_WIDTH = 520
PLOT_HEIGHT = 180
PLOT_PADDING = 16


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


def default_csv_path():
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return os.path.abspath(f"epuck2_gyro_log_{stamp}.csv")


def csv_fieldnames():
    fields = [
        "timestamp",
        "port",
        "selector_raw",
        "acceleration",
        "orientation",
        "inclination",
        "gyro_x",
        "gyro_y",
        "gyro_z",
        "tof_mm",
        "button",
        "microsd",
    ]
    fields.extend(f"prox_{idx}" for idx in range(8))
    fields.extend(f"ambient_{idx}" for idx in range(8))
    return fields


def sample_to_csv_row(data):
    row = {key: data.get(key, "") for key in csv_fieldnames()}
    row["timestamp"] = datetime.now().isoformat(timespec="seconds")
    for idx, value in enumerate(data.get("prox", [])):
        row[f"prox_{idx}"] = value
    for idx, value in enumerate(data.get("ambient", [])):
        row[f"ambient_{idx}"] = value
    return row


def append_csv_row(path, data):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    file_exists = os.path.exists(path)
    with open(path, "a", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=csv_fieldnames())
        if not file_exists:
            writer.writeheader()
        writer.writerow(sample_to_csv_row(data))


def run_headless(port=PORT, csv_path=None, count=1, interval_s=0.5):
    samples = []
    total = max(1, count)
    for idx in range(total):
        data = read_gyro_sample(port)
        samples.append(data)
        if csv_path:
            append_csv_row(csv_path, data)
        if idx + 1 < total:
            time.sleep(max(0.0, interval_s))
    return samples


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="e-puck2 gyro/proximity reader with GUI and headless fallback")
    parser.add_argument("--port", default=PORT, help=f"serial port (default: {PORT})")
    parser.add_argument("--headless", action="store_true", help="run without Tk and print JSON samples")
    parser.add_argument("--csv", help="optional CSV file path for headless logging")
    parser.add_argument("--count", type=int, default=1, help="number of headless samples to read (default: 1)")
    parser.add_argument("--interval", type=float, default=0.5, help="seconds between headless samples (default: 0.5)")
    return parser.parse_args(argv)


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
        prox = struct.unpack("<8H", read_exact(fd, 16))
        ambient = struct.unpack("<8H", read_exact(fd, 16))
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
            "prox": list(prox),
            "ambient": list(ambient),
        }
    finally:
        os.close(fd)


class GyroApp:
    def __init__(self, root):
        self.root = root
        self.root.title(WINDOW_TITLE)
        self.auto_refresh = False
        self.logging_enabled = False
        self.history = {
            "gyro_x": deque(maxlen=HISTORY_SIZE),
            "gyro_y": deque(maxlen=HISTORY_SIZE),
            "gyro_z": deque(maxlen=HISTORY_SIZE),
        }

        self.port_var = tk.StringVar(value=PORT)
        self.status_var = tk.StringVar(value="Ready")
        self.csv_path_var = tk.StringVar(value=default_csv_path())
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
        self.prox_vars = [tk.StringVar(value="-") for _ in range(8)]
        self.ambient_vars = [tk.StringVar(value="-") for _ in range(8)]

        self._build_ui()
        self.draw_plot()

    def _build_ui(self):
        frame = tk.Frame(self.root, padx=12, pady=12)
        frame.pack(fill="both", expand=True)

        top = tk.Frame(frame)
        top.pack(fill="x")

        tk.Label(top, text="Port:").grid(row=0, column=0, sticky="w")
        tk.Entry(top, textvariable=self.port_var, width=24).grid(row=0, column=1, sticky="ew", padx=(6, 6))
        tk.Button(top, text="Read Once", command=self.read_once).grid(row=0, column=2, padx=(4, 0))
        self.auto_button = tk.Button(top, text="Start Auto Refresh", command=self.toggle_auto)
        self.auto_button.grid(row=0, column=3, padx=(6, 0))

        tk.Label(top, text="CSV:").grid(row=1, column=0, sticky="w", pady=(8, 0))
        tk.Entry(top, textvariable=self.csv_path_var, width=48).grid(row=1, column=1, columnspan=2, sticky="ew", padx=(6, 6), pady=(8, 0))
        self.log_button = tk.Button(top, text="Start CSV Logging", command=self.toggle_logging)
        self.log_button.grid(row=1, column=3, padx=(6, 0), pady=(8, 0))
        tk.Button(top, text="New CSV Path", command=self.reset_csv_path).grid(row=1, column=4, padx=(6, 0), pady=(8, 0))
        top.columnconfigure(1, weight=1)

        middle = tk.Frame(frame)
        middle.pack(fill="both", expand=True, pady=(12, 0))

        values_frame = tk.LabelFrame(middle, text="Current values", padx=8, pady=8)
        values_frame.pack(side="left", fill="y")

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
        for idx, (label_text, key) in enumerate(fields):
            tk.Label(values_frame, text=label_text + ":", anchor="w").grid(row=idx, column=0, sticky="w", pady=2)
            tk.Label(values_frame, textvariable=self.value_vars[key], anchor="w", width=18, relief="sunken").grid(
                row=idx, column=1, sticky="ew", padx=(6, 0), pady=2
            )

        right = tk.Frame(middle)
        right.pack(side="left", fill="both", expand=True, padx=(12, 0))

        plot_frame = tk.LabelFrame(right, text="Live gyro plot", padx=8, pady=8)
        plot_frame.pack(fill="x")
        self.plot_canvas = tk.Canvas(plot_frame, width=PLOT_WIDTH, height=PLOT_HEIGHT, bg="white", highlightthickness=1)
        self.plot_canvas.pack(fill="x")
        legend = tk.Label(plot_frame, text="Red = X   Blue = Y   Green = Z")
        legend.pack(anchor="w", pady=(6, 0))

        sensor_frame = tk.Frame(right)
        sensor_frame.pack(fill="both", expand=True, pady=(12, 0))

        prox_frame = tk.LabelFrame(sensor_frame, text="Proximity", padx=8, pady=8)
        prox_frame.pack(side="left", fill="both", expand=True)
        ambient_frame = tk.LabelFrame(sensor_frame, text="Ambient", padx=8, pady=8)
        ambient_frame.pack(side="left", fill="both", expand=True, padx=(12, 0))

        for idx in range(8):
            tk.Label(prox_frame, text=f"P{idx}:", anchor="w").grid(row=idx, column=0, sticky="w", pady=2)
            tk.Label(prox_frame, textvariable=self.prox_vars[idx], anchor="w", width=10, relief="sunken").grid(
                row=idx, column=1, sticky="ew", padx=(6, 0), pady=2
            )
            tk.Label(ambient_frame, text=f"A{idx}:", anchor="w").grid(row=idx, column=0, sticky="w", pady=2)
            tk.Label(ambient_frame, textvariable=self.ambient_vars[idx], anchor="w", width=10, relief="sunken").grid(
                row=idx, column=1, sticky="ew", padx=(6, 0), pady=2
            )

        tk.Label(frame, textvariable=self.status_var, anchor="w", fg="blue").pack(fill="x", pady=(12, 0))

    def reset_csv_path(self):
        self.csv_path_var.set(default_csv_path())
        self.status_var.set("Generated a new CSV path")

    def update_values(self, data):
        for key, var in self.value_vars.items():
            var.set(str(data.get(key, "-")))
        for idx, value in enumerate(data.get("prox", [])):
            self.prox_vars[idx].set(str(value))
        for idx, value in enumerate(data.get("ambient", [])):
            self.ambient_vars[idx].set(str(value))

        self.history["gyro_x"].append(data["gyro_x"])
        self.history["gyro_y"].append(data["gyro_y"])
        self.history["gyro_z"].append(data["gyro_z"])
        self.draw_plot()

        if self.logging_enabled:
            append_csv_row(self.csv_path_var.get().strip(), data)

        status = f"Last read ok from {data['port']}"
        if self.logging_enabled:
            status += f" | logging to {self.csv_path_var.get().strip()}"
        self.status_var.set(status)

    def draw_plot(self):
        c = self.plot_canvas
        c.delete("all")
        width = PLOT_WIDTH
        height = PLOT_HEIGHT
        left = PLOT_PADDING
        right = width - PLOT_PADDING
        top = PLOT_PADDING
        bottom = height - PLOT_PADDING

        c.create_rectangle(left, top, right, bottom, outline="#bbbbbb")
        mid_y = (top + bottom) / 2
        c.create_line(left, mid_y, right, mid_y, fill="#dddddd", dash=(4, 3))

        all_values = [value for series in self.history.values() for value in series]
        if not all_values:
            c.create_text(width / 2, height / 2, text="No samples yet", fill="#777777")
            return

        max_abs = max(max(abs(v) for v in all_values), 1)
        c.create_text(left + 28, top + 10, text=f"±{max_abs}", fill="#666666")

        colors = {"gyro_x": "#d62728", "gyro_y": "#1f77b4", "gyro_z": "#2ca02c"}
        for key, color in colors.items():
            points = list(self.history[key])
            if len(points) < 2:
                continue
            xy = []
            x_step = (right - left) / max(len(points) - 1, 1)
            for idx, value in enumerate(points):
                x = left + idx * x_step
                y = mid_y - ((value / max_abs) * ((bottom - top) / 2 - 4))
                xy.extend([x, y])
            c.create_line(*xy, fill=color, width=2, smooth=False)

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

    def toggle_logging(self):
        self.logging_enabled = not self.logging_enabled
        if self.logging_enabled:
            self.log_button.config(text="Stop CSV Logging")
            self.status_var.set(f"CSV logging armed: {self.csv_path_var.get().strip()}")
        else:
            self.log_button.config(text="Start CSV Logging")
            self.status_var.set("CSV logging stopped")


def main(argv=None):
    args = parse_args(argv)

    no_display = not os.environ.get("DISPLAY")
    if args.headless or no_display:
        if no_display and not args.headless:
            print("No DISPLAY found; falling back to headless mode.", file=sys.stderr)
        samples = run_headless(
            port=args.port,
            csv_path=args.csv,
            count=args.count,
            interval_s=args.interval,
        )
        print(json.dumps(samples if len(samples) > 1 else samples[0], indent=2))
        if args.csv:
            print(f"CSV_LOGGED {os.path.abspath(args.csv)}", file=sys.stderr)
        return 0

    root = tk.Tk()
    app = GyroApp(root)
    app.port_var.set(args.port)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
