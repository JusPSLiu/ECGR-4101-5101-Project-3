import serial
import serial.tools.list_ports   # lets us list the COM ports the laptop can see - to help pick the right one
import sys                       # used to exit the script cleanly with an error message
import struct                    # used to pack the file size into 4 raw bytes (little-endian uint32)
import time                 # used later for pauses between chunks and for timeouts
from pathlib import Path    # used to build the .bin file path no matter where the script is run from


# Every value you might need to change lives here - so nothing else in the
# script has to be edited if the port, file location, or protocol changes


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

DONE_TIMEOUT = 10           # seconds to wait for DONE_BYTE / ERROR_BYTE after the last chunk

# Testing
# True  = no board needed: skip opening the port and just PRINT what would be sent.
# False = real run: open the port and actually send to the bootloader.
# Set this to False for the team test with the real board.
DRY_RUN = True


# SECTION B: READ THE FIRMWARE FILE


def read_firmware(path):
    """Read the entire .bin file into memory and return it as bytes."""
    path = path.resolve()                 # turn the "python/../Lab3_Application/..." path into a clean full path
    with open(path, "rb") as f:           # "rb" = read binary: raw bytes exactly as they'll go into flash, not text
        data = f.read()                   # read the whole file at once (app images are small - a few KB)
    print(f"Read {len(data)} bytes from {path.name}")   # confirm the file was found and show its size
    return data                           # hand the bytes to the rest of the script to send

firmware = read_firmware(BIN_PATH)        # read the file now so later sections can send it


# SECTION C: OPEN THE SERIAL PORT


# Replace "COM5" with your port name (or "/dev/ttyACM0" on Linux)
if DRY_RUN:
    ser = None                                    # no real port in dry-run mode; send() below just prints instead
    print("DRY RUN: not opening a serial port (set DRY_RUN = False when the board is connected)")
else:
    try:
        ser = serial.Serial(port=PORT, baudrate=BAUDRATE, timeout=SERIAL_TIMEOUT)  # open the port using the values from the settings block
    except serial.SerialException as e:
        # The port doesn't exist or is in use; print a clear message instead of a long traceback
        print(f"Could not open {PORT}. Is the board plugged into the USB OTG FS port and running the bootloader?")
        print(f"Details: {e}")
        # List every COM port the laptop can currently see - so the user can pick the right one for PORT
        ports = [p.device + " - " + p.description for p in serial.tools.list_ports.comports()]
        print("Available ports:", ", ".join(ports) if ports else "none found")
        sys.exit(1)                                   # stop here; nothing else can work without a connection
    print(f"Connected to {ser.name}")                 # success: show which port we connected to

# file is at "../Lab3_Application/build/Debug/Lab3_Application.elf"


# SECTION D: SEND THE FILE SIZE


def send(data, label):
    """Send raw bytes to the bootloader - or, in dry-run mode, just print what would be sent."""
    if DRY_RUN:
        preview = data[:8].hex(" ")                  # show the first 8 bytes in hex, e.g. "eb 03 00 00"
        more = " ..." if len(data) > 8 else ""       # mark that there are more bytes than shown
        print(f"[DRY RUN] would send {label} ({len(data)} bytes): {preview}{more}")
    else:
        ser.write(data)                              # push the bytes out over the USB CDC (virtual COM) port
        ser.flush()                                  # wait until they have actually left the laptop

if SEND_SIZE_FIRST:
    # Pack the firmware length into exactly 4 bytes:
    #   "<" = little-endian (lowest byte first - the same byte order the STM32 uses)
    #   "I" = unsigned 32-bit integer (uint32_t on the bootloader side)
    # e.g. 1003 bytes = 0x000003EB -> sent as eb 03 00 00
    size_bytes = struct.pack("<I", len(firmware))
    send(size_bytes, "file size")
    print(f"File size sent: {len(firmware)} bytes")  # tells the bootloader exactly how many data bytes to expect