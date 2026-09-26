import PySimpleGUI as sg
import serial
from collections import deque
from serial.tools import list_ports


def get_active_ports():
	"""Return the currently available serial port names."""
	# This list comprehension builds a new list from the port objects returned
	# by pyserial. It is similar to filling an array in a for loop in C.
	return [port.device for port in list_ports.comports()]


# Load ports once so the dropdown has options when the window opens.
ports = get_active_ports()
# Each row is a separate line of controls in the window.
# These nested lists describe rows: each inner list contains the controls in
# one row. The key strings act like IDs used to find controls after creation.
layout = [
	[sg.Text("COM port:"), sg.Combo(ports, key="-PORT-", readonly=True, size=(20, 1))],
	[sg.Button("Connect", key="-CONNECT-"), sg.Button("Refresh", key="-REFRESH-"),
	 sg.Button("Show Data", key="-SHOW-DATA-", disabled=True),
	 sg.Button("Test Window", key="-TEST-WINDOW-")],
	[sg.Text("Not connected", key="-STATUS-")],
]


def create_data_window():
	"""Create the live serial-data monitor window."""
	# Like the main layout above, this is a description of controls, not a
	# sequence of drawing commands. PySimpleGUI creates the actual window below.
	data_layout = [
		[sg.Text("Incoming bytes (hex)")],
		[sg.Multiline("", key="-RAW-", size=(80, 4), disabled=True, autoscroll=True)],
		[sg.Text("Decoded bytes (first byte after connecting is assumed to be the status register)")],
		[sg.Text("Status register: waiting for byte 1", key="-STATUS-REGISTER-")],
		[sg.Table(
			values=[],
			headings=["Status bit", "State"],
			key="-STATUS-BITS-",
			auto_size_columns=True,
			col_widths=[18, 12],
			justification="left",
			num_rows=8,
		)],
		[sg.Text("Remaining bytes (unsigned 0-255)")],
		[sg.Table(
			values=[],
			headings=["Byte #", "Decimal", "Hex"],
			key="-VALUES-",
			auto_size_columns=True,
			col_widths=[12, 12, 12],
			justification="left",
			num_rows=8,
		)],
	]
	# finalize=True creates the window immediately so it can be updated at once.
	return sg.Window("DC Load Data", data_layout, finalize=True)


def update_data_window(data_window, raw_bytes, status_byte, value_bytes):
	"""Refresh the raw-byte view and the decoded tables."""
	# Format each byte as two hexadecimal digits, such as 5 -> 05 or 255 -> FF.
	data_window["-RAW-"].update(" ".join(f"{byte_value:02X}" for byte_value in raw_bytes))

	if status_byte is None:
		data_window["-STATUS-REGISTER-"].update("Status register: waiting for byte 1")
		data_window["-STATUS-BITS-"].update(values=[])
	else:
		data_window["-STATUS-REGISTER-"].update(
			f"Status register: 0x{status_byte:02X} ({status_byte})"
		)
		# Bit 0 is the least-significant bit. Each row shows whether that bit is set.
		bit_rows = [
			[f"Bit {bit_index}", "On" if status_byte & (1 << bit_index) else "Off"]
			for bit_index in range(8)
		]
		data_window["-STATUS-BITS-"].update(values=bit_rows)

	# Keep the byte's position in the received sequence as well as its value.
	value_rows = [
		[byte_index, byte_value, f"0x{byte_value:02X}"]
		for byte_index, byte_value in value_bytes
	]
	data_window["-VALUES-"].update(values=value_rows)


# Create the main window and initialize the program's state.
# None is Python's equivalent of a null pointer: no connection/window exists yet.
window = sg.Window("DC Load", layout)
connection = None
data_window = None
# Serial input is binary, so retain byte values directly instead of decoding text.
# Keep only recent bytes/values for display so memory use stays bounded.
raw_bytes = deque(maxlen=64)
value_bytes = deque(maxlen=32)
received_byte_count = 0
status_byte = None

# This loop is the GUI's event loop. The 100 ms timeout lets it check for serial
# input regularly even when the user is not clicking a button.
while True:
	# read() returns a pair: the event ID and a dictionary of current control values.
	event, values = window.read(timeout=100)

	if event == sg.WIN_CLOSED:
		break

	if event == "-REFRESH-":
		# Rescan ports and update the dropdown with the latest list.
		ports = get_active_ports()
		# The conditional expression selects the first port if one exists,
		# otherwise it selects an empty string.
		window["-PORT-"].update(values=ports, value=ports[0] if ports else "")

	elif event == "-CONNECT-":
		port = values.get("-PORT-")
		if not port:
			# Don't try to open a connection until a port is selected.
			window["-STATUS-"].update("Select a COM port first")
			continue

		try:
			# Close any old connection first, then open the selected port at
			# 9600 baud. A timeout prevents reads from waiting forever.
			if connection and connection.is_open:
				connection.close()
			connection = serial.Serial(port, baudrate=9600, timeout=1)
			# A successful connection always opens a fresh data window and clears
			# values left over from any earlier connection.
			if data_window:
				data_window.close()
			data_window = create_data_window()
			window.hide()
			# Start decoding from the beginning of this connection. The first
			# received byte is provisionally treated as the status register.
			raw_bytes.clear()
			value_bytes.clear()
			received_byte_count = 0
			status_byte = None
			window["-SHOW-DATA-"].update(disabled=False)
			window["-STATUS-"].update(f"Connected to {port}")
		except serial.SerialException as error:
			# On failure, show the exception text and mark the handle as empty.
			connection = None
			window["-STATUS-"].update(f"Connection failed: {error}")
	elif event == "-SHOW-DATA-":
		# This button only reopens the monitor for a live serial connection.
		if connection and connection.is_open and not data_window:
			data_window = create_data_window()
			window.hide()
			update_data_window(data_window, raw_bytes, status_byte, value_bytes)
	elif event == "-TEST-WINDOW-":
		# Preview the same window without opening a serial port. No fake serial
		# data is generated; this is only for checking the window layout.
		if not data_window:
			data_window = create_data_window()
			window.hide()
			update_data_window(data_window, raw_bytes, status_byte, value_bytes)
		if not connection or not connection.is_open:
			window["-STATUS-"].update("Test window opened without a serial connection")

	# PySimpleGUI windows are read separately. A zero timeout checks the second
	# window without delaying the main window's event loop.
	if data_window:
		data_event, _ = data_window.read(timeout=0)
		if data_event == sg.WIN_CLOSED:
			data_window.close()
			data_window = None
			window.un_hide()

	# in_waiting is the number of bytes already buffered by the serial driver.
	# This condition avoids a read when there is no connection or no new input.
	if connection and connection.is_open and connection.in_waiting:
		try:
			# Read exactly the number of bytes currently available. The returned
			# value is a bytes object: each item is already an integer from 0 to 255.
			available_bytes = connection.in_waiting
			received_bytes = connection.read(available_bytes)
			for byte_value in received_bytes:
				raw_bytes.append(byte_value)
				received_byte_count += 1
				if status_byte is None:
					status_byte = byte_value
				else:
					# All later bytes are shown as unsigned values until the packet
					# length/markers are known well enough to split packets.
					value_bytes.append((received_byte_count, byte_value))
			if data_window and received_bytes:
				update_data_window(data_window, raw_bytes, status_byte, value_bytes)
		except (serial.SerialException, OSError) as error:
			# A disconnected device can fail during a read even after opening.
			window["-STATUS-"].update(f"Serial read failed: {error}")
			connection.close()

# Release resources on normal exit, similar to closing files/sockets in C.
if connection and connection.is_open:
	connection.close()
if data_window:
	data_window.close()
window.close()

