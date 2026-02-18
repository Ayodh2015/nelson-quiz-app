from flask import Flask
from config import SECRET_KEY

app = Flask(__name__)
app.secret_key = SECRET_KEY

from routes.auth import auth
from routes.quiz import quiz
from routes.dashboard import dashboard

app.register_blueprint(auth)
app.register_blueprint(quiz)
app.register_blueprint(dashboard)

if __name__ == "__main__":
    app.run(debug=True)
