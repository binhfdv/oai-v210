# main.py
import threading
import os
from app_server import app
import orchestrator
import logging

logging.basicConfig(level=logging.INFO)

def run_flask():
    # Use threaded True to allow concurrent requests if needed.
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("HTTP_PORT", "5000"))
    app.run(host=host, port=port, threaded=True)

if __name__ == "__main__":
    # start orchestrator in main thread and Flask in a background thread,
    # or vice-versa. We'll run Flask in background and orchestrator in main thread so any crash is visible.
    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()
    # Now start orchestrator main loop (blocking)
    orchestrator.main()
