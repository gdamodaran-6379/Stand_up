"""Utility functions for Standup Agent."""

import os
import json
import re
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CREDENTIALS_PATH = os.path.join(SCRIPT_DIR, 'credentials.json')
TOKEN_CACHE_KEY = "standup_agent_tokens"

# Scopes
GOOGLE_SCOPES = {
    'https://www.googleapis.com/auth/calendar.readonly': 'Read calendar events',
    'https://www.googleapis.com/auth/drive.readonly': 'Read Drive files',
}

JIRA_SCOPES = {
    'read:jira-work': 'Read Jira work',
    'write:jira-work': 'Write Jira comments',
    'offline_access': 'Offline access',
}

SYDNEY_TZ = ZoneInfo("Australia/Sydney")
JIRA_TOKEN_CACHE_KEY = "standup_agent_jira_token"

# Spoken digit mapping
SPOKEN_DIGITS = {
    'zero': '0', 'one': '1', 'two': '2', 'three': '3', 'four': '4',
    'five': '5', 'six': '6', 'seven': '7', 'eight': '8', 'nine': '9'
}


def load_oauth_credentials():
    """Load OAuth client credentials from credentials.json"""
    if not os.path.exists(CREDENTIALS_PATH):
        raise FileNotFoundError(f"credentials.json not found at {CREDENTIALS_PATH}")
    
    with open(CREDENTIALS_PATH, 'r') as f:
        creds_data = json.load(f)
        client_config = creds_data.get('installed') or creds_data.get('web')
        if not client_config:
            raise ValueError("Invalid credentials.json format")
        return client_config['client_id'], client_config['client_secret']


def get_sydney_date(date_str=None):
    """Get date in Australia/Sydney timezone"""
    if date_str:
        # Parse provided date
        from dateutil import parser
        dt = parser.parse(date_str)
        return dt.astimezone(SYDNEY_TZ)
    return datetime.now(SYDNEY_TZ)


def extract_ticket_keys(text, default_project="WJR"):
    """Extract Jira ticket keys from text with confidence levels"""
    tickets = []
    
    # Full key pattern (HIGH confidence)
    full_pattern = r'\b([A-Z]{2,10}-\d+)\b'
    for match in re.finditer(full_pattern, text):
        tickets.append({
            'key': match.group(1),
            'confidence': 'high',
            'type': 'full_key'
        })
    
    # Partial numeric pattern (MEDIUM confidence)
    partial_pattern = r'(?:ticket|issue|bug|story)\s+(\d+)'
    for match in re.finditer(partial_pattern, text, re.IGNORECASE):
        key = f"{default_project}-{match.group(1)}"
        if not any(t['key'] == key for t in tickets):
            tickets.append({
                'key': key,
                'confidence': 'medium',
                'type': 'partial_numeric'
            })
    
    # Spoken digits pattern (LOW confidence)
    spoken_pattern = r'\b(' + '|'.join(SPOKEN_DIGITS.keys()) + r')(?:\s+(' + '|'.join(SPOKEN_DIGITS.keys()) + r'))*'
    for match in re.finditer(spoken_pattern, text, re.IGNORECASE):
        digits = ''.join(SPOKEN_DIGITS.get(word.lower(), '') for word in match.group(0).split())
        if len(digits) >= 3:
            key = f"{default_project}-{digits}"
            if not any(t['key'] == key for t in tickets):
                tickets.append({
                    'key': key,
                    'confidence': 'low',
                    'type': 'spoken_digits'
                })
    
    return tickets


def parse_speakers(text):
    """Parse speaker attributions from transcript"""
    speakers = {}
    current_speaker = None
    
    lines = text.split('\n')
    for line in lines:
        # Detect speaker pattern: "Name:" or "Name -"
        speaker_match = re.match(r'^([A-Z][a-zA-Z\s]+):\s*(.*)$', line.strip())
        if speaker_match:
            current_speaker = speaker_match.group(1).strip()
            content = speaker_match.group(2).strip()
            if current_speaker not in speakers:
                speakers[current_speaker] = []
            if content:
                speakers[current_speaker].append(content)
        elif current_speaker and line.strip():
            speakers[current_speaker].append(line.strip())
    
    return speakers


def extract_date_from_transcript(text):
    """Extract date mentioned in transcript"""
    # Patterns like "Standup for 27 Oct", "27 October 2025"
    date_patterns = [
        r'(?:standup|meeting)\s+(?:for|on)\s+(\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*(?:\s+\d{4})?)',
        r'(\d{1,2}\s+(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{4})',
    ]
    
    for pattern in date_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            from dateutil import parser
            try:
                return parser.parse(match.group(1))
            except:
                pass
    
    return None


def generate_adf_comment(content, date_str, speakers_data):
    """Generate Atlassian Document Format comment"""
    adf = {
        "version": 1,
        "type": "doc",
        "content": [
            {
                "type": "paragraph",
                "content": [{"type": "text", "text": f"Standup Update — {date_str}", "marks": [{"type": "strong"}]}]
            }
        ]
    }
    
    # Add speaker sections
    for speaker, points in speakers_data.items():
        adf["content"].append({
            "type": "heading",
            "attrs": {"level": 3},
            "content": [{"type": "text", "text": speaker}]
        })
        
        bullet_items = []
        for point in points:
            bullet_items.append({
                "type": "listItem",
                "content": [{
                    "type": "paragraph",
                    "content": [{"type": "text", "text": point}]
                }]
            })
        
        adf["content"].append({
            "type": "bulletList",
            "content": bullet_items
        })
    
    # Add footer
    adf["content"].append({
        "type": "paragraph",
        "content": [{
            "type": "text",
            "text": "Generated by Standup Agent based on meeting notes; verify accuracy before relying on this content. For discrepancies, contact your Product Owner.",
            "marks": [{"type": "em"}]
        }]
    })
    
    return adf


def get_meet_code(hangout_link):
    """Extract Google Meet code from hangout link"""
    if not hangout_link:
        return None
    try:
        return hangout_link.split('/')[-1].split('?')[0].replace('-', '')
    except:
        return None


def read_document_content(drive_service, file_id):
    """Download and return plain text content of a Google Doc"""
    try:
        from googleapiclient.http import MediaIoBaseDownload
        import io
        
        request = drive_service.files().export_media(fileId=file_id, mimeType='text/plain')
        file_content = io.BytesIO()
        downloader = MediaIoBaseDownload(file_content, request)
        done = False
        while not done:
            status, done = downloader.next_chunk()
        return file_content.getvalue().decode('utf-8')
    except Exception as e:
        return f"Error reading document: {e}"


def search_meeting_notes(drive_service, event_summary, event_time):
    """Search for Gemini meeting notes in Drive"""
    try:
        query = "mimeType='application/vnd.google-apps.document' and (name contains 'Notes by Gemini' or name contains 'Meeting notes')"
        results = drive_service.files().list(
            q=query, spaces='drive',
            fields='files(id, name, createdTime, modifiedTime, webViewLink)',
            orderBy='modifiedTime desc', pageSize=50
        ).execute()
        
        files = results.get('files', [])
        for file in files:
            if event_summary.lower() in file['name'].lower():
                file_time = datetime.fromisoformat(file['createdTime'].replace('Z', '+00:00'))
                time_diff = (file_time - event_time).total_seconds()
                if 0 <= time_diff <= 14400:  # 0-4 hours after meeting
                    return {'id': file['id'], 'name': file['name'], 'link': file['webViewLink']}
        return None
    except:
        return None


def check_for_transcript_and_recording(cal_service, drive_service, meet_code, event_summary, event_time):
    """Check if meeting has transcript, recording, or notes"""
    if not meet_code:
        return None
    
    result = {'transcript': None, 'recording': None, 'notes': None}
    
    # Check for notes in Drive
    notes = search_meeting_notes(drive_service, event_summary, event_time)
    if notes:
        result['notes'] = notes
    
    return result if result['notes'] else None


def get_jira_cloud_id(access_token, tool_context):
    """Get Jira cloud ID and cache it"""
    import requests
    
    # Check cache first
    cached_cloud_id = tool_context.state.get(JIRA_TOKEN_CACHE_KEY + "_cloud_id")
    if cached_cloud_id:
        return cached_cloud_id
    
    # Fetch cloud ID
    resources_url = "https://api.atlassian.com/oauth/token/accessible-resources"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/json"
    }
    
    response = requests.get(resources_url, headers=headers, timeout=10)
    if response.status_code != 200:
        return None
    
    resources = response.json()
    if not resources:
        return None
    
    cloud_id = resources[0]['id']
    
    # Cache it
    tool_context.state[JIRA_TOKEN_CACHE_KEY + "_cloud_id"] = cloud_id
    
    return cloud_id


def get_authenticated_google_services(tool_context, auth_scheme, auth_credential, client_id, client_secret):
    """Get authenticated Google API services"""
    from google.adk.auth import AuthConfig
    
    creds = None
    cached_token_info = tool_context.state.get(TOKEN_CACHE_KEY + "_google")
    
    if cached_token_info:
        try:
            creds = Credentials.from_authorized_user_info(cached_token_info, list(GOOGLE_SCOPES.keys()))
            if not creds.valid and creds.expired and creds.refresh_token:
                creds.refresh(Request())
                tool_context.state[TOKEN_CACHE_KEY + "_google"] = json.loads(creds.to_json())
            elif not creds.valid:
                creds = None
        except:
            creds = None
    
    if not creds or not creds.valid:
        exchanged_credential = tool_context.get_auth_response(
            AuthConfig(auth_scheme=auth_scheme, raw_auth_credential=auth_credential)
        )
        
        if exchanged_credential:
            creds = Credentials(
                token=exchanged_credential.oauth2.access_token,
                refresh_token=exchanged_credential.oauth2.refresh_token,
                token_uri=auth_scheme.flows.authorizationCode.tokenUrl,
                client_id=client_id,
                client_secret=client_secret,
                scopes=list(GOOGLE_SCOPES.keys()),
            )
            tool_context.state[TOKEN_CACHE_KEY + "_google"] = json.loads(creds.to_json())
    
    if not creds or not creds.valid:
        tool_context.request_credential(
            AuthConfig(auth_scheme=auth_scheme, raw_auth_credential=auth_credential)
        )
        return None
    
    calendar_service = build('calendar', 'v3', credentials=creds)
    drive_service = build('drive', 'v3', credentials=creds)
    return calendar_service, drive_service
