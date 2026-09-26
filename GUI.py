import PySimpleGUI as sg
import json
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
		[sg.Text("Incoming serial data")],
		[sg.Multiline("", key="-RAW-", size=(80, 14), disabled=True, autoscroll=True)],
		[sg.Text("Latest data points")],
		[sg.Table(
			values=[],
			headings=["Point", "Value"],
			key="-POINTS-",
			auto_size_columns=True,
			col_widths=[24, 24],
			justification="left",
			num_rows=8,
		)],
	]
	# finalize=True creates the window immediately so it can be updated at once.
	return sg.Window("DC Load Data", data_layout, finalize=True)


def parse_data_points(line):
	"""Extract key/value points from JSON objects or delimited text."""
	try:
		# JSON objects are converted to a Python dictionary (similar to a map
		# or hash table). Values are made strings for display in the table.
		parsed = json.loads(line)
		if isinstance(parsed, dict):
			return {str(key): str(value) for key, value in parsed.items()}
	except json.JSONDecodeError:
		# The line was not JSON, so try the simpler key=value / key:value format.
		pass

	# Use a dictionary so each point name maps to its most recent value.
	points = {}
	for field in line.replace(";", ",").split(","):
		separator = "=" if "=" in field else ":" if ":" in field else None
		if separator:
			name, value = field.split(separator, 1)
			name = name.strip()
			if name:
				points[name] = value.strip()
	return points


# Create the main window and initialize the program's state.
# None is Python's equivalent of a null pointer: no connection/window exists yet.
window = sg.Window("DC Load", layout)
connection = None
data_window = None
# Serial data can arrive in pieces. Keep an unfinished line here until its
# newline arrives; keep only the most recent 200 complete lines for the screen.
pending_data = ""
raw_lines = deque(maxlen=200)
# Dictionary of the newest value seen for each parsed point name.
latest_points = {}

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
			pending_data = ""
			raw_lines.clear()
			latest_points.clear()
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
			data_window["-RAW-"].update("\n".join(raw_lines))
			data_window["-POINTS-"].update(values=list(latest_points.items()))
	elif event == "-TEST-WINDOW-":
		# Preview the same window without opening a serial port. No fake serial
		# data is generated; this is only for checking the window layout.
		if not data_window:
			data_window = create_data_window()
			data_window["-RAW-"].update("\n".join(raw_lines))
			data_window["-POINTS-"].update(values=list(latest_points.items()))
		if not connection or not connection.is_open:
			window["-STATUS-"].update("Test window opened without a serial connection")

	# PySimpleGUI windows are read separately. A zero timeout checks the second
	# window without delaying the main window's event loop.
	if data_window:
		data_event, _ = data_window.read(timeout=0)
		if data_event == sg.WIN_CLOSED:
			data_window.close()
			data_window = None

	# in_waiting is the number of bytes already buffered by the serial driver.
	# This condition avoids a read when there is no connection or no new input.
	if connection and connection.is_open and connection.in_waiting:
		try:
			# Read currently available bytes and decode them as UTF-8. Invalid
			# byte sequences are replaced instead of crashing the GUI.
			received_data = connection.read(connection.in_waiting).decode("utf-8", errors="replace")
			pending_data += received_data
			# Split at newline boundaries. split() leaves the unfinished final
			# fragment in pending_data so it can be completed by the next read.
			lines = pending_data.split("\n")
			pending_data = lines.pop()
			for line in lines:
				line = line.rstrip("\r")
				if line:
					raw_lines.append(line)
					# Merge each parsed point into the dictionary, replacing older values.
					latest_points.update(parse_data_points(line))
			if data_window and received_data:
				# Include the unfinished fragment too, so data is visible before
				# its terminating newline arrives.
				display_lines = list(raw_lines)
				if pending_data:
					display_lines.append(pending_data)
				data_window["-RAW-"].update("\n".join(display_lines))
				data_window["-POINTS-"].update(values=list(latest_points.items()))
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

