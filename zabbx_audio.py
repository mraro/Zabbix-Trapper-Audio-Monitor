# pyinstaller zabbx_audio.py --onefile --windowed --add-data="resources_rc.py:resources_rc.py" -i "icon.ico" -n "Zabbix Audio Capture v2.1.5 86x"
import configparser
import socket
import sys
import time

from PySide2 import QtCore
from PySide2.QtGui import QIcon, QIntValidator
from PySide2.QtWidgets import QSystemTrayIcon, QMenu, QLabel, QLineEdit, QComboBox, QHBoxLayout, QApplication, \
    QMainWindow, QPushButton, QVBoxLayout, QWidget, QAction

from pyzabbix import ZabbixMetric, ZabbixSender

import pyaudio
import threading

import numpy as np

import os
import tempfile
import resources_rc
from equalizer_bar import EqualizerBar

import ctypes

ctypes.windll.kernel32.SetConsoleTitleW("Zabbix Audio Capture")


class Autoparse:
    def __init__(self):
        self.app = QApplication(sys.argv)
        self.app.setQuitOnLastWindowClosed(False)
        self.trayIcon = QSystemTrayIcon(self.app)

        icon = QIcon(":/icons/app_icon.png")
        print(icon)
        print(":/icons/app_icon.png")
        # Create the tray
        tray = QSystemTrayIcon()
        tray.setIcon(icon)
        tray.setVisible(True)

        # Create the menu
        menu = self.create_menu()

        # Add the menu to the tray
        tray.setContextMenu(menu)

        print(tray.isVisible())
        self.p = None
        self.CHUNK = 2 ** 11
        self.RATE = 44100
        self.data = np.zeros(2)

        self.config_window = None
        self.open_config_window()

        self.populate_microphones()

        self.looping_running = True

        self.node = threading.Thread(target=self.current)
        self.node.start()

        try:
            self.zabbix_server, self.zabbix_port, self.zabbix_host = self.read_config_ini()
        except Exception as e:
            self.update_log(f"FALHA ao ler arquivo config.ini - \n {e}")

        sys.exit(self.app.exec_())

    def quit(self):
        try:
            self.looping_running = False
            time.sleep(3)
            del self.node
            self.app.quit()
            del self.__init__
        except:
            pass

    def create_menu(self):
        menu = QMenu()
        autopconfig_action = menu.addAction('Config')
        autopconfig_action.triggered.connect(self.open_config_window)
        exit_action = menu.addAction("Exit")
        exit_action.triggered.connect(self.quit)
        print("menu feito")
        return menu

    def open_config_window(self):

        if not self.config_window:
            self.config_window = QMainWindow()
            self.config_window.setGeometry(100, 100, 400, 200)
            self.config_window.setWindowIcon(QIcon(":/icons/app_icon.png"))

            self.config_window.setWindowTitle("Configurações de Áudio")

            # Widgets para as configurações de servidor
            server_label = QLabel("Server:")
            self.server_input = QLineEdit()
            self.server_input.setInputMask("000.000.000.000; ")
            self.server_input.setPlaceholderText("Endereço IPv4")
            # self.server_input.setFixedWidth(120)

            port_label = QLabel("Port:")
            self.port_input = QLineEdit()
            self.port_input.setValidator(QIntValidator())
            self.port_input.setMaxLength(5)

            hostname_label = QLabel("Hostname:")
            self.hostname_input = QLineEdit()

            # Carregar valores padrão dos parâmetros salvos, se existirem
            config = configparser.ConfigParser()
            config.read('config.ini')
            if 'Servidor' in config:
                server_config = config['Servidor']
                self.server_input.setText(server_config.get('Endereço', ''))
                self.port_input.setText(server_config.get('Porta', '10051'))
                self.hostname_input.setText(server_config.get('Hostname', socket.gethostname()))
            else:
                self.port_input.setText('10051')
                self.hostname_input.setText(socket.gethostname())

            # Botão de salvar
            save_button = QPushButton("Salvar")
            save_button.clicked.connect(self.save_settings)

            # Layout para as configurações de servidor
            server_layout = QVBoxLayout()

            server_layout.addWidget(server_label)
            server_layout.addWidget(self.server_input)
            server_layout.addWidget(port_label)
            server_layout.addWidget(self.port_input)
            server_layout.addWidget(hostname_label)
            server_layout.addWidget(self.hostname_input)
            server_layout.addWidget(save_button)

            # ComboBox para os microfones disponíveis
            microphone_label = QLabel("Microfone:")
            self.microphone_combobox = QComboBox()

            # Layout para a combobox do microfone
            microphone_layout = QVBoxLayout()
            microphone_layout.addWidget(microphone_label)
            microphone_layout.addWidget(self.microphone_combobox)

            # Plot Widget
            self.equalizer = EqualizerBar(2,
                                          ['#0C0786', '#40039C', '#6A00A7', '#8F0DA3', '#B02A8F', '#CA4678', '#E06461',
                                           '#F1824C', '#FCA635', '#FCCC25', '#EFF821'])

            self._timer = QtCore.QTimer()
            self._timer.setInterval(1)
            self._timer.timeout.connect(self.update_plot)
            self._timer.start()

            microphone_layout.addWidget(self.equalizer)

            # Widgets para as configurações de servidor
            self.log_label = QLabel("Log:")
            self.log_text = QLabel("")
            self.log_text.setWordWrap(True)

            # Layout para a label de log
            log_layout = QVBoxLayout()
            log_layout.addWidget(self.log_label)
            log_layout.addWidget(self.log_text)

            # Layout principal
            main_layout = QVBoxLayout()

            # Layout para as configurações de servidor e microfone
            server_microphone_layout = QHBoxLayout()
            server_microphone_layout.addLayout(server_layout)
            server_microphone_layout.addSpacing(20)  # Adicionando um espaçador
            server_microphone_layout.addLayout(microphone_layout)

            # Adicionando layouts ao layout principal
            main_layout.addLayout(server_microphone_layout)
            main_layout.addStretch(1)  # Adicionando um espaçador elástico
            main_layout.addLayout(log_layout)  # Adicionando a layout de log ao layout principal

            central_widget = QWidget()
            central_widget.setLayout(main_layout)

            self.config_window.setCentralWidget(central_widget)
        self.config_window.show()

    def update_log(self, message):
        # Atualizar o texto da label de log
        self.log_text.setText(message)

    def save_settings(self):
        try:
            # Salvar os parâmetros do usuário em um arquivo de configuração
            config = configparser.ConfigParser()
            config['Servidor'] = {
                'Endereço': self.server_input.text(),
                'Porta': self.port_input.text(),
                'Hostname': self.hostname_input.text()
            }

            with open('config.ini', 'w') as configfile:
                config.write(configfile)
        except Exception as e:
            print('error on send data:', e)

    def read_config_ini(self):
        try:
            # Ler os parâmetros do arquivo de configuração
            config = configparser.ConfigParser()
            config.read('config.ini')

            if 'Servidor' in config:
                server_config = config['Servidor']
                endereco = server_config.get('Endereço', '')
                porta = server_config.get('Porta', '')
                hostname = server_config.get('Hostname', '')
                return endereco, porta, hostname
            else:
                return '', '', ''

        except Exception as e:
            self.update_log(f'O Arquivo de configuração está invalido, erro:{e}')

    def populate_microphones(self):
        p = pyaudio.PyAudio()
        info = p.get_host_api_info_by_index(0)
        numdevices = info.get('deviceCount')
        list_microphones = []
        for i in range(numdevices):
            device_info = p.get_device_info_by_index(i)
            if device_info['maxInputChannels'] > 0:
                device_name = device_info['name']
                if device_name not in list_microphones:
                    list_microphones.append(device_name)
                    self.microphone_combobox.addItem(device_name)

        self.microphone_combobox.setCurrentIndex(1)  # define o padrão do windows

    def send_data_to_zabbix_trapper(self, valor):
        try:
            metrics = ZabbixMetric(str(self.zabbix_host), "app.lista_valores", valor)
            sender = ZabbixSender(self.zabbix_server, int(self.zabbix_port))
            sender.send([metrics])
            self.update_log(f'Ultimo valor enviado para o zabbix: {valor}')

        except:
            self.update_log('Coloque uma configuração valida ao zabbix trapper')
            try:
                self.zabbix_server, self.zabbix_port, self.zabbix_host = self.read_config_ini()
            except Exception as e:
                self.update_log(f"FALHA ao ler arquivo config.ini - \n {e}")

    def update_plot(self):
        self.equalizer.setValues([self.data.mean() ** 2,
                                  self.data.mean() ** 1.5])

    def current(self):
        current = self.microphone_combobox.currentIndex()

        p = pyaudio.PyAudio()
        # init
        stream = p.open(input_device_index=0,
                        format=pyaudio.paInt16,
                        channels=2,
                        rate=self.RATE,
                        input=True,
                        frames_per_buffer=self.CHUNK)

        while True:
            if not self.looping_running:
                print("BREAK")
                break

            last = self.microphone_combobox.currentIndex()
            if current != last:
                current = last
                print(current)
                p.close(stream)
                p = pyaudio.PyAudio()
                # print('change')
                try:
                    stream = p.open(input_device_index=current,
                                    format=pyaudio.paInt16,
                                    channels=2,
                                    rate=self.RATE,
                                    input=True,
                                    frames_per_buffer=self.CHUNK)
                    print('estereo')

                except OSError:
                    stream = p.open(input_device_index=current,
                                    format=pyaudio.paInt16,
                                    channels=1,
                                    rate=self.RATE,
                                    input=True,
                                    frames_per_buffer=self.CHUNK)
                    print('mono')

            else:
                try:
                    time.sleep(0.5)

                    if stream.get_read_available() > 1:
                        self.update_log("")

                        # print(stream)
                        stream_data = stream.read(self.CHUNK)
                        data = np.frombuffer(stream_data, dtype=np.int16)
                        # peak = np.average(np.abs(data)) * 2
                        # zabbix_data = int(50 * peak / 2 ** 16)
                        # data = (data - 0) / (np.max(data) - 0)
                        data = (np.average(np.abs(data))) * 0.01
                        # print(data)
                        self.data[:-1] = self.data[1:]  # Shift dos valores para a esquerda
                        self.data[-1] = data

                        self.send_data_to_zabbix_trapper(int(data))

                    else:
                        self.update_log("Troca o microfone, impossivel de ler" + str(current))
                except Exception as e:
                    self.update_log(f"FALHA reinicie o app pelo gerenciador de tarefas\n {e}")


def single_instance():
    # Caminho para o arquivo de travamento
    lock_file = os.path.join(tempfile.gettempdir(), 'app.lock')

    try:
        # cria o arquivo de travamento
        lock_fd = os.open(lock_file, os.O_CREAT | os.O_EXCL | os.O_RDWR)
    except OSError:
        print("O programa já está em execução.")
        return False

    # Se chegarmos aqui, significa que somos a única instância do programa
    print("O programa está sendo executado...")

    os.close(lock_fd)
    os.unlink(lock_file)

    return True


if __name__ == "__main__":
    if single_instance():
        Autoparse()
