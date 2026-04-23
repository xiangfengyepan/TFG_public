import os
import json
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QFrame, QLabel, QLineEdit, QPushButton, 
    QFormLayout, QScrollArea, QTextEdit, QSpinBox, QDoubleSpinBox, QMessageBox
)

class DetailsPanel(QFrame):
    def __init__(self, config_dir, save_callback, reset_callback, ranges):
        super().__init__()
        self.config_dir = config_dir
        self.save_callback = save_callback
        self.reset_callback = reset_callback
        self.ranges = ranges
        self.param_inputs = {}
        
        self.setFixedWidth(350)
        self.setup_ui()

    def setup_ui(self):
        self.setStyleSheet("""
            QFrame { background-color: #ffffff; border-left: 1px solid #dcdde1; }
            
            QLabel { 
                color: #2f3640; 
                font-family: 'Segoe UI', sans-serif; 
                padding-left: 10px;
                padding-right: 10px;
            }
            
            QLineEdit, QSpinBox, QDoubleSpinBox { 
                background-color: #f5f6fa; 
                color: #000000; 
                border: 1px solid #dcdde1; 
                border-radius: 4px;
                padding: 6px;
                font-weight: 500;
            }

            /* --- COLORES DE ALTO CONTRASTE --- */
            QSpinBox::up-button, QDoubleSpinBox::up-button {
                background-color: #00b894; /* Verde Esmeralda */
                width: 25px;
                border-top-right-radius: 4px;
                border-left: 1px solid #dcdde1;
            }
            QSpinBox::down-button, QDoubleSpinBox::down-button {
                background-color: #0984e3; /* Azul Royal */
                width: 25px;
                border-bottom-right-radius: 4px;
                border-left: 1px solid #dcdde1;
                border-top: 1px solid #ffffff;
            }

            QSpinBox::up-button:hover { background-color: #55efc4; }
            QSpinBox::down-button:hover { background-color: #74b9ff; }

            QPushButton#save_btn { 
                background-color: #2ecc71; color: white; padding: 12px; 
                font-weight: bold; border-radius: 8px; border: none; 
            }
            QPushButton#reset_btn { 
                color: #e67e22; border: 1px solid #e67e22; padding: 8px; 
                border-radius: 8px; background-color: transparent;
            }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(15, 20, 15, 20)
        
        self.title_label = QLabel("Select an agent")
        self.title_label.setStyleSheet("font-weight: bold; font-size: 18px; color: #1e272e;")
        
        self.role_label = QLabel("")
        self.role_label.setStyleSheet("color: #7f8c8d; font-style: italic; margin-bottom: 5px;")

        self.desc_label = QTextEdit()
        self.desc_label.setReadOnly(True)
        self.desc_label.setMaximumHeight(80)
        self.desc_label.setStyleSheet("background-color: #f8f9fa; border-radius: 5px; border: 1px solid #f1f2f6;")

        layout.addWidget(self.title_label)
        layout.addWidget(self.role_label)
        layout.addWidget(self.desc_label)
        layout.addSpacing(15)
        
        layout.addWidget(QLabel("<b>HYPERPARAMETERS</b>"))

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.config_container = QWidget()
        self.config_form = QFormLayout(self.config_container)
        self.scroll.setWidget(self.config_container)
        layout.addWidget(self.scroll)

        self.save_btn = QPushButton("Save Changes")
        self.save_btn.setObjectName("save_btn")
        self.save_btn.clicked.connect(self.handle_save)
        self.save_btn.setEnabled(False)

        self.reset_btn = QPushButton("Restore Defaults")
        self.reset_btn.setObjectName("reset_btn")
        self.reset_btn.clicked.connect(self.handle_reset)
        self.reset_btn.setEnabled(False)

        layout.addWidget(self.save_btn)
        layout.addWidget(self.reset_btn)

    def load_node_config(self, filename):
        while self.config_form.count():
            item = self.config_form.takeAt(0)
            if item.widget(): item.widget().deleteLater()

        self.param_inputs = {}
        path = os.path.join(self.config_dir, filename)

        if os.path.exists(path):
            with open(path, "r") as f:
                data = json.load(f)
                for key, value in data.items():
                    # Usar el argumento de visibilidad (índice 3)
                    range_cfg = self.ranges.get(key, (0, 1000, 1, True))
                    
                    if len(range_cfg) > 3 and not range_cfg[3]:
                        continue

                    min_val, max_val, step = range_cfg[0], range_cfg[1], range_cfg[2]
                    label = QLabel(f"{key}:")

                    if isinstance(value, float):
                        input_w = QDoubleSpinBox()
                        input_w.setRange(min_val, max_val)
                        input_w.setSingleStep(step)
                        input_w.setValue(value)
                    elif isinstance(value, int) and not isinstance(value, bool):
                        input_w = QSpinBox()
                        input_w.setRange(int(min_val), int(max_val))
                        input_w.setValue(value)
                    else:
                        # Representar listas como texto separado por comas para la UI
                        text_val = ", ".join(value) if isinstance(value, list) else str(value if value is not None else "")
                        input_w = QLineEdit(text_val)
                    
                    input_w.setFixedWidth(110)
                    self.config_form.addRow(label, input_w)
                    self.param_inputs[key] = (input_w, type(value))
            
            self.save_btn.setEnabled(True)
            self.reset_btn.setEnabled(True)

    def handle_save(self):
        self.save_callback()
        QMessageBox.information(self, "Success", "Agent hyperparameters updated.")

    def handle_reset(self):
        self.reset_callback()
        QMessageBox.warning(self, "Restored", "Defaults restored.")