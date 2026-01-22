import os
from flask import Blueprint, render_template, request, redirect, url_for, session, jsonify, g
from app import db
from app.models import User
from app.routes.auth import login_required, get_current_user

bp = Blueprint('settings', __name__, url_prefix='/settings')


@bp.before_request
def load_user():
    """Load current user before each request."""
    g.user = get_current_user()


@bp.route('/')
@login_required
def index():
    """Show settings page."""
    return render_template('settings/index.html', user=g.user)


@bp.route('/location', methods=['GET', 'POST'])
@login_required
def set_location():
    """Set or update notes storage location."""
    if request.method == 'POST':
        location = request.form.get('location', '').strip()

        if not location:
            error = 'Please enter a valid path'
            if request.headers.get('HX-Request'):
                return render_template('partials/location_error.html', error=error)
            return render_template('settings/location.html', error=error, user=g.user)

        # Expand user home directory
        location = os.path.expanduser(location)

        # Validate and create directory if needed
        try:
            if not os.path.exists(location):
                os.makedirs(location, exist_ok=True)
            elif not os.path.isdir(location):
                raise ValueError('Path exists but is not a directory')

            # Test write permission
            test_file = os.path.join(location, '.write_test')
            with open(test_file, 'w') as f:
                f.write('test')
            os.remove(test_file)

        except Exception as e:
            error = f'Cannot use this location: {e}'
            if request.headers.get('HX-Request'):
                return render_template('partials/location_error.html', error=error)
            return render_template('settings/location.html', error=error, user=g.user)

        # Save location to user
        g.user.notes_location = location
        db.session.commit()

        # Store in session for quick access
        session['notes_location'] = location

        # Check if this is first-time setup (redirect to pull)
        is_setup = request.form.get('is_setup') == '1'
        if is_setup:
            return redirect(url_for('settings.initial_sync'))

        if request.headers.get('HX-Request'):
            return render_template('partials/location_success.html', location=location)
        return redirect(url_for('settings.index'))

    # GET request - show location form
    return render_template('settings/location.html', user=g.user)


@bp.route('/setup')
@login_required
def setup():
    """First-time setup page for new users."""
    if g.user.notes_location:
        return redirect(url_for('notes.index'))
    return render_template('settings/setup.html', user=g.user)


@bp.route('/initial-sync')
@login_required
def initial_sync():
    """Show initial sync page after location setup."""
    return render_template('settings/initial_sync.html', user=g.user)
