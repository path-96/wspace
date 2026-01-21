from flask import Blueprint, render_template, request, redirect, url_for, session, jsonify, current_app
from app import db
from app.models import Note, Folder
from app.services.gdrive_service import GDriveService

bp = Blueprint('sync', __name__, url_prefix='/sync')


@bp.route('/')
def sync_status():
    """Show sync status."""
    credentials = session.get('gdrive_credentials')
    is_connected = credentials is not None

    notes_count = Note.query.count()
    synced_count = Note.query.filter_by(sync_status='synced').count()
    local_count = Note.query.filter_by(sync_status='local').count()
    conflict_count = Note.query.filter_by(sync_status='conflict').count()

    status = {
        'connected': is_connected,
        'total': notes_count,
        'synced': synced_count,
        'local': local_count,
        'conflicts': conflict_count
    }

    if request.headers.get('HX-Request'):
        return render_template('partials/sync_status.html', status=status)
    return jsonify(status)


@bp.route('/connect')
def connect():
    """Start OAuth flow for Google Drive."""
    client_id = current_app.config.get('GOOGLE_CLIENT_ID')
    if not client_id:
        return render_template('partials/sync_error.html',
                             error='Google Drive not configured. Set GOOGLE_CLIENT_ID in .env')

    service = GDriveService(current_app.config)
    auth_url = service.get_auth_url()
    return redirect(auth_url)


@bp.route('/oauth/callback')
def oauth_callback():
    """Handle OAuth callback from Google."""
    code = request.args.get('code')
    if not code:
        return redirect(url_for('notes.index'))

    try:
        service = GDriveService(current_app.config)
        credentials = service.handle_callback(code)
        session['gdrive_credentials'] = credentials
        return redirect(url_for('notes.index'))
    except Exception as e:
        return render_template('partials/sync_error.html', error=str(e))


@bp.route('/disconnect', methods=['POST'])
def disconnect():
    """Disconnect Google Drive."""
    session.pop('gdrive_credentials', None)
    if request.headers.get('HX-Request'):
        return render_template('partials/sync_status.html', status={'connected': False})
    return redirect(url_for('notes.index'))


@bp.route('/sync-all', methods=['POST'])
def sync_all():
    """Sync all notes with Google Drive."""
    credentials = session.get('gdrive_credentials')
    if not credentials:
        return jsonify({'error': 'Not connected to Google Drive'}), 401

    try:
        service = GDriveService(current_app.config, credentials)

        # Get or create Notes folder in Drive
        folder_id = service.get_or_create_notes_folder()

        # Sync local notes to Drive
        notes = Note.query.filter_by(sync_status='local').all()
        for note in notes:
            filename = f"{note.title}.{note.file_type}"
            if note.gdrive_id:
                service.update_file(note.gdrive_id, note.content, filename)
            else:
                note.gdrive_id = service.upload_file(note.content, filename, folder_id)
            note.sync_status = 'synced'

        db.session.commit()

        # Update credentials in session (they may have been refreshed)
        session['gdrive_credentials'] = service.get_credentials_dict()

        return sync_status()
    except Exception as e:
        if request.headers.get('HX-Request'):
            return render_template('partials/sync_error.html', error=str(e))
        return jsonify({'error': str(e)}), 500


@bp.route('/sync-note/<int:note_id>', methods=['POST'])
def sync_note(note_id):
    """Sync a single note with Google Drive."""
    credentials = session.get('gdrive_credentials')
    if not credentials:
        return jsonify({'error': 'Not connected to Google Drive'}), 401

    note = Note.query.get_or_404(note_id)

    try:
        service = GDriveService(current_app.config, credentials)
        folder_id = service.get_or_create_notes_folder()

        filename = f"{note.title}.{note.file_type}"
        if note.gdrive_id:
            service.update_file(note.gdrive_id, note.content, filename)
        else:
            note.gdrive_id = service.upload_file(note.content, filename, folder_id)

        note.sync_status = 'synced'
        db.session.commit()

        session['gdrive_credentials'] = service.get_credentials_dict()

        if request.headers.get('HX-Request'):
            return render_template('partials/note_sync_status.html', note=note)
        return jsonify({'status': 'synced', 'gdrive_id': note.gdrive_id})
    except Exception as e:
        if request.headers.get('HX-Request'):
            return render_template('partials/sync_error.html', error=str(e))
        return jsonify({'error': str(e)}), 500
