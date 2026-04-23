from paths import WORKFLOW_JSON
from app.src.utils.json import get_nodes_data
from PyQt6.QtWidgets import (
    QGraphicsView,
    QGraphicsScene,
    QGraphicsEllipseItem,
    QGraphicsLineItem,
    QGraphicsTextItem,
    QGraphicsPathItem,
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QPen, QBrush, QColor, QPainterPath


# TODO find a library to paint graph
class AgentNode(QGraphicsEllipseItem):
    def __init__(self, node_id, x, y, name, role, details, callback):
        super().__init__(-25, -25, 50, 50)  # Centered at x,y with 50x50 size
        self.setPos(x, y)
        self.setBrush(QBrush(QColor("#4CAF50")))
        self.setPen(QPen(Qt.GlobalColor.black, 2))
        self.setFlag(QGraphicsEllipseItem.GraphicsItemFlag.ItemIsSelectable)

        # Store agent data
        self.node_id = node_id  # Matches the .json filename
        self.agent_name = name
        self.agent_role = role
        self.agent_details = details
        self.callback = callback

        # Add label
        label = QGraphicsTextItem(name, self)
        label.setPos(-20, 25)

    def mousePressEvent(self, event):
        super().mousePressEvent(event)
        # Emit all data including the ID to the graph/page
        self.callback(
            self.node_id, self.agent_name, self.agent_role, self.agent_details
        )


class AgentGraph(QGraphicsView):
    # Signal signature: node_id, name, role, details
    node_clicked = pyqtSignal(str, str, str, str)

    def __init__(self):
        super().__init__()
        self.scene = QGraphicsScene(self)
        self.setScene(self.scene)
        self.setRenderHint(self.renderHints().Antialiasing)

        # Interactivity: Pan and drag
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)

        self.setup_topology()

    def setup_topology(self):
        workflow_data = get_nodes_data(WORKFLOW_JSON)
        nodes_list = workflow_data.get("nodes", [])
        edges_list = workflow_data.get("edges", [])

        nodes = {}

        for d in nodes_list:
            node = AgentNode(
                d["id"],
                d["x"],
                d["y"],
                d["name"],
                d["role"],
                d["details"],
                self.emit_node_clicked,
            )
            self.scene.addItem(node)
            nodes[d["id"]] = node

        for edge in edges_list:
            s_node = nodes.get(edge["source"])
            t_node = nodes.get(edge["target"])

            if s_node and t_node:
                start_pt = s_node.scenePos()
                end_pt = t_node.scenePos()

                path = QPainterPath()
                path.moveTo(start_pt)

                mid_x = (start_pt.x() + end_pt.x()) / 2
                mid_y = (start_pt.y() + end_pt.y()) / 2

                dist = (
                    (end_pt.x() - start_pt.x()) ** 2 + (end_pt.y() - start_pt.y()) ** 2
                ) ** 0.5
                offset = dist * 0.2

                control_pt_y = mid_y - offset

                path.quadTo(mid_x, control_pt_y, end_pt.x(), end_pt.y())

                edge_item = QGraphicsPathItem(path)
                edge_item.setPen(QPen(QColor("#3498db"), 2, Qt.PenStyle.SolidLine))
                edge_item.setZValue(-1)

                edge_item.setOpacity(0.6)

                self.scene.addItem(edge_item)

    def emit_node_clicked(self, node_id, name, role, details):
        self.node_clicked.emit(node_id, name, role, details)

    def wheelEvent(self, event):
        zoom_in_factor = 1.25
        zoom_out_factor = 1 / zoom_in_factor
        zoom_factor = zoom_in_factor if event.angleDelta().y() > 0 else zoom_out_factor
        self.scale(zoom_factor, zoom_factor)
