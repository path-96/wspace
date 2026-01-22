import os
import shutil
from datetime import datetime


class FileStorageService:
    """Service for saving notes to local filesystem."""

    def __init__(self, base_path):
        self.base_path = os.path.expanduser(base_path)

    def _ensure_dir(self, path):
        """Ensure directory exists."""
        os.makedirs(path, exist_ok=True)

    def _get_folder_path(self, folder):
        """Get full path for a folder, creating parent directories as needed."""
        if not folder:
            return self.base_path

        # Build path from folder hierarchy
        path_parts = []
        current = folder
        while current:
            path_parts.insert(0, current.name)
            current = current.parent

        folder_path = os.path.join(self.base_path, *path_parts)
        self._ensure_dir(folder_path)
        return folder_path

    def save_note(self, note):
        """Save a note to the filesystem."""
        folder_path = self._get_folder_path(note.folder)
        filename = f"{note.title}.{note.file_type}"
        file_path = os.path.join(folder_path, filename)

        # Save content
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(note.content or '')

        return file_path

    def delete_note(self, note):
        """Delete a note from the filesystem."""
        folder_path = self._get_folder_path(note.folder)
        filename = f"{note.title}.{note.file_type}"
        file_path = os.path.join(folder_path, filename)

        if os.path.exists(file_path):
            os.remove(file_path)
            return True
        return False

    def rename_note(self, old_title, old_file_type, new_title, new_file_type, folder=None):
        """Rename a note file on the filesystem."""
        folder_path = self._get_folder_path(folder)

        old_filename = f"{old_title}.{old_file_type}"
        new_filename = f"{new_title}.{new_file_type}"

        old_path = os.path.join(folder_path, old_filename)
        new_path = os.path.join(folder_path, new_filename)

        if os.path.exists(old_path) and old_path != new_path:
            os.rename(old_path, new_path)
            return new_path
        return old_path

    def move_note(self, note, old_folder, new_folder):
        """Move a note to a different folder."""
        old_folder_path = self._get_folder_path(old_folder)
        new_folder_path = self._get_folder_path(new_folder)

        filename = f"{note.title}.{note.file_type}"
        old_path = os.path.join(old_folder_path, filename)
        new_path = os.path.join(new_folder_path, filename)

        if os.path.exists(old_path):
            shutil.move(old_path, new_path)
            return new_path
        return None

    def create_folder(self, folder):
        """Create a folder on the filesystem."""
        folder_path = self._get_folder_path(folder)
        self._ensure_dir(folder_path)
        return folder_path

    def delete_folder(self, folder):
        """Delete a folder from the filesystem (only if empty)."""
        folder_path = self._get_folder_path(folder)
        if os.path.exists(folder_path) and os.path.isdir(folder_path):
            # Only delete if empty
            if not os.listdir(folder_path):
                os.rmdir(folder_path)
                return True
        return False

    def rename_folder(self, folder, old_name):
        """Rename a folder on the filesystem."""
        parent_path = self._get_folder_path(folder.parent) if folder.parent else self.base_path

        old_path = os.path.join(parent_path, old_name)
        new_path = os.path.join(parent_path, folder.name)

        if os.path.exists(old_path) and old_path != new_path:
            os.rename(old_path, new_path)
            return new_path
        return old_path

    def sync_all_notes(self, notes):
        """Sync all notes to the filesystem."""
        synced = 0
        for note in notes:
            try:
                self.save_note(note)
                synced += 1
            except Exception:
                pass
        return synced
