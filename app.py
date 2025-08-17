from flask import Flask
from flask_cors import CORS
from routes import pi_routes

app = Flask(__name__)
CORS(app)

# Register Blueprints
app.register_blueprint(pi_routes)

if __name__ == "__main__":
    app.run(debug=True)