from flask import Blueprint, render_template, request, jsonify, g
from app.services.search_service import search_notes
from app.routes.auth import login_required, get_current_user

bp = Blueprint('search', __name__, url_prefix='/search')


@bp.before_request
def load_user():
    """Load current user before each request."""
    g.user = get_current_user()


@bp.route('/')
@login_required
def search():
    """Full-text search across notes."""
    query = request.args.get('q', '').strip()
    if not query:
        if request.headers.get('HX-Request'):
            return render_template('partials/search_results.html', results=[], query='')
        return jsonify([])

    results = search_notes(query, user_id=g.user.id)

    if request.headers.get('HX-Request'):
        return render_template('partials/search_results.html', results=results, query=query)
    return jsonify(results)
