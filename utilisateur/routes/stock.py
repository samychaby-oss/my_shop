from flask import Blueprint, jsonify, request, current_app
from psycopg2.extras import RealDictCursor

stock_bp = Blueprint('stock', __name__, url_prefix='/api')

def get_db():
    return current_app.get_db_connection()

# ── GET alertes stock ────────────────────────────────────────
@stock_bp.route('/stock/alertes', methods=['GET'])
def get_alertes():
    try:
        conn = get_db()
        cur  = conn.cursor(cursor_factory=RealDictCursor)

        # Ruptures
        cur.execute('SELECT COUNT(*) AS total FROM public.produits WHERE stock = 0 AND actif = TRUE')
        out_of_stock = cur.fetchone()['total']

        # Stock bas
        cur.execute('SELECT COUNT(*) AS total FROM public.produits WHERE stock > 0 AND stock <= seuil_alerte AND actif = TRUE')
        low_stock = cur.fetchone()['total']

        # Valeur totale
        cur.execute('SELECT COALESCE(SUM(prix * stock), 0) AS total FROM public.produits WHERE actif = TRUE')
        total_value = cur.fetchone()['total']

        cur.close(); conn.close()
        return jsonify({
            'outOfStock': int(out_of_stock),
            'lowStock':   int(low_stock),
            'totalValue': float(total_value),
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ── GET tous les produits avec stock ────────────────────────
@stock_bp.route('/stock', methods=['GET'])
def get_stock():
    try:
        conn = get_db()
        cur  = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute('''
            SELECT id, nom, categorie, prix, stock, seuil_alerte, actif
            FROM public.produits
            ORDER BY stock ASC, nom ASC
        ''')
        items = cur.fetchall()
        cur.close(); conn.close()
        return jsonify(list(items))
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ── PUT modifier prix et stock d'un produit ──────────────────
@stock_bp.route('/stock/<int:produit_id>', methods=['PUT'])
def update_stock(produit_id):
    try:
        data = request.get_json()
        conn = get_db()
        cur  = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute('''
            UPDATE public.produits
            SET prix  = COALESCE(%s, prix),
                stock = COALESCE(%s, stock)
            WHERE id = %s
            RETURNING id, nom, prix, stock, seuil_alerte
        ''', (
            data.get('prix'),
            data.get('stock'),
            produit_id,
        ))
        produit = cur.fetchone()
        conn.commit()
        cur.close(); conn.close()
        if not produit:
            return jsonify({'error': 'Produit introuvable'}), 404
        return jsonify(dict(produit))
    except Exception as e:
        return jsonify({'error': str(e)}), 500