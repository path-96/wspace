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
            self.credentials = Credentials(
                token=credentials_dict.get('token'),
                refresh_token=credentials_dict.get('refresh_token'),
                token_uri='https://oauth2.googleapis.com/token',
                client_id=config.get('GOOGLE_CLIENT_ID'),
                client_secret=config.get('GOOGLE_CLIENT_SECRET'),
                scopes=SCOPES
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
        # Search for existing folder
        results = self.service.files().list(
            q="name='Notes' and mimeType='application/vnd.google-apps.folder' and trashed=false",
            spaces='drive',
            fields='files(id, name)'
        ).execute()

        files = results.get('files', [])
        if files:
            return files[0]['id']

        # Create folder
        file_metadata = {
            'name': 'Notes',
            'mimeType': 'application/vnd.google-apps.folder'
        }
        folder = self.service.files().create(
            body=file_metadata,
            fields='id'
        ).execute()
        return folder['id']

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

    def update_file(self, file_id, content, filename):
        """Update an existing file in Drive."""
        mime_type = 'text/markdown' if filename.endswith('.md') else 'text/plain'

        media = MediaInMemoryUpload(
            content.encode('utf-8'),
            mimetype=mime_type,
            resumable=True
        )

        self.service.files().update(
            fileId=file_id,
            body={'name': filename},
            media_body=media
        ).execute()

    def download_file(self, file_id):
        """Download file content from Drive."""
        content = self.service.files().get_media(fileId=file_id).execute()
        return content.decode('utf-8')

    def list_files(self, folder_id):
        """List all files in a folder."""
        results = self.service.files().list(
            q=f"'{folder_id}' in parents and trashed=false",
            spaces='drive',
            fields='files(id, name, modifiedTime)',
            orderBy='modifiedTime desc'
        ).execute()
        return results.get('files', [])

    def get_file_metadata(self, file_id):
        """Get file metadata."""
        return self.service.files().get(
            fileId=file_id,
            fields='id, name, modifiedTime'
        ).execute()
