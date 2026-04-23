from PyQt6.QtWidgets import QFrame, QVBoxLayout, QPushButton, QSizePolicy
from PyQt6.QtCore import pyqtSignal, Qt


class Sidebar(QFrame):
    page_changed = pyqtSignal(int)

    def __init__(self):
        super().__init__()
        self.is_expanded = True
        self.setFixedWidth(200)
        self.setStyleSheet("background-color: #2b2b2b; color: white;")

        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        # Toggle Button
        self.toggle_btn = QPushButton("☰")
        self.toggle_btn.clicked.connect(self.toggle_sidebar)
        layout.addWidget(self.toggle_btn)

        # Page Buttons
        self.topo_btn = QPushButton("Topology")
        # self.topo_btn.setIcon(QIcon("path/to/topology_icon.png")) #TODO: Add actual icon path
        self.topo_btn.clicked.connect(lambda: self.page_changed.emit(0))

        self.chat_btn = QPushButton("Chat")
        # self.chat_btn.setIcon(QIcon("path/to/chat_icon.png")) #TODO: Add actual icon path
        self.chat_btn.clicked.connect(lambda: self.page_changed.emit(1))

        layout.addWidget(self.topo_btn)
        layout.addWidget(self.chat_btn)

    def toggle_sidebar(self):
        if self.is_expanded:
            self.setFixedWidth(60)
            self.toggle_btn.setText("☰")
            self.topo_btn.setText("")  # Hide text, rely on icon later
            self.chat_btn.setText("")
        else:
            self.setFixedWidth(200)
            self.toggle_btn.setText("☰")
            self.topo_btn.setText("Topology")
            self.chat_btn.setText("Chat")
        self.is_expanded = not self.is_expanded
