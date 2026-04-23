from paths import AGENT_CONFIG_DIR

import os
import json
from PyQt6.QtWidgets import (
    QWidget,
    QHBoxLayout,
    QSpinBox,
    QDoubleSpinBox,
)
from components.agent_graph import AgentGraph
from .details_panel import DetailsPanel

class TopologyPage(QWidget):
    def __init__(self):
        super().__init__()
        self.config_dir = AGENT_CONFIG_DIR
        self.current_node_id = None

        self.ranges = {
            "temperature": (0.0, 2.0, 0.1, True),
            "top_k": (0, 100, 1, True),
            "top_p": (0.0, 1.0, 0.05, True),
            "min_p": (0.0, 1.0, 0.05, True),
            "repeat_penalty": (0.0, 2.0, 0.1, True),
            "repeat_last_n": (0, 512, 8, True),
            "seed": (0, 999999, 1, True),
            "num_predict": (-1, 8192, 1, True),
            "stop": (None, None, None, False),
        }
        layout = QHBoxLayout(self)

        self.graph_view = AgentGraph()
        self.graph_view.node_clicked.connect(self.update_details)
        layout.addWidget(self.graph_view, stretch=3)

        self.details_panel = DetailsPanel(
            self.config_dir,
            self.save_current_config,
            self.restore_defaults,
            self.ranges,
        )
        layout.addWidget(self.details_panel, stretch=1)

    def update_details(self, node_id, name, role, details):
        self.current_node_id = node_id
        self.details_panel.title_label.setText(name)
        self.details_panel.role_label.setText(role)
        self.details_panel.desc_label.setText(details)
        self.details_panel.load_node_config(f"{node_id}.json")

    def save_current_config(self):
        if not self.current_node_id: return
        
        updated_data = {}
        for key, (widget, data_type) in self.details_panel.param_inputs.items():
            if isinstance(widget, QDoubleSpinBox):
                updated_data[key] = round(widget.value(), 3)
            elif isinstance(widget, QSpinBox):
                updated_data[key] = widget.value()
            else:
                val_str = widget.text().strip()
                
                if key == "stop":
                    if not val_str:
                        updated_data[key] = None # null en JSON
                    else:
                        updated_data[key] = [s.strip() for s in val_str.split(",") if s.strip()]
                else:
                    updated_data[key] = val_str

        path = os.path.join(self.config_dir, f"{self.current_node_id}.json")
        with open(path, "w") as f:
            json.dump(updated_data, f, indent=2)
            
    def restore_defaults(self):
        if not self.current_node_id:
            return
        self.details_panel.load_node_config(f"{self.current_node_id}_default.json")
        self.save_current_config()