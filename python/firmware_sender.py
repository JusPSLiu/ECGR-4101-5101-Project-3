import serial
import time                 # used later for pauses between chunks and for timeouts
from pathlib import Path    # used to build the .bin file path no matter where the script is run from

# =============================================================================
# SETTINGS
# Every value you might need to change lives here, so nothing else in the
# script has to be edited if the port, file location, or protocol changes.
# =============================================================================

# Serial port 
PORT = "COM5"               # COM port the bootloader shows up as (check Device Manager -> Ports)
BAUDRATE = 115200           # USB CDC ignores the baud rate, but pyserial still requires a value
SERIAL_TIMEOUT = 1          # seconds a single read waits before giving up

#  Firmware file
# Path to the compiled application binary, built from this script's own folder:
#   python/ -> up one level -> Lab3_Application/build/Debug/Lab3_Application.bin
# Using the script's location means it works whether you run it from the repo
# root or from inside the python/ folder.
BIN_PATH = Path(__file__).parent / ".." / "Lab3_Application" / "build" / "Debug" / "Lab3_Application.bin"

#  Transfer settings 
CHUNK_SIZE = 64             # bytes sent per write (matches the USB full-speed packet size)
CHUNK_DELAY = 0.01          # seconds to pause between chunks so the bootloader can keep up with flash writes

# Protocol (agreed with Feature 1) 
# If Feature 1 changes the protocol - only these lines should need updating
SEND_SIZE_FIRST = True      # send the file size as 4 bytes (little-endian uint32) before the data
READY_BYTE = b'R'           # byte the bootloader sends after it finishes erasing flash
READY_TIMEOUT = 15          # seconds to wait for READY_BYTE (erasing the app region takes a few seconds)
DONE_BYTE = b'D'            # optional: byte the bootloader sends when writing finished successfully
ERROR_BYTE = b'E'           # optional: byte the bootloader sends if something failed
DONE_TIMEOUT = 10           # seconds to wait for DONE_BYTE / ERROR_BYTE after the last chunk

# Replace "COM5" with your port name (or "/dev/ttyACM0" on Linux)
ser = serial.Serial(port="COM5", baudrate=115200, timeout=1)
print(f"Connected to {ser.name}")

# file is at "../Lab3_Application/build/Debug/Lab3_Application.elf"