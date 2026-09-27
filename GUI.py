import PySimpleGUI as sg
import serial
import ast
from collections import deque
from configparser import ConfigParser, Error as ConfigError
from pathlib import Path
from serial.tools import list_ports


def get_active_ports():
	"""Return the currently available serial port names."""
	# This list comprehension builds a new list from the port objects returned
	# by pyserial. It is similar to filling an array in a for loop in C.
	return [port.device for port in list_ports.comports()]


DECODER_WIDTHS = {
	"status_bits": 1,
	"uint8": 1,
	"int8": 1,
	"uint16_be": 2,
	"uint16_le": 2,
	"int16_be": 2,
	"int16_le": 2,
}


def load_config(config_path):
	"""Load and validate device and register settings from an INI file."""
	parser = ConfigParser(inline_comment_prefixes=("#", ";"))
	if not parser.read(config_path, encoding="utf-8"):
		raise ValueError(f"Configuration file not found: {config_path}")

	baudrate = parser.getint("device", "baudrate", fallback=9600)
	data_size = parser.getint("device", "data_size", fallback=8)
	if data_size != 8:
		raise ValueError("device.data_size must be 8 because serial input is byte-based")
	terminator_text = parser.get("device", "record_terminator")
	try:
		if terminator_text[:1] in ("'", '"'):
			record_terminator_text = ast.literal_eval(terminator_text)
		else:
			record_terminator_text = ast.literal_eval(f'"{terminator_text}"')
		if not isinstance(record_terminator_text, str):
			raise ValueError("device.record_terminator must resolve to text")
		record_terminator = record_terminator_text.encode("latin-1")
	except (SyntaxError, ValueError, UnicodeEncodeError) as error:
		raise ValueError("device.record_terminator must be a quoted or escaped byte string") from error
	if not record_terminator:
		raise ValueError("device.record_terminator cannot be empty")

	register_order = [
		name.strip()
		for name in parser.get("registers", "order").split(",")
		if name.strip()
	]
	if not register_order:
		raise ValueError("The [registers] order setting must list at least one register")
	if len(register_order) != len(set(register_order)):
		raise ValueError("The [registers] order setting contains duplicate names")

	registers = []
	for key in register_order:
		section = f"register.{key}"
		if not parser.has_section(section):
			raise ValueError(f"Missing [{section}] section")
		decoder = parser.get(section, "decoder").strip().lower()
		if decoder not in DECODER_WIDTHS:
			raise ValueError(
				f"Unsupported decoder '{decoder}' in [{section}]. "
				f"Supported decoders: {', '.join(DECODER_WIDTHS)}"
			)
		packet_width_bits = parser.getint(section, "packet_with_bits")
		if packet_width_bits <= 0 or packet_width_bits % data_size:
			raise ValueError(
				f"[{section}] packet_with_bits must be a positive multiple of {data_size}"
			)
		width = packet_width_bits // data_size
		if width != DECODER_WIDTHS[decoder]:
			raise ValueError(
				f"[{section}] packet_with_bits gives {width} bytes, but "
				f"decoder '{decoder}' requires {DECODER_WIDTHS[decoder]}"
			)
		registers.append({
			"key": key,
			"name": parser.get(section, "name"),
			"index": sum(item["width"] for item in registers),
			"width": width,
			"decoder": decoder,
			"scale": parser.getfloat(section, "scale", fallback=1.0),
			"unit": parser.get(section, "unit", fallback="").strip(),
		})

	status_bit_names = {}
	if parser.has_section("decoder.status_bits"):
		status_bit_names = {
			int(bit_number) - 1: bit_name.strip()
			for bit_number, bit_name in parser.items("decoder.status_bits")
			if bit_number.isdecimal() and 1 <= int(bit_number) <= data_size
		}
	return baudrate, sum(register["width"] for register in registers), record_terminator, registers, status_bit_names


def decode_frame(frame, registers, status_bit_names):
	"""Decode one complete frame and return register and status-bit table rows."""
	register_rows = []
	status_rows = []
	for register in registers:
		start = register["index"]
		width = register["width"]
		register_bytes = frame[start:start + width]
		raw_text = " ".join(f"0x{byte_value:02X}" for byte_value in register_bytes)
		decoder = register["decoder"]

		if decoder == "status_bits":
			value = register_bytes[0]
			value_text = f"0x{value:02X} ({value})"
			status_rows = [
				[
					status_bit_names.get(bit_index, f"Bit {bit_index + 1}"),
					"On" if value & (1 << bit_index) else "Off",
				]
				for bit_index in range(8)
			]
		else:
			byte_order = "little" if decoder.endswith("_le") else "big"
			signed = decoder.startswith("int")
			value = int.from_bytes(register_bytes, byteorder=byte_order, signed=signed)
			value *= register["scale"]
			value_text = f"{value:g} {register['unit']}".strip()

		register_rows.append([register["name"], value_text, raw_text])
	return register_rows, status_rows


def extract_records(buffer, record_length, record_terminator):
	"""Remove complete fixed-width payloads and their trailing terminators."""
	records = []
	invalid_records = 0
	record_size = record_length + len(record_terminator)
	while len(buffer) >= record_size:
		frame = bytes(buffer[:record_length])
		terminator = bytes(buffer[record_length:record_size])
		del buffer[:record_size]
		if terminator == record_terminator:
			records.append(frame)
		else:
			invalid_records += 1
	return records, invalid_records


# Load ports once so the dropdown has options when the window opens.
ports = get_active_ports()
config_path = Path(__file__).with_name("config.ini")
try:
	baudrate, record_length, record_terminator, registers, status_bit_names = load_config(config_path)
except (ConfigError, OSError, ValueError) as error:
	sg.popup_error(f"Could not load {config_path.name}: {error}")
	raise SystemExit(1)
status_register = next(
	(register for register in registers if register["decoder"] == "status_bits"),
	None,
)
status_register_name = status_register["name"] if status_register else "Status register"
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
		[sg.Text("Decoded registers")],
		[sg.Table(
			values=[],
			headings=["Register", "Value", "Bytes"],
			key="-REGISTERS-",
			auto_size_columns=True,
			col_widths=[18, 16, 12],
			justification="left",
			num_rows=max(3, len(registers)),
		)],
		[sg.Text(f"{status_register_name} bits")],
		[sg.Table(
			values=[],
			headings=["Bit", "State"],
			key="-STATUS-BITS-",
			auto_size_columns=True,
			col_widths=[18, 12],
			justification="left",
			num_rows=8,
		)],
	]
	# finalize=True creates the window immediately so it can be updated at once.
	return sg.Window("DC Load Data", data_layout, finalize=True)


def update_data_window(data_window, raw_bytes, register_rows, status_rows):
	"""Refresh the raw-byte view and the decoded tables."""
	# Format each byte as two hexadecimal digits, such as 5 -> 05 or 255 -> FF.
	data_window["-RAW-"].update(" ".join(f"{byte_value:02X}" for byte_value in raw_bytes))
	data_window["-REGISTERS-"].update(values=register_rows)
	data_window["-STATUS-BITS-"].update(values=status_rows)


# Create the main window and initialize the program's state.
# None is Python's equivalent of a null pointer: no connection/window exists yet.
window = sg.Window("DC Load", layout)
connection = None
data_window = None
# Serial input is binary, so retain byte values directly instead of decoding text.
# Keep only recent bytes/values for display so memory use stays bounded.
raw_bytes = deque(maxlen=64)
frame_buffer = bytearray()
register_rows = []
status_rows = []

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
			# Close any old connection first, then open the selected port using
			# the baud rate in config.ini.
			if connection and connection.is_open:
				connection.close()
			connection = serial.Serial(port, baudrate=baudrate, timeout=1)
			# A successful connection always opens a fresh data window and clears
			# values left over from any earlier connection.
			if data_window:
				data_window.close()
			data_window = create_data_window()
			window.hide()
			# Start frame decoding from a clean connection state.
			raw_bytes.clear()
			frame_buffer.clear()
			register_rows = []
			status_rows = []
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
			update_data_window(data_window, raw_bytes, register_rows, status_rows)
	elif event == "-TEST-WINDOW-":
		# Preview the same window without opening a serial port. No fake serial
		# data is generated; this is only for checking the window layout.
		if not data_window:
			data_window = create_data_window()
			window.hide()
			update_data_window(data_window, raw_bytes, register_rows, status_rows)
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
			# A record is the configured number of payload bytes followed by its terminator.
			available_bytes = connection.in_waiting
			received_bytes = connection.read(available_bytes)
			raw_bytes.extend(received_bytes)
			frame_buffer.extend(received_bytes)
			frames, invalid_records = extract_records(
				frame_buffer, record_length, record_terminator
			)
			for frame in frames:
				register_rows, status_rows = decode_frame(
					frame, registers, status_bit_names
				)
			if invalid_records:
				window["-STATUS-"].update(
					"Record terminator mismatch; check device protocol/config"
				)
			if data_window and received_bytes:
				update_data_window(data_window, raw_bytes, register_rows, status_rows)
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

