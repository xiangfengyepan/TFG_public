from app.src.core.workflow import build_workflow

from PyQt6.QtCore import QObject, pyqtSignal

class LiveStream(QObject):
    text_written = pyqtSignal(str)

    def write(self, text):
        if text:
            # Send the printed text to the GUI
            self.text_written.emit(str(text))
    
    def flush(self):
        # Required to mimic a standard file stream
        pass

from PyQt6.QtCore import QThread, pyqtSignal
from contextlib import redirect_stdout

class WorkflowWorker(QThread):
    # Signals to communicate back to the UI
    log_received = pyqtSignal(str)
    finished = pyqtSignal(dict)

    def __init__(self, bug_desc):
        super().__init__()
        self.bug_desc = bug_desc

    def run(self):
        # 1. Setup the bridge
        bridge = LiveStream()
        bridge.text_written.connect(self.log_received.emit)
        
        # 2. Redirect all prints during execution
        with redirect_stdout(bridge):
            app = build_workflow()
            initial_state = {
                "task_description": self.bug_desc,
            }
            
            try:
                final_state = app.invoke(initial_state)
            except Exception as e:
                print(f"CRITICAL ERROR: {e}")
                final_state = {} # Prevents the UI from crashing on final_state lookup
            self.finished.emit(final_state)