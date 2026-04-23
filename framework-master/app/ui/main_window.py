import sys
from PyQt6.QtWidgets import (
    QApplication,
    QMainWindow,
    QWidget,
    QHBoxLayout,
    QStackedWidget,
)
from components.sidebar import Sidebar
from app.ui.pages.topology.topology_page import TopologyPage
from pages.chat_page import ChatPage


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("MAS APR Framework")
        self.resize(1000, 700)

        # Central layout
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QHBoxLayout(central_widget)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # Components
        self.sidebar = Sidebar()
        self.stacked_widget = QStackedWidget()

        # Pages
        self.topology_page = TopologyPage()
        self.chat_page = ChatPage()

        self.stacked_widget.addWidget(self.topology_page)  # Index 0
        self.stacked_widget.addWidget(self.chat_page)  # Index 1

        # Add to layout
        main_layout.addWidget(self.sidebar)
        main_layout.addWidget(self.stacked_widget)

        # Connect sidebar signals to page switching
        self.sidebar.page_changed.connect(self.stacked_widget.setCurrentIndex)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow()
    window.showMaximized() 
    sys.exit(app.exec())