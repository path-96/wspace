import json
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from googleapiclient.http import MediaInMemoryUpload


SCOPES = ['https://www.googleapis.com/auth/drive.file']


class GDriveService:
    """Google Drive API service wrapper."""

    def __init__(self, config, credentials_dict=None):
        self.config = config
        self.credentials = None
        self._service = None

        if credentials_dict:
            scopes = credentials_dict.get('scopes', SCOPES)
            self.credentials = Credentials(
                token=credentials_dict.get('token'),
                refresh_token=credentials_dict.get('refresh_token'),
                token_uri='https://oauth2.googleapis.com/token',
                client_id=config.get('GOOGLE_CLIENT_ID'),
                client_secret=config.get('GOOGLE_CLIENT_SECRET'),
                scopes=scopes
            )

    def get_auth_url(self):
        """Get OAuth authorization URL."""
        flow = self._get_flow()
        auth_url, _ = flow.authorization_url(
            access_type='offline',
            include_granted_scopes='true',
            prompt='consent'
        )
        return auth_url

    def handle_callback(self, code):
        """Handle OAuth callback and return credentials dict."""
        flow = self._get_flow()
        flow.fetch_token(code=code)
        self.credentials = flow.credentials
        return self.get_credentials_dict()

    def get_credentials_dict(self):
        """Return credentials as dict for session storage."""
        if not self.credentials:
            return None
        return {
            'token': self.credentials.token,
            'refresh_token': self.credentials.refresh_token,
            'token_uri': self.credentials.token_uri,
            'client_id': self.credentials.client_id,
            'client_secret': self.credentials.client_secret,
            'scopes': list(self.credentials.scopes) if self.credentials.scopes else SCOPES,
        }

    def _get_flow(self):
        """Get OAuth flow."""
        client_config = {
            'web': {
                'client_id': self.config.get('GOOGLE_CLIENT_ID'),
                'client_secret': self.config.get('GOOGLE_CLIENT_SECRET'),
                'auth_uri': 'https://accounts.google.com/o/oauth2/auth',
                'token_uri': 'https://oauth2.googleapis.com/token',
                'redirect_uris': [self.config.get('GOOGLE_REDIRECT_URI')],
            }
        }
        return Flow.from_client_config(client_config, SCOPES,
                                       redirect_uri=self.config.get('GOOGLE_REDIRECT_URI'))

    @property
    def service(self):
        """Get or create Drive API service."""
        if not self._service and self.credentials:
            self._service = build('drive', 'v3', credentials=self.credentials)
        return self._service

    def get_or_create_notes_folder(self):
        """Get or create the Notes folder in Drive root."""
        return self.get_or_create_folder('Notes', parent_id=None)

    def get_or_create_folder(self, name, parent_id=None):
        """Get or create a folder by name in a parent folder."""
        # Build query
        query = f"name='{name}' and mimeType='application/vnd.google-apps.folder' and trashed=false"
        if parent_id:
            query += f" and '{parent_id}' in parents"
        else:
            query += " and 'root' in parents"

        results = self.service.files().list(
            q=query,
            spaces='drive',
            fields='files(id, name)'
        ).execute()

        files = results.get('files', [])
        if files:
            return files[0]['id']

        # Create folder
        file_metadata = {
            'name': name,
            'mimeType': 'application/vnd.google-apps.folder'
        }
        if parent_id:
            file_metadata['parents'] = [parent_id]

        folder = self.service.files().create(
            body=file_metadata,
            fields='id'
        ).execute()
        return folder['id']

    def get_or_create_folder_path(self, folder_path, root_folder_id):
        """
        Get or create a nested folder path.
        folder_path is a list like ['Work', 'Projects', 'App']
        Returns the id of the deepest folder.
        """
        current_parent = root_folder_id
        for folder_name in folder_path:
            current_parent = self.get_or_create_folder(folder_name, current_parent)
        return current_parent

    def upload_file(self, content, filename, folder_id):
        """Upload a new file to Drive."""
        file_metadata = {
            'name': filename,
            'parents': [folder_id]
        }

        # Determine mime type
        mime_type = 'text/markdown' if filename.endswith('.md') else 'text/plain'

        media = MediaInMemoryUpload(
            content.encode('utf-8'),
            mimetype=mime_type,
            resumable=True
        )

        file = self.service.files().create(
            body=file_metadata,
            media_body=media,
            fields='id'
        ).execute()

        return file['id']

    def update_file(self, file_id, content, filename, new_folder_id=None):
        """Update an existing file in Drive, optionally moving it."""
        mime_type = 'text/markdown' if filename.endswith('.md') else 'text/plain'

        media = MediaInMemoryUpload(
            content.encode('utf-8'),
            mimetype=mime_type,
            resumable=True
        )

        # If moving to new folder
        if new_folder_id:
            # Get current parents
            file = self.service.files().get(fileId=file_id, fields='parents').execute()
            previous_parents = ",".join(file.get('parents', []))

            self.service.files().update(
                fileId=file_id,
                addParents=new_folder_id,
                removeParents=previous_parents,
                body={'name': filename},
                media_body=media
            ).execute()
        else:
            self.service.files().update(
                fileId=file_id,
                body={'name': filename},
                media_body=media
            ).execute()

    def download_file(self, file_id, mime_type=None):
        """Download file content from Drive. Handles both regular files and Google Docs."""
        # Google Docs types need to be exported
        google_docs_types = {
            'application/vnd.google-apps.document': 'text/plain',
            'application/vnd.google-apps.spreadsheet': 'text/csv',
        }

        if mime_type in google_docs_types:
            # Export Google Docs as plain text
            content = self.service.files().export(
                fileId=file_id,
                mimeType=google_docs_types[mime_type]
            ).execute()
        else:
            # Regular file download
            content = self.service.files().get_media(fileId=file_id).execute()

        if isinstance(content, bytes):
            return content.decode('utf-8')
        return content

    def list_files(self, folder_id, include_folders=False):
        """List all files in a folder."""
        query = f"'{folder_id}' in parents and trashed=false"
        if not include_folders:
            query += " and mimeType!='application/vnd.google-apps.folder'"

        results = self.service.files().list(
            q=query,
            spaces='drive',
            fields='files(id, name, mimeType, modifiedTime)',
            orderBy='modifiedTime desc'
        ).execute()
        return results.get('files', [])

    def list_all_files_recursive(self, folder_id, path=''):
        """
        Recursively list all files and folders.
        Returns list of dicts with id, name, path, mimeType, modifiedTime.
        """
        results = []
        items = self.list_files(folder_id, include_folders=True)

        for item in items:
            item_path = f"{path}/{item['name']}" if path else item['name']
            item['path'] = item_path

            if item['mimeType'] == 'application/vnd.google-apps.folder':
                item['is_folder'] = True
                results.append(item)
                # Recurse into subfolder
                results.extend(self.list_all_files_recursive(item['id'], item_path))
            else:
                item['is_folder'] = False
                results.append(item)

        return results

    def get_file_metadata(self, file_id):
        """Get file metadata."""
        return self.service.files().get(
            fileId=file_id,
            fields='id, name, mimeType, modifiedTime, parents'
        ).execute()

    def delete_file(self, file_id):
        """Delete a file or folder from Drive."""
        self.service.files().delete(fileId=file_id).execute()
