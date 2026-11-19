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
WAIT_FOR_DONE = True        # True = wait for DONE_BYTE at the end; set False if Feature 1 doesn't send one
DONE_TIMEOUT = 10           # seconds to wait for DONE_BYTE / ERROR_BYTE after the last chunk

# Safety limits
WRITE_TIMEOUT = 5           # seconds a single write may block before we decide the bootloader stopped listening
MAX_APP_SIZE = 960 * 1024   # application flash region is 960 KB (0x08010000 to the end of flash) - a bigger file can't fit

# Testing
# True  = no board needed: skip opening the port and just PRINT what would be sent.
# False = real run: open the port and actually send to the bootloader.
# Set this to False for the team test with the real board.
DRY_RUN = True


# SECTION G: ERROR HANDLING
# This runs automatically if anything below crashes, so the user sees a short,
# clear message instead of a long red traceback - and the COM port always gets closed.


def handle_error(exc_type, exc, tb):
    """Called by Python for any error that isn't caught elsewhere in the script."""
    print()                                          # end the progress line (if any) before printing the message
    if issubclass(exc_type, KeyboardInterrupt):
        print("Stopped by user (Ctrl+C). The firmware was NOT fully sent - run the script again to retry.")
    elif issubclass(exc_type, serial.SerialTimeoutException):
        print(f"Transmission error: the bootloader stopped accepting data (no progress for {WRITE_TIMEOUT} s).")
        print("Reset the board, put it back in update mode, and run the script again.")
    elif issubclass(exc_type, serial.SerialException):
        print("Transmission error: lost connection to the board during the transfer.")
        print(f"Details: {exc}")
        print("Check the USB OTG FS cable, reset the board, and run the script again.")
    else:
        sys.__excepthook__(exc_type, exc, tb)        # anything unexpected: show the normal Python traceback so it can be debugged
    port = globals().get("ser")                      # the port may not exist yet if the error happened early
    if port:
        try:
            port.close()                             # always release the COM port so it isn't left "in use"
        except Exception:
            pass                                     # the port may already be gone (e.g. cable unplugged)
    sys.exit(1)

sys.excepthook = handle_error                        # tell Python to use handle_error for uncaught errors from here on


# SECTION B: READ THE FIRMWARE FILE


def read_firmware(path):
    """Read the entire .bin file into memory and return it as bytes."""
    path = path.resolve()                 # turn the "python/../Lab3_Application/..." path into a clean full path
    with open(path, "rb") as f:           # "rb" = read binary: raw bytes exactly as they'll go into flash, not text
        data = f.read()                   # read the whole file at once (app images are small - a few KB)
    print(f"Read {len(data)} bytes from {path.name}")   # confirm the file was found and show its size
    return data                           # hand the bytes to the rest of the script to send

try:
    firmware = read_firmware(BIN_PATH)        # read the file now so later sections can send it
except FileNotFoundError:
    # The application hasn't been built yet, or the path in BIN_PATH is wrong
    print(f"Firmware file not found: {BIN_PATH.resolve()}")
    print("Build the Lab3_Application project first (or check BIN_PATH in the settings).")
    sys.exit(1)

if len(firmware) == 0:
    # An empty file would "succeed" but leave the board with no application at all
    print("Firmware file is empty - rebuild the Lab3_Application project and try again.")
    sys.exit(1)
if len(firmware) > MAX_APP_SIZE:
    # Too big to fit in the application flash region; writing it would run past the end of flash
    print(f"Firmware is {len(firmware)} bytes but the application region only holds {MAX_APP_SIZE} bytes.")
    sys.exit(1)


# SECTION C: OPEN THE SERIAL PORT


# Replace "COM5" with your port name (or "/dev/ttyACM0" on Linux)
if DRY_RUN:
    ser = None                                    # no real port in dry-run mode; send() below just prints instead
    print("DRY RUN: not opening a serial port (set DRY_RUN = False when the board is connected)")
else:
    try:
        ser = serial.Serial(port=PORT, baudrate=BAUDRATE, timeout=SERIAL_TIMEOUT, write_timeout=WRITE_TIMEOUT)  # open the port using the values from the settings block
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



    

# SECTION E: WAIT FOR THE BOOTLOADER'S "READY" SIGNAL


def wait_for_byte(expected, timeout, what):
    """Wait up to `timeout` seconds for the bootloader to send the `expected` byte.
    Returns True if it arrives, False if the bootloader reports an error or time runs out."""
    if DRY_RUN:
        print(f"[DRY RUN] pretending the bootloader sent the {what} ({expected!r})")
        return True                                   # no board in dry-run mode - so assume it replied

    print(f"Waiting up to {timeout} s for the {what}...")
    deadline = time.time() + timeout                  # the moment we give up waiting
    while time.time() < deadline:
        reply = ser.read(1)                           # wait up to SERIAL_TIMEOUT (1 s) for one byte; b'' if nothing came
        if reply == expected:
            return True                               # got the byte we were waiting for
        if reply == ERROR_BYTE:
            print(f"Bootloader reported an error while waiting for the {what}.")
            return False                              # bootloader said something went wrong
        # any other byte (or nothing yet) is ignored - keep waiting until the deadline
    print(f"Timed out: no {what} after {timeout} s.")
    return False                                      # deadline passed with no reply

if not wait_for_byte(READY_BYTE, READY_TIMEOUT, "ready signal"):
    # Without the ready signal the bootloader may still be erasing flash,
    # so sending the firmware now would lose data - stop instead.
    print("Is the bootloader in update mode? Try resetting the board and running the script again.")
    if ser:
        ser.close()                                   # release the COM port before exiting
    sys.exit(1)
print("Bootloader is ready - flash erased, starting firmware transfer")



# SECTION F: SEND THE FIRMWARE IN CHUNKS


total = len(firmware)                                 # total number of bytes to send
num_chunks = (total + CHUNK_SIZE - 1) // CHUNK_SIZE   # round up so a partial last chunk still counts
if DRY_RUN:
    last_chunk = total - (num_chunks - 1) * CHUNK_SIZE  # size of the final (possibly partial) chunk
    print(f"[DRY RUN] would send {num_chunks} chunks of up to {CHUNK_SIZE} bytes (last chunk: {last_chunk} bytes)")

sent = 0                                              # running count of bytes sent so far
for start in range(0, total, CHUNK_SIZE):             # step through the file CHUNK_SIZE bytes at a time
    chunk = firmware[start:start + CHUNK_SIZE]        # slice out the next piece (the last one may be shorter)
    if not DRY_RUN:
        ser.write(chunk)                              # send this piece to the bootloader
        ser.flush()                                   # make sure it has fully left the laptop before pausing
    sent += len(chunk)
    percent = sent * 100 // total                     # whole-number percentage complete
    # "\r" returns to the start of the line, so the progress updates in place instead of printing hundreds of lines
    print(f"\rSent {sent}/{total} bytes ({percent}%)", end="", flush=True)
    time.sleep(CHUNK_DELAY)                           # short pause so the bootloader can write flash before the next chunk
print()                                               # move to a new line after the progress line finishes

# After the last byte - wait for the bootloader to confirm it wrote everything to flash
if WAIT_FOR_DONE:
    if not wait_for_byte(DONE_BYTE, DONE_TIMEOUT, "done signal"):
        print("Firmware may not have been written correctly. Reset the board and run the script again.")
        if ser:
            ser.close()                               # release the COM port before exiting
        sys.exit(1)

if ser:
    ser.close()                                       # done with the port - release it for other programs
print("Firmware update complete! Press the User button on the board to start the new application.")