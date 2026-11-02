import serial

# Replace "COM5" with your port name (or "/dev/ttyACM0" on Linux)
ser = serial.Serial(port="COM5", baudrate=115200, timeout=1)
print(f"Connected to {ser.name}")

# file is at "../Lab3_Application/build/Debug/Lab3_Application.elf"