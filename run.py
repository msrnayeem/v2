# run.py
from app import create_app

# create app object
app = create_app()
application = app

    
if __name__ == "__main__":
    app.run(debug=True, port=5000, host="0.0.0.0")
