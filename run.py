from app import create_app
from app.config import Config

app = create_app()

if __name__ == "__main__":
    try:
        port = int(Config.PORT)
    except (TypeError, ValueError):
        port = 5015
    app.run(debug=True, port=port)
