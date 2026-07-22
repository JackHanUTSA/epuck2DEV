#!/usr/bin/env python3
import os
import termios
import time

PORT = "/dev/ttyACM2"
BLINKS = 8


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


def send(fd, text):
    termios.tcflush(fd, termios.TCIFLUSH)
    os.write(fd, text.encode())
    time.sleep(0.2)
    try:
        reply = os.read(fd, 64)
    except BlockingIOError:
        reply = b""
    return reply.decode("latin1", "replace").strip()


fd = os.open(PORT, os.O_RDWR | os.O_NOCTTY)
try:
    setup(fd)
    termios.tcflush(fd, termios.TCIOFLUSH)

    for i in range(BLINKS):
        print(f"on  {i+1}:", send(fd, "B,1\r"))
        time.sleep(0.3)
        print(f"off {i+1}:", send(fd, "B,0\r"))
        time.sleep(0.2)

    print("stop:", send(fd, "S\r"))
finally:
    os.close(fd)
