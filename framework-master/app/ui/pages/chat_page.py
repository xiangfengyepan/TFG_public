from app.ui.utils.workflow_worker import WorkflowWorker
from app.src.tools.terminal_tool import CommandApprovalDecision, TerminalTool
from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QTextEdit,
    QPushButton,
    QLabel,
    QProgressBar,
    QFileDialog,
    QMessageBox,
)
from PyQt6.QtCore import Qt
from pathlib import Path
import re


FIXED_APR_PROMPT = "Fix bugs that may cause crashes or failing tests."
PROJECT_ROOT = Path(__file__).resolve().parents[3]
ENV_FILE = PROJECT_ROOT / "app" / ".env"


class ChatPage(QWidget):
    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)

        self.show_thinking = True
        self.latest_stream_text = ""
        self.latest_final_text = ""
        self.selected_root = self._load_root_from_env() or ""

        self.setStyleSheet(
            """
            QWidget { background-color: #f6f8fb; color: #1f2937; }
            QTextEdit {
                background-color: #ffffff;
                border: 1px solid #d0d7e2;
                border-radius: 8px;
                font-family: Consolas, 'Courier New', monospace;
                font-size: 10pt;
                padding: 10px;
            }
            QPushButton {
                background-color: #2563eb;
                color: white;
                border: none;
                border-radius: 6px;
                padding: 8px 12px;
                font-weight: 600;
            }
            QPushButton:disabled { background-color: #94a3b8; }
            QLabel#mutedLabel { color: #4b5563; }
            """
        )

        top_controls = QHBoxLayout()
        self.folder_label = QLabel("")
        self.folder_label.setObjectName("mutedLabel")
        self._refresh_folder_label()

        self.select_folder_btn = QPushButton("Select Root Folder")
        self.select_folder_btn.clicked.connect(self.select_root_folder)

        self.toggle_thinking_btn = QPushButton("Hide Thinking")
        self.toggle_thinking_btn.clicked.connect(self.toggle_thinking_visibility)

        self.run_btn = QPushButton("Run Workflow")
        self.run_btn.clicked.connect(self.send_message)

        top_controls.addWidget(self.select_folder_btn)
        top_controls.addWidget(self.toggle_thinking_btn)
        top_controls.addWidget(self.run_btn)
        layout.addLayout(top_controls)
        layout.addWidget(self.folder_label)

        self.output_box = QTextEdit()
        self.output_box.setReadOnly(True)
        self.output_box.setPlaceholderText("Workflow stream and final result will appear here...")
        layout.addWidget(QLabel("<b>Workflow Output</b>"))
        layout.addWidget(self.output_box, stretch=1)

        # Progress and Controls
        self.status_layout = QHBoxLayout()
        self.status_label = QLabel("Ready")
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 0)
        self.progress_bar.hide()

        self.status_layout.addWidget(self.status_label)
        self.status_layout.addWidget(self.progress_bar)
        layout.addLayout(self.status_layout)

        # Wire command-approval popup for tool execution from UI
        TerminalTool.set_approval_callback(self._ask_command_approval)

    def _load_root_from_env(self) -> str:
        if not ENV_FILE.exists():
            return ""
        try:
            text = ENV_FILE.read_text(encoding="utf-8")
        except Exception:
            return ""
        match = re.search(r"^ROOT_DIR=(.*)$", text, flags=re.MULTILINE)
        if not match:
            return ""
        value = match.group(1).split("#", 1)[0].strip()
        return value

    def _write_root_to_env(self, root_path: str) -> None:
        root_norm = str(Path(root_path).resolve())
        text = ""
        if ENV_FILE.exists():
            try:
                text = ENV_FILE.read_text(encoding="utf-8")
            except Exception:
                text = ""
        new_line = f"ROOT_DIR={root_norm}"
        if re.search(r"^ROOT_DIR=.*$", text, flags=re.MULTILINE):
            updated = re.sub(r"^ROOT_DIR=.*$", new_line, text, flags=re.MULTILINE)
        elif text.strip():
            updated = text.rstrip() + "\n" + new_line + "\n"
        else:
            updated = new_line + "\n"
        ENV_FILE.write_text(updated, encoding="utf-8")
        self.selected_root = root_norm
        self._refresh_folder_label()

    def _refresh_folder_label(self):
        if self.selected_root:
            self.folder_label.setText(f"ROOT_DIR: {self.selected_root}")
        else:
            self.folder_label.setText("ROOT_DIR not set. Please select a folder.")

    def select_root_folder(self):
        current = self.selected_root or str(PROJECT_ROOT)
        folder = QFileDialog.getExistingDirectory(self, "Select APR Root Folder", current)
        if not folder:
            return
        self._write_root_to_env(folder)
        self.status_label.setText("Repository root updated.")

    def toggle_thinking_visibility(self):
        self.show_thinking = not self.show_thinking
        self.toggle_thinking_btn.setText("Hide Thinking" if self.show_thinking else "Show Thinking")
        self._render_output_box()

    def _ask_command_approval(self, command: str) -> str:
        msg = QMessageBox(self)
        msg.setIcon(QMessageBox.Icon.Question)
        msg.setWindowTitle("Approve Terminal Command")
        msg.setText("The agent wants to run a terminal command:")
        msg.setInformativeText(command)
        allow_once_btn = msg.addButton("Allow Once", QMessageBox.ButtonRole.AcceptRole)
        allow_always_btn = msg.addButton(
            "Allow + Add to Allowlist", QMessageBox.ButtonRole.AcceptRole
        )
        deny_btn = msg.addButton("Deny", QMessageBox.ButtonRole.RejectRole)
        msg.setDefaultButton(deny_btn)
        msg.exec()
        clicked = msg.clickedButton()
        if clicked == allow_always_btn:
            return CommandApprovalDecision.ALLOW_ALWAYS
        if clicked == allow_once_btn:
            return CommandApprovalDecision.ALLOW_ONCE
        return CommandApprovalDecision.DENY

    def _render_output_box(self):
        parts = []
        if self.show_thinking and self.latest_stream_text.strip():
            parts.append(self.latest_stream_text.rstrip())
        if self.latest_final_text.strip():
            if parts:
                parts.append("\n=== FINAL RESULT ===\n")
            parts.append(self.latest_final_text.rstrip())
        content = "".join(parts).strip()
        self.output_box.setPlainText(content or "No output yet.")
        cursor = self.output_box.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)
        self.output_box.setTextCursor(cursor)

    def send_message(self):
        if not self.selected_root:
            self.status_label.setText("Select a root folder first.")
            return

        # UI Reset
        self.latest_stream_text = ""
        self.latest_final_text = ""
        self.output_box.clear()
        self.run_btn.setEnabled(False)
        self.select_folder_btn.setEnabled(False)
        self.progress_bar.show()
        self.status_label.setText("Consulting Agents...")

        # Initialize Worker
        self.worker = WorkflowWorker(FIXED_APR_PROMPT)
        self.worker.log_received.connect(self.update_thinking_box)
        self.worker.finished.connect(self.display_final_result)

        # Error handling: If the worker fails (like Ollama being down)
        # In a real app, you'd add an 'error' signal to WorkflowWorker
        self.worker.start()

    def update_thinking_box(self, text):
        self.latest_stream_text += text
        if self.show_thinking:
            self._render_output_box()

    def display_final_result(self, final_state):
        self.run_btn.setEnabled(True)
        self.select_folder_btn.setEnabled(True)
        self.progress_bar.hide()
        self.status_label.setText("Done.")

        # LangGraph stream output is a dict keyed by node name
        if not final_state:
            self.latest_final_text = "ERROR: No data received. Is Ollama running?"
            self._render_output_box()
            return

        # Get the dictionary from the last node that executed
        node_name = list(final_state.keys())[0]
        node_data = final_state[node_name]

        # Fill final output (Handling Ollama object)
        resp = node_data.get("response")
        resp_message = getattr(resp, "message", None)
        if isinstance(resp_message, dict):
            final_msg = resp_message.get("content", str(resp))
        else:
            final_msg = str(resp)

        analysis = node_data.get("analysis_details", "")
        final_parts = []
        if analysis:
            final_parts.append("Analysis:\n" + str(analysis).strip())
        final_parts.append("Response:\n" + final_msg.strip())
        self.latest_final_text = "\n\n".join(final_parts).strip()
        self._render_output_box()
