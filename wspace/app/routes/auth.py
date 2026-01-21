from functools import wraps
from flask import Blueprint, redirect, url_for, session, current_app, render_template, request
from google.oauth2 import id_token
from google.auth.transport import requests as google_requests
from google_auth_oauthlib.flow import Flow
from datetime import datetime, timezone
from app import db
from app.models import User

bp = Blueprint('auth', __name__, url_prefix='/auth')

SCOPES = [
    'openid',
    'https://www.googleapis.com/auth/userinfo.email',
    'https://www.googleapis.com/auth/userinfo.profile',
    'https://www.googleapis.com/auth/drive.file',
]


def login_required(f):
    """Decorator to require login for routes."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('auth.login'))
        return f(*args, **kwargs)
    return decorated_function


def get_current_user():
    """Get the currently logged in user."""
    if 'user_id' in session:
        return User.query.get(session['user_id'])
    return None


def _get_flow():
    """Create OAuth flow."""
    client_config = {
        'web': {
            'client_id': current_app.config.get('GOOGLE_CLIENT_ID'),
            'client_secret': current_app.config.get('GOOGLE_CLIENT_SECRET'),
            'auth_uri': 'https://accounts.google.com/o/oauth2/auth',
            'token_uri': 'https://oauth2.googleapis.com/token',
            'redirect_uris': [current_app.config.get('GOOGLE_REDIRECT_URI', 'http://localhost:5000/auth/callback')],
        }
    }
    return Flow.from_client_config(
        client_config,
        scopes=SCOPES,
        redirect_uri=current_app.config.get('GOOGLE_AUTH_REDIRECT_URI', 'http://localhost:5000/auth/callback')
    )


@bp.route('/login')
def login():
    """Show login page or redirect to Google OAuth."""
    if 'user_id' in session:
        return redirect(url_for('notes.index'))

    client_id = current_app.config.get('GOOGLE_CLIENT_ID')
    if not client_id:
        return render_template('auth/login.html', error='Google OAuth not configured. Set GOOGLE_CLIENT_ID in .env')

    return render_template('auth/login.html')


@bp.route('/google')
def google_login():
    """Start Google OAuth flow."""
    client_id = current_app.config.get('GOOGLE_CLIENT_ID')
    if not client_id:
        return redirect(url_for('auth.login'))

    flow = _get_flow()
    auth_url, state = flow.authorization_url(
        access_type='offline',
        include_granted_scopes='true',
        prompt='consent'
    )
    session['oauth_state'] = state
    return redirect(auth_url)


@bp.route('/callback')
def callback():
    """Handle Google OAuth callback."""
    try:
        flow = _get_flow()
        flow.fetch_token(authorization_response=request.url)

        credentials = flow.credentials

        # Get user info from ID token
        id_info = id_token.verify_oauth2_token(
            credentials.id_token,
            google_requests.Request(),
            current_app.config.get('GOOGLE_CLIENT_ID')
        )

        google_id = id_info.get('sub')
        email = id_info.get('email')
        name = id_info.get('name')
        picture = id_info.get('picture')

        # Find or create user
        user = User.query.filter_by(google_id=google_id).first()
        if not user:
            user = User(
                google_id=google_id,
                email=email,
                name=name,
                picture=picture
            )
            db.session.add(user)
        else:
            # Update user info
            user.email = email
            user.name = name
            user.picture = picture
            user.last_login = datetime.now(timezone.utc)

        db.session.commit()

        # Store user in session
        session['user_id'] = user.id
        session['user_email'] = user.email
        session['user_name'] = user.name
        session['user_picture'] = user.picture

        # Store credentials for Drive sync
        session['gdrive_credentials'] = {
            'token': credentials.token,
            'refresh_token': credentials.refresh_token,
            'scopes': list(credentials.scopes) if credentials.scopes else SCOPES,
        }

        # Debug: log granted scopes
        current_app.logger.info(f"Granted scopes: {credentials.scopes}")

        return redirect(url_for('notes.index'))

    except Exception as e:
        current_app.logger.error(f"OAuth callback error: {e}")
        return render_template('auth/login.html', error=str(e))


@bp.route('/logout')
def logout():
    """Log out the current user."""
    session.clear()
    return redirect(url_for('auth.login'))
