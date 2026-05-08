from flask import Flask, render_template
from flask_cors import CORS
import psycopg2
from psycopg2.extras import RealDictCursor

app = Flask(__name__)
CORS(app)

def get_db_connection():
    return psycopg2.connect(
        host="localhost",
        database="postgres",
        user="postgres",
        password="HETIC2026"
    )

app.get_db_connection = get_db_connection

from routes.produits     import produits_bp
from routes.commandes    import commandes_bp
from routes.utilisateurs import utilisateurs_bp
from routes.stock        import stock_bp
from routes.previsions   import previsions_bp

app.register_blueprint(produits_bp)
app.register_blueprint(commandes_bp)
app.register_blueprint(utilisateurs_bp)
app.register_blueprint(stock_bp)
app.register_blueprint(previsions_bp)

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/admin')
def admin():
    return render_template('admin.html')

@app.route('/login')
def login():
    return render_template('login.html')

@app.route('/signup')
def signup():
    return render_template('signup.html')

if __name__ == '__main__':
    app.run(debug=True, port=5000)