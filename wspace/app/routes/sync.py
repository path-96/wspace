from datetime import datetime, timezone
from flask import Blueprint, render_template, request, redirect, url_for, session, jsonify, current_app, g
from app import db
from app.models import Note, Folder
from app.services.gdrive_service import GDriveService
from app.services.file_storage import FileStorageService
from app.routes.auth import login_required, get_current_user

bp = Blueprint('sync', __name__, url_prefix='/sync')


@bp.before_request
def load_user():
    """Load current user before each request."""
    g.user = get_current_user()


def get_folder_path(folder):
    """Get folder path as list of names from root to folder."""
    if not folder:
        return []
    path = []
    current = folder
    while current:
        path.insert(0, current.name)
        current = current.parent
    return path


def get_or_create_folder_by_path(path_parts, user_id):
    """Get or create a local folder by path, creating parents as needed."""
    if not path_parts:
        return None

    parent = None
    for name in path_parts:
        folder = Folder.query.filter_by(name=name, parent_id=parent.id if parent else None, user_id=user_id).first()
        if not folder:
            folder = Folder(name=name, parent_id=parent.id if parent else None, user_id=user_id)
            db.session.add(folder)
            db.session.flush()
        parent = folder

    return parent


def parse_drive_time(time_str):
    """Parse Google Drive timestamp to datetime."""
    if not time_str:
        return None
    try:
        # Handle format: 2024-01-15T10:30:00.000Z
        return datetime.fromisoformat(time_str.replace('Z', '+00:00'))
    except:
        return None


@bp.route('/')
@login_required
def sync_status():
    """Show sync status."""
    credentials = session.get('gdrive_credentials')
    is_connected = credentials is not None

    notes_count = Note.query.filter_by(user_id=g.user.id).count()
    synced_count = Note.query.filter_by(user_id=g.user.id, sync_status='synced').count()
    local_count = Note.query.filter_by(user_id=g.user.id, sync_status='local').count()
    conflict_count = Note.query.filter_by(user_id=g.user.id, sync_status='conflict').count()

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
@login_required
def disconnect():
    """Disconnect Google Drive."""
    session.pop('gdrive_credentials', None)
    if request.headers.get('HX-Request'):
        return render_template('partials/sync_status.html', status={'connected': False})
    return redirect(url_for('notes.index'))


@bp.route('/sync-all', methods=['POST'])
@login_required
def sync_all():
    """Push all local changes to Google Drive."""
    credentials = session.get('gdrive_credentials')
    if not credentials:
        return jsonify({'error': 'Not connected to Google Drive'}), 401

    try:
        service = GDriveService(current_app.config, credentials)
        root_folder_id = service.get_or_create_notes_folder()

        # Only sync notes marked as 'local' (changed since last sync)
        notes = Note.query.filter_by(user_id=g.user.id, sync_status='local').all()
        for note in notes:
            # Get target folder in Drive
            if note.folder:
                folder_path = get_folder_path(note.folder)
                target_folder_id = service.get_or_create_folder_path(folder_path, root_folder_id)
                if not note.folder.gdrive_id:
                    note.folder.gdrive_id = target_folder_id
            else:
                target_folder_id = root_folder_id

            filename = f"{note.title}.{note.file_type}"
            if note.gdrive_id:
                service.update_file(note.gdrive_id, note.content, filename, target_folder_id)
            else:
                note.gdrive_id = service.upload_file(note.content, filename, target_folder_id)

            note.sync_status = 'synced'
            note.gdrive_modified = datetime.now(timezone.utc)

        db.session.commit()
        session['gdrive_credentials'] = service.get_credentials_dict()

        return sync_status()
    except Exception as e:
        if request.headers.get('HX-Request'):
            return render_template('partials/sync_error.html', error=str(e))
        return jsonify({'error': str(e)}), 500


@bp.route('/full-sync', methods=['POST'])
@login_required
def full_sync():
    """Full two-way sync: pull from Drive first, then push local changes."""
    credentials = session.get('gdrive_credentials')
    if not credentials:
        return jsonify({'error': 'Not connected to Google Drive'}), 401

    try:
        service = GDriveService(current_app.config, credentials)
        root_folder_id = service.get_or_create_notes_folder()

        pulled = 0
        pushed = 0

        # === PULL: Get changes from Drive ===
        drive_files = service.list_all_files_recursive(root_folder_id)
        existing_by_gdrive_id = {n.gdrive_id: n for n in Note.query.filter_by(user_id=g.user.id).all() if n.gdrive_id}
        pulled_notes = []

        for item in drive_files:
            if item['is_folder']:
                continue

            name = item['name']
            mime_type = item.get('mimeType', '')
            drive_modified = parse_drive_time(item.get('modifiedTime'))

            if name.endswith('.md'):
                title = name[:-3]
                file_type = 'md'
            elif name.endswith('.txt'):
                title = name[:-4]
                file_type = 'txt'
            elif mime_type == 'application/vnd.google-apps.document':
                title = name
                file_type = 'md'
            else:
                continue

            path = item.get('path', '')
            path_parts = path.split('/')[:-1] if '/' in path else []

            try:
                if item['id'] in existing_by_gdrive_id:
                    note = existing_by_gdrive_id[item['id']]
                    # Only update if Drive version is newer
                    if note.gdrive_modified and drive_modified:
                        if drive_modified <= note.gdrive_modified:
                            continue

                    content = service.download_file(item['id'], mime_type)
                    note.title = title
                    note.content = content
                    note.file_type = file_type
                    note.sync_status = 'synced'
                    note.gdrive_modified = drive_modified
                    pulled_notes.append(note)
                    pulled += 1
                else:
                    content = service.download_file(item['id'], mime_type)
                    local_folder = get_or_create_folder_by_path(path_parts, g.user.id) if path_parts else None

                    note = Note(
                        title=title,
                        content=content,
                        file_type=file_type,
                        user_id=g.user.id,
                        folder_id=local_folder.id if local_folder else None,
                        gdrive_id=item['id'],
                        gdrive_modified=drive_modified,
                        sync_status='synced'
                    )
                    db.session.add(note)
                    pulled_notes.append(note)
                    pulled += 1
            except Exception as e:
                current_app.logger.warning(f"Failed to pull {name}: {e}")

        db.session.commit()

        # Save pulled notes to filesystem
        save_notes_to_filesystem(pulled_notes, g.user)

        # === PUSH: Send local changes to Drive ===
        local_notes = Note.query.filter_by(user_id=g.user.id, sync_status='local').all()
        for note in local_notes:
            if note.folder:
                folder_path = get_folder_path(note.folder)
                target_folder_id = service.get_or_create_folder_path(folder_path, root_folder_id)
                if not note.folder.gdrive_id:
                    note.folder.gdrive_id = target_folder_id
            else:
                target_folder_id = root_folder_id

            filename = f"{note.title}.{note.file_type}"
            if note.gdrive_id:
                service.update_file(note.gdrive_id, note.content, filename, target_folder_id)
            else:
                note.gdrive_id = service.upload_file(note.content, filename, target_folder_id)

            note.sync_status = 'synced'
            note.gdrive_modified = datetime.now(timezone.utc)
            pushed += 1

        db.session.commit()
        session['gdrive_credentials'] = service.get_credentials_dict()

        if request.headers.get('HX-Request'):
            return render_template('partials/sync_result.html', pulled=pulled, pushed=pushed)
        return jsonify({'pulled': pulled, 'pushed': pushed})
    except Exception as e:
        current_app.logger.error(f"Full sync error: {e}")
        if request.headers.get('HX-Request'):
            return render_template('partials/sync_error.html', error=str(e))
        return jsonify({'error': str(e)}), 500


@bp.route('/pull', methods=['POST'])
@login_required
def pull_from_drive():
    """Pull new/changed notes from Google Drive (incremental)."""
    credentials = session.get('gdrive_credentials')
    if not credentials:
        return jsonify({'error': 'Not connected to Google Drive'}), 401

    try:
        service = GDriveService(current_app.config, credentials)
        root_folder_id = service.get_or_create_notes_folder()

        # Get all files from Drive recursively
        drive_files = service.list_all_files_recursive(root_folder_id)

        imported = 0
        updated = 0
        skipped = 0
        pulled_notes = []

        # Get existing notes by gdrive_id for this user
        existing_by_gdrive_id = {n.gdrive_id: n for n in Note.query.filter_by(user_id=g.user.id).all() if n.gdrive_id}

        for item in drive_files:
            if item['is_folder']:
                continue

            name = item['name']
            mime_type = item.get('mimeType', '')
            drive_modified = parse_drive_time(item.get('modifiedTime'))

            # Determine file type based on extension or mime type
            if name.endswith('.md'):
                title = name[:-3]
                file_type = 'md'
            elif name.endswith('.txt'):
                title = name[:-4]
                file_type = 'txt'
            elif mime_type == 'application/vnd.google-apps.document':
                # Google Docs - treat as markdown
                title = name
                file_type = 'md'
            else:
                skipped += 1
                continue

            # Get folder path (excluding the filename)
            path = item.get('path', '')
            path_parts = path.split('/')[:-1] if '/' in path else []

            try:
                # Check if note already exists
                if item['id'] in existing_by_gdrive_id:
                    note = existing_by_gdrive_id[item['id']]

                    # Only update if Drive version is newer
                    if note.gdrive_modified and drive_modified:
                        if drive_modified <= note.gdrive_modified:
                            skipped += 1
                            continue

                    content = service.download_file(item['id'], mime_type)
                    note.title = title
                    note.content = content
                    note.file_type = file_type
                    note.sync_status = 'synced'
                    note.gdrive_modified = drive_modified
                    pulled_notes.append(note)
                    updated += 1
                else:
                    # Create new note
                    content = service.download_file(item['id'], mime_type)

                    # Get or create local folder
                    local_folder = get_or_create_folder_by_path(path_parts, g.user.id) if path_parts else None

                    note = Note(
                        title=title,
                        content=content,
                        file_type=file_type,
                        user_id=g.user.id,
                        folder_id=local_folder.id if local_folder else None,
                        gdrive_id=item['id'],
                        gdrive_modified=drive_modified,
                        sync_status='synced'
                    )
                    db.session.add(note)
                    pulled_notes.append(note)
                    imported += 1
            except Exception as e:
                current_app.logger.warning(f"Failed to import {name}: {e}")
                skipped += 1

        db.session.commit()
        session['gdrive_credentials'] = service.get_credentials_dict()

        # Save pulled notes to filesystem
        save_notes_to_filesystem(pulled_notes, g.user)

        result = {
            'imported': imported,
            'updated': updated,
            'skipped': skipped
        }

        if request.headers.get('HX-Request'):
            return render_template('partials/pull_result.html', result=result)
        return jsonify(result)
    except Exception as e:
        current_app.logger.error(f"Pull from Drive error: {e}")
        if request.headers.get('HX-Request'):
            return render_template('partials/sync_error.html', error=str(e))
        return jsonify({'error': str(e)}), 500


@bp.route('/sync-note/<int:note_id>', methods=['POST'])
@login_required
def sync_note(note_id):
    """Sync a single note with Google Drive."""
    credentials = session.get('gdrive_credentials')
    if not credentials:
        return jsonify({'error': 'Not connected to Google Drive'}), 401

    note = Note.query.filter_by(id=note_id, user_id=g.user.id).first_or_404()

    try:
        service = GDriveService(current_app.config, credentials)
        root_folder_id = service.get_or_create_notes_folder()

        # Get target folder in Drive
        if note.folder:
            folder_path = get_folder_path(note.folder)
            target_folder_id = service.get_or_create_folder_path(folder_path, root_folder_id)
            if not note.folder.gdrive_id:
                note.folder.gdrive_id = target_folder_id
        else:
            target_folder_id = root_folder_id

        filename = f"{note.title}.{note.file_type}"
        if note.gdrive_id:
            service.update_file(note.gdrive_id, note.content, filename, target_folder_id)
        else:
            note.gdrive_id = service.upload_file(note.content, filename, target_folder_id)

        note.sync_status = 'synced'
        note.gdrive_modified = datetime.now(timezone.utc)
        db.session.commit()

        session['gdrive_credentials'] = service.get_credentials_dict()

        if request.headers.get('HX-Request'):
            return render_template('partials/note_sync_status.html', note=note)
        return jsonify({'status': 'synced', 'gdrive_id': note.gdrive_id})
    except Exception as e:
        if request.headers.get('HX-Request'):
            return render_template('partials/sync_error.html', error=str(e))
        return jsonify({'error': str(e)}), 500


def save_notes_to_filesystem(notes, user):
    """Save notes to the local filesystem."""
    if not user or not user.notes_location:
        return 0

    try:
        storage = FileStorageService(user.notes_location)
        return storage.sync_all_notes(notes)
    except Exception as e:
        current_app.logger.error(f"Filesystem sync error: {e}")
        return 0


@bp.route('/auto-pull', methods=['POST'])
@login_required
def auto_pull():
    """Auto-pull from Google Drive (used during initial setup)."""
    credentials = session.get('gdrive_credentials')
    if not credentials:
        return jsonify({'imported': 0, 'updated': 0, 'skipped': 0, 'error': 'Not connected'})

    try:
        service = GDriveService(current_app.config, credentials)
        root_folder_id = service.get_or_create_notes_folder()

        # Get all files from Drive recursively
        drive_files = service.list_all_files_recursive(root_folder_id)

        imported = 0
        updated = 0
        skipped = 0

        # Get existing notes by gdrive_id for this user
        existing_by_gdrive_id = {n.gdrive_id: n for n in Note.query.filter_by(user_id=g.user.id).all() if n.gdrive_id}

        pulled_notes = []

        for item in drive_files:
            if item['is_folder']:
                continue

            name = item['name']
            mime_type = item.get('mimeType', '')
            drive_modified = parse_drive_time(item.get('modifiedTime'))

            # Determine file type based on extension or mime type
            if name.endswith('.md'):
                title = name[:-3]
                file_type = 'md'
            elif name.endswith('.txt'):
                title = name[:-4]
                file_type = 'txt'
            elif mime_type == 'application/vnd.google-apps.document':
                title = name
                file_type = 'md'
            else:
                skipped += 1
                continue

            # Get folder path
            path = item.get('path', '')
            path_parts = path.split('/')[:-1] if '/' in path else []

            try:
                if item['id'] in existing_by_gdrive_id:
                    note = existing_by_gdrive_id[item['id']]

                    if note.gdrive_modified and drive_modified:
                        if drive_modified <= note.gdrive_modified:
                            skipped += 1
                            continue

                    content = service.download_file(item['id'], mime_type)
                    note.title = title
                    note.content = content
                    note.file_type = file_type
                    note.sync_status = 'synced'
                    note.gdrive_modified = drive_modified
                    pulled_notes.append(note)
                    updated += 1
                else:
                    content = service.download_file(item['id'], mime_type)
                    local_folder = get_or_create_folder_by_path(path_parts, g.user.id) if path_parts else None

                    note = Note(
                        title=title,
                        content=content,
                        file_type=file_type,
                        user_id=g.user.id,
                        folder_id=local_folder.id if local_folder else None,
                        gdrive_id=item['id'],
                        gdrive_modified=drive_modified,
                        sync_status='synced'
                    )
                    db.session.add(note)
                    pulled_notes.append(note)
                    imported += 1
            except Exception as e:
                current_app.logger.warning(f"Failed to import {name}: {e}")
                skipped += 1

        db.session.commit()
        session['gdrive_credentials'] = service.get_credentials_dict()

        # Save all pulled notes to filesystem
        save_notes_to_filesystem(pulled_notes, g.user)

        return jsonify({
            'imported': imported,
            'updated': updated,
            'skipped': skipped
        })
    except Exception as e:
        current_app.logger.error(f"Auto-pull error: {e}")
        return jsonify({'imported': 0, 'updated': 0, 'skipped': 0, 'error': str(e)})
