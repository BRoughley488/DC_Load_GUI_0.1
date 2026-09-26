import PySimpleGUI as sg
import serial
from collections import deque
from serial.tools import list_ports
import time


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


def available_ports():
	return [port.device for port in list_ports.comports()]


def create_layout(ports):
	bit_rows = [
		[sg.Text(f"Bit {bit}", size=(6, 1)),
		 sg.Text(STATUS_BIT_LABELS[bit], size=(24, 1)),
		 sg.Text("Waiting", key=f"-BIT-{bit}-", size=(10, 1))]
		for bit in range(7, -1, -1)
	]

	return [
		[sg.Text("DC Load Serial Monitor", font=("Any", 16, "bold"))],
		[sg.Text("COM port"),
		 sg.Combo(ports, key="-PORT-", readonly=True, expand_x=True),
		 sg.Button("Refresh", key="-REFRESH-"),
		 sg.Text("Baud"), sg.Input("115200", key="-BAUD-", size=(9, 1)),
		 sg.Button("Connect", key="-CONNECT-")],
		[sg.Text("Disconnected", key="-CONNECTION-", size=(50, 1))],
		[sg.HorizontalSeparator()],
		[sg.Text("Raw received bytes (hex and binary)", font=("Any", 11, "bold")),
		 sg.Text("Latest byte decoded as status", font=("Any", 11, "bold"))],
		[sg.Multiline("", key="-RAW-", size=(58, 20), disabled=True,
					  autoscroll=True, expand_x=True, expand_y=True),
		 sg.VerticalSeparator(),
		 sg.Column(bit_rows, vertical_alignment="top")],
	]


def main():
	ports = available_ports()
	window = sg.Window(
		"DC Load Serial Monitor",
		create_layout(ports),
		resizable=True,
		finalize=True,
	)
	connection = None
	raw_lines = deque(maxlen=200)

	while True:
		event, values = window.read(timeout=50)
		if event == sg.WINDOW_CLOSED:
			break

		if event == "-REFRESH-":
			ports = available_ports()
			window["-PORT-"].update(values=ports)
			if values["-PORT-"] not in ports:
				window["-PORT-"].update(value="")

		if event == "-CONNECT-":
			if connection is not None:
				connection.close()
				connection = None
				window["-CONNECT-"].update("Connect")
				window["-CONNECTION-"].update("Disconnected")
				for bit in range(8):
					window[f"-BIT-{bit}-"].update("Waiting")
			else:
				try:
					port = values["-PORT-"]
					baud = int(values["-BAUD-"])
					if not port:
						raise ValueError("Select a COM port first.")
					connection = serial.Serial(port, baudrate=baud, timeout=0)
					window["-CONNECT-"].update("Disconnect")
					window["-CONNECTION-"].update(f"Connected to {port} at {baud} baud")
				except (ValueError, serial.SerialException) as error:
					sg.popup_error(str(error), title="Serial connection failed")

		if connection is not None and connection.is_open:
			try:
				waiting = connection.in_waiting
				if waiting:
					received = connection.read(waiting)
					timestamp = time.strftime("%H:%M:%S")
					for byte in received:
						raw_lines.append(
							f"{timestamp}  0x{byte:02X}  {byte:08b}"
						)
						for bit in range(8):
							state = "SET" if byte & (1 << bit) else "clear"
							window[f"-BIT-{bit}-"].update(state)
					window["-RAW-"].update("\n".join(raw_lines))
			except serial.SerialException as error:
				connection.close()
				connection = None
				window["-CONNECT-"].update("Connect")
				window["-CONNECTION-"].update(f"Serial error: {error}")

	if connection is not None and connection.is_open:
		connection.close()
	window.close()


if __name__ == "__main__":
	main()


