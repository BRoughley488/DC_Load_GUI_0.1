# PySimpleGUI creates the window and its controls. pyserial handles UART/COM I/O.
import PySimpleGUI as sg
import serial
# These standard-library helpers limit the log size and add timestamps.
from collections import deque
from serial.tools import list_ports
import time


# Dictionary keys are bit positions: 7 is the highest bit and 0 is the lowest.
# Replace the placeholder text when the status-byte meanings are known.
STATUS_BIT_LABELS = {
	7: "Placeholder action",
	6: "Placeholder action",
	5: "Placeholder action",
	4: "Placeholder action",
	3: "Placeholder action",
	2: "Placeholder action",
	1: "Placeholder action",
	0: "Placeholder action",
}


# Return the serial port identifiers shown in the port selector.
def available_ports():
	# Port objects expose a device name, such as "COM3" or "/dev/ttyUSB0".
	return [port.device for port in list_ports.comports()]


def create_layout(ports):
	# Create one display row per bit. Each key is used later to update that row.
	bit_rows = [
		[sg.Text(f"Bit {bit}", size=(6, 1)),
		 sg.Text(STATUS_BIT_LABELS[bit], size=(24, 1)),
		 sg.Text("Waiting", key=f"-BIT-{bit}-", size=(10, 1))]
		for bit in range(7, -1, -1)
	]

	# PySimpleGUI layouts are lists of rows, with each row containing its controls.
	return [
		[sg.Text("DC Load Serial Monitor", font=("Any", 16, "bold"))],
		# Port and baud-rate controls, plus refresh and connect/disconnect buttons.
		[sg.Text("COM port"),
		 sg.Combo(ports, key="-PORT-", readonly=True, expand_x=True),
		 sg.Button("Refresh", key="-REFRESH-"),
		 sg.Text("Baud"), sg.Input("115200", key="-BAUD-", size=(9, 1)),
		 sg.Button("Connect", key="-CONNECT-")],
		[sg.Text("Disconnected", key="-CONNECTION-", size=(50, 1))],
		[sg.HorizontalSeparator()],
		# The left panel shows raw bytes; the right panel shows the latest byte's bits.
		[sg.Text("Raw received bytes (hex and binary)", font=("Any", 11, "bold")),
		 sg.Text("Latest byte decoded as status", font=("Any", 11, "bold"))],
		[sg.Multiline("", key="-RAW-", size=(58, 20), disabled=True,
					  autoscroll=True, expand_x=True, expand_y=True),
		 sg.VerticalSeparator(),
		 sg.Column(bit_rows, vertical_alignment="top")],
	]


def main():
	# Find available ports before building the dropdown and displaying the window.
	ports = available_ports()
	window = sg.Window(
		"DC Load Serial Monitor",
		create_layout(ports),
		resizable=True,
		finalize=True,
	)
	connection = None
	# Keep only the newest 200 lines so the raw log stays a manageable size.
	raw_lines = deque(maxlen=200)

	while True:
		# Wait briefly for a GUI event, then check again; this keeps the window responsive.
		event, values = window.read(timeout=50)
		if event == sg.WINDOW_CLOSED:
			break

		if event == "-REFRESH-":
			# Refresh the list in case a device was plugged in after the window opened.
			ports = available_ports()
			window["-PORT-"].update(values=ports)
			if values["-PORT-"] not in ports:
				window["-PORT-"].update(value="")

		if event == "-CONNECT-":
			if connection is not None:
				# Clicking Connect again closes an existing serial connection.
				connection.close()
				connection = None
				window["-CONNECT-"].update("Connect")
				window["-CONNECTION-"].update("Disconnected")
				for bit in range(8):
					window[f"-BIT-{bit}-"].update("Waiting")
			else:
				try:
					# GUI inputs arrive as text, so parse the baud rate into an integer.
					port = values["-PORT-"]
					baud = int(values["-BAUD-"])
					if not port:
						raise ValueError("Select a COM port first.")
					# timeout=0 makes serial reads non-blocking so they cannot freeze the GUI.
					connection = serial.Serial(port, baudrate=baud, timeout=0)
					window["-CONNECT-"].update("Disconnect")
					window["-CONNECTION-"].update(f"Connected to {port} at {baud} baud")
				except (ValueError, serial.SerialException) as error:
					sg.popup_error(str(error), title="Serial connection failed")

		# Read from the device only when a serial connection is open.
		if connection is not None and connection.is_open:
			try:
				# in_waiting reports how many bytes have arrived and are ready to read.
				waiting = connection.in_waiting
				if waiting:
					received = connection.read(waiting)
					timestamp = time.strftime("%H:%M:%S")
					# Packet framing is not defined yet, so decode each byte as status.
					for byte in received:
						# Show the byte both as hexadecimal (0xA5) and as eight binary digits.
						raw_lines.append(
							f"{timestamp}  0x{byte:02X}  {byte:08b}"
						)
						for bit in range(8):
							# Shift 1 to this bit position, then AND tests whether the bit is set.
							state = "SET" if byte & (1 << bit) else "clear"
							window[f"-BIT-{bit}-"].update(state)
					# Update the visible log after processing this batch of bytes.
					window["-RAW-"].update("\n".join(raw_lines))
			except serial.SerialException as error:
				# On a communication error, close the port and show the error in the window.
				connection.close()
				connection = None
				window["-CONNECT-"].update("Connect")
				window["-CONNECTION-"].update(f"Serial error: {error}")

	# Release the hardware port if the user closes the window while still connected.
	if connection is not None and connection.is_open:
		connection.close()
	window.close()


if __name__ == "__main__":
	main()


