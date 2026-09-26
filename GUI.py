import PySimpleGUI as sg
import tkinter as tk
import serial
from serial.tools import list_ports


def get_active_ports():
	"""Return the currently available serial port names."""
	return [port.device for port in list_ports.comports()]


# Load ports once so the dropdown has options when the window opens.
ports = get_active_ports()
# Each row is a separate line of controls in the window.
layout = [
	[sg.Text("COM port:"), sg.Combo(ports, key="-PORT-", readonly=True, size=(20, 1))],
	[sg.Button("Connect", key="-CONNECT-"), sg.Button("Refresh", key="-REFRESH-")],
	[sg.Text("Not connected", key="-STATUS-")],
]

# Keep the connection so it can be reused or closed later.
window = sg.Window("DC Load", layout)
connection = None

# Handle GUI events until the user closes the window.
while True:
	event, values = window.read()

	if event == sg.WIN_CLOSED:
		break

	if event == "-REFRESH-":
		# Rescan ports and update the dropdown with the latest list.
		ports = get_active_ports()
		window["-PORT-"].update(values=ports, value=ports[0] if ports else "")

	elif event == "-CONNECT-":
		port = values.get("-PORT-")
		if not port:
			# Don't try to open a connection until a port is selected.
			window["-STATUS-"].update("Select a COM port first")
			continue

		try:
			# Close any existing connection before opening the selected port.
			if connection and connection.is_open:
				connection.close()
			connection = serial.Serial(port, baudrate=9600, timeout=1)
			window["-STATUS-"].update(f"Connected to {port}")
		except serial.SerialException as error:
			# Show the connection error in the window and clear the saved handle.
			connection = None
			window["-STATUS-"].update(f"Connection failed: {error}")

# Release the serial port and GUI resources when the event loop ends.
if connection and connection.is_open:
	connection.close()
window.close()

