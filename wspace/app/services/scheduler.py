import os
from datetime import datetime, timezone
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

scheduler = BackgroundScheduler()
_scheduler_initialized = False


def init_scheduler(app):
    """Initialize the background scheduler with the Flask app."""
    global _scheduler_initialized

    # Prevent double initialization in debug mode
    if _scheduler_initialized or scheduler.running:
        return

    # Don't start scheduler in reloader process
    if os.environ.get('WERKZEUG_RUN_MAIN') != 'true' and app.debug:
        return

    _scheduler_initialized = True

    # Add the sync job
    scheduler.add_job(
        func=sync_all_users,
        trigger=IntervalTrigger(minutes=5),
        id='sync_all_users',
        name='Sync all users with Google Drive',
        replace_existing=True,
        kwargs={'app': app}
    )

    scheduler.start()
    app.logger.info("Background scheduler started - syncing every 5 minutes")


def sync_all_users(app):
    """Background job to sync all users' notes with Google Drive."""
    with app.app_context():
        from app import db
        from app.models import User, Note, Folder
        from app.services.gdrive_service import GDriveService
        from app.services.file_storage import FileStorageService

        # Get all users with notes_location set
        users = User.query.filter(User.notes_location.isnot(None)).all()

        for user in users:
            try:
                sync_user_notes(app, user)
            except Exception as e:
                app.logger.error(f"Background sync error for user {user.id}: {e}")


def sync_user_notes(app, user):
    """Sync notes for a single user (called from background job)."""
    from app import db
    from app.models import Note, Folder
    from app.services.gdrive_service import GDriveService
    from app.services.file_storage import FileStorageService

    # We need stored credentials for background sync
    # For now, this will work when user has an active session
    # In production, you'd store refresh tokens in the database

    # Check if user has any local changes to push
    local_notes = Note.query.filter_by(user_id=user.id, sync_status='local').all()

    if local_notes:
        app.logger.info(f"User {user.id} has {len(local_notes)} local notes to sync")

    # Save all synced notes to filesystem
    if user.notes_location:
        try:
            storage = FileStorageService(user.notes_location)
            synced_notes = Note.query.filter_by(user_id=user.id).all()
            storage.sync_all_notes(synced_notes)
        except Exception as e:
            app.logger.error(f"Filesystem sync error for user {user.id}: {e}")


def shutdown_scheduler():
    """Shutdown the scheduler gracefully."""
    if scheduler.running:
        scheduler.shutdown(wait=False)
