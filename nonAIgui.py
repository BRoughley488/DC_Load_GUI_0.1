import serial
import PySimpleGUI as sg
from serial.tools import list_ports
import configparser

config_path = Path(__file__).with_name("config.ini")

config = configparser.ConfigParser()


comPorts = list_ports.comports()
layout1 = [[sg.Text(comPorts)]]


window = sg.Window('Playing with my worm rn', layout1)

while True:
    event, values = window.read()
    if event == sg.WINDOW_CLOSED or event == 'Quit':
        break


window.close()