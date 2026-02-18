import os
import atexit
from flask import Flask
from config import SECRET_KEY, close_db_pool

app = Flask(__name__)
app.secret_key = SECRET_KEY

from routes.auth import auth
from routes.quiz import quiz
from routes.dashboard import dashboard

app.register_blueprint(auth)
app.register_blueprint(quiz)
app.register_blueprint(dashboard)

# Register cleanup function to close database pool on shutdown
atexit.register(close_db_pool)

if __name__ == "__main__":
    debug_mode = os.environ.get("FLASK_DEBUG", "False").lower() == "true"
    host = os.environ.get("FLASK_HOST", "127.0.0.1")
    port = int(os.environ.get("FLASK_PORT", "5000"))
    app.run(debug=debug_mode, host=host, port=port)
