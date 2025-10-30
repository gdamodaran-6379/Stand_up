"""Tool functions for Standup Agent."""

from typing import Optional
from datetime import datetime, timedelta
from google.adk.tools import ToolContext
import requests
from .utils import (
    get_sydney_date, extract_ticket_keys, parse_speakers,
    extract_date_from_transcript, generate_adf_comment,
    get_authenticated_google_services, get_jira_cloud_id, SYDNEY_TZ
)


def fetch_calendar_events(days_back: int = 7, only_with_notes: bool = True, tool_context: Optional[ToolContext] = None) -> dict:
    """Fetch Google Calendar events from the last N days, optionally filtering for those with notes.
    
    Args:
        days_back: Number of days to look back (default 7)
        only_with_notes: If True, only return meetings with notes/transcripts (default True)
        tool_context: ToolContext for authentication
    
    Returns:
        dict: status and list of events with notes/transcripts
    """
    try:
        from .config import google_auth_scheme, google_auth_credential, GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET
        from .utils import get_meet_code, check_for_transcript_and_recording
        
        services = get_authenticated_google_services(
            tool_context, google_auth_scheme, google_auth_credential,
            GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET
        )
        
        if not services:
            return {"status": "pending", "message": "Awaiting Google authentication"}
        
        cal_service, drive_service = services
        
        now = datetime.now(SYDNEY_TZ)
        start_date = (now - timedelta(days=days_back)).replace(hour=0, minute=0, second=0)
        
        events_result = cal_service.events().list(
            calendarId='primary',
            timeMin=start_date.isoformat(),
            timeMax=now.isoformat(),
            singleEvents=True,
            orderBy='startTime'
        ).execute()
        
        events = events_result.get('items', [])
        result_events = []
        
        for e in events:
            summary = e.get('summary', 'No Title')
            start = e['start'].get('dateTime', e['start'].get('date'))
            meet_link = e.get('hangoutLink')
            
            event_info = {
                "id": e.get('id'),
                "summary": summary,
                "start": start,
                "has_meet": bool(meet_link)
            }
            
            # Check for notes if filtering
            if only_with_notes and meet_link:
                meet_code = get_meet_code(meet_link)
                event_time = datetime.fromisoformat(start.replace('Z', '+00:00'))
                media = check_for_transcript_and_recording(cal_service, drive_service, meet_code, summary, event_time)
                
                if media:
                    if media.get('notes'):
                        event_info['notes_id'] = media['notes']['id']
                        event_info['notes_link'] = media['notes']['link']
                    if media.get('transcript'):
                        event_info['transcript_id'] = media['transcript']['id']
                        event_info['transcript_link'] = media['transcript']['link']
                    result_events.append(event_info)
            elif not only_with_notes:
                result_events.append(event_info)
        
        return {
            "status": "success",
            "events": result_events,
            "count": len(result_events)
        }
    except Exception as e:
        return {"status": "error", "error_message": str(e)}


def parse_transcript(transcript_text: str, default_project: str = "WJR") -> dict:
    """Parse transcript to extract tickets, speakers, and date.
    
    Args:
        transcript_text: Raw transcript text
        default_project: Default Jira project key (default "WJR")
    
    Returns:
        dict: Parsed data with tickets, speakers, date
    """
    try:
        # Extract date
        extracted_date = extract_date_from_transcript(transcript_text)
        date_used = extracted_date if extracted_date else get_sydney_date()
        
        # Extract tickets
        tickets = extract_ticket_keys(transcript_text, default_project)
        
        # Parse speakers
        speakers = parse_speakers(transcript_text)
        
        # Group content by ticket
        ticket_contexts = {}
        for ticket in tickets:
            ticket_key = ticket['key']
            ticket_contexts[ticket_key] = {
                'confidence': ticket['confidence'],
                'type': ticket['type'],
                'speakers': {},
                'mentions': []
            }
            
            # Find mentions in speaker content
            for speaker, lines in speakers.items():
                relevant_lines = [line for line in lines if ticket_key in line or 
                                any(str(ticket_key.split('-')[1]) in line for line in lines)]
                if relevant_lines:
                    ticket_contexts[ticket_key]['speakers'][speaker] = relevant_lines
        
        return {
            "status": "success",
            "date": date_used.strftime("%d %b %Y"),
            "tickets": tickets,
            "speakers": speakers,
            "ticket_contexts": ticket_contexts,
            "default_project": default_project
        }
    except Exception as e:
        return {"status": "error", "error_message": str(e)}


def get_jira_auth(tool_context):
    """Get Jira authentication token with caching"""
    from .config import jira_auth_credential, jira_auth_scheme
    from google.adk.auth import AuthConfig
    from .utils import JIRA_TOKEN_CACHE_KEY
    
    # Check cache first
    cached_token = tool_context.state.get(JIRA_TOKEN_CACHE_KEY)
    if cached_token:
        return cached_token
    
    # Get OAuth token
    auth_config = AuthConfig(auth_scheme=jira_auth_scheme, raw_auth_credential=jira_auth_credential)
    exchanged_credential = tool_context.get_auth_response(auth_config)
    
    if not exchanged_credential:
        tool_context.request_credential(auth_config)
        return None
    
    access_token = exchanged_credential.oauth2.access_token
    
    # Cache it
    tool_context.state[JIRA_TOKEN_CACHE_KEY] = access_token
    
    return access_token


def validate_jira_tickets(ticket_keys: list, tool_context: Optional[ToolContext] = None) -> dict:
    """Validate Jira ticket keys via Jira API.
    
    Args:
        ticket_keys: List of Jira ticket keys to validate
        tool_context: ToolContext for authentication
    
    Returns:
        dict: Validation results for each ticket
    """
    try:
        from .config import JIRA_SITE_URL
        
        jira_site = JIRA_SITE_URL
        
        # Get cached or new token
        access_token = get_jira_auth(tool_context)
        if not access_token:
            return {"status": "pending", "message": "Awaiting Jira authentication"}
        
        # Get cloud ID (cached)
        cloud_id = get_jira_cloud_id(access_token, tool_context)
        if not cloud_id:
            return {"status": "error", "error_message": "Failed to get Jira cloud ID"}
        
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/json"
        }
        
        results = []
        for key in ticket_keys:
            try:
                url = f"https://api.atlassian.com/ex/jira/{cloud_id}/rest/api/3/issue/{key}"
                response = requests.get(url, headers=headers, timeout=10)
                
                if response.status_code == 200:
                    data = response.json()
                    results.append({
                        "key": key,
                        "valid": True,
                        "status": data['fields']['status']['name'],
                        "assignee": data['fields'].get('assignee', {}).get('displayName', 'Unassigned'),
                        "summary": data['fields']['summary']
                    })
                else:
                    results.append({
                        "key": key,
                        "valid": False,
                        "error": f"HTTP {response.status_code}"
                    })
            except Exception as e:
                results.append({
                    "key": key,
                    "valid": False,
                    "error": str(e)
                })
        
        return {"status": "success", "results": results}
    except Exception as e:
        return {"status": "error", "error_message": str(e)}


def generate_jira_comment(ticket_key: str, ticket_context: dict, date_str: str, ticket_info: Optional[dict] = None) -> dict:
    """Generate Jira comment in ADF format.
    
    Args:
        ticket_key: Jira ticket key
        ticket_context: Context data for the ticket (speakers, mentions)
        date_str: Date string for the standup
        ticket_info: Optional ticket info from validation (status, assignee, summary)
    
    Returns:
        dict: Generated comment in ADF format with preview
    """
    try:
        speakers_data = ticket_context.get('speakers', {})
        
        # Generate ADF
        adf = generate_adf_comment(
            content=ticket_context,
            date_str=date_str,
            speakers_data=speakers_data
        )
        
        # Generate plain text preview
        preview_lines = [f"Standup Update — {date_str}", ""]
        for speaker, points in speakers_data.items():
            preview_lines.append(f"{speaker}")
            for point in points:
                preview_lines.append(f"• {point}")
            preview_lines.append("")
        preview_lines.append("Generated by Standup Agent based on meeting notes; verify accuracy before relying on this content.")
        
        result = {
            "status": "success",
            "ticket_key": ticket_key,
            "adf": adf,
            "preview": "\n".join(preview_lines)
        }
        
        # Add ticket info if provided
        if ticket_info:
            result["ticket_status"] = ticket_info.get("status")
            result["ticket_assignee"] = ticket_info.get("assignee")
            result["ticket_summary"] = ticket_info.get("summary")
        
        return result
    except Exception as e:
        return {"status": "error", "error_message": str(e)}


def post_jira_comment(ticket_key: str, adf_comment: dict, tool_context: Optional[ToolContext] = None) -> dict:
    """Post comment to Jira ticket.
    
    Args:
        ticket_key: Jira ticket key
        adf_comment: Comment in ADF format
        tool_context: ToolContext for authentication
    
    Returns:
        dict: Post status and link
    """
    try:
        from .config import JIRA_SITE_URL
        
        jira_site = JIRA_SITE_URL
        
        # Get cached or new token
        access_token = get_jira_auth(tool_context)
        if not access_token:
            return {"status": "pending", "message": "Awaiting Jira authentication"}
        
        # Get cloud ID (cached)
        cloud_id = get_jira_cloud_id(access_token, tool_context)
        if not cloud_id:
            return {"status": "error", "error_message": "Failed to get Jira cloud ID"}
        
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/json",
            "Content-Type": "application/json"
        }
        
        url = f"https://api.atlassian.com/ex/jira/{cloud_id}/rest/api/3/issue/{ticket_key}/comment"
        payload = {"body": adf_comment}
        
        response = requests.post(url, json=payload, headers=headers, timeout=10)
        
        if response.status_code in [200, 201]:
            return {
                "status": "success",
                "ticket_key": ticket_key,
                "link": f"https://{jira_site}/browse/{ticket_key}"
            }
        else:
            return {
                "status": "error",
                "ticket_key": ticket_key,
                "error_message": f"HTTP {response.status_code}: {response.text}"
            }
    except Exception as e:
        return {"status": "error", "error_message": str(e)}


def get_meeting_notes(event_id: str, tool_context: Optional[ToolContext] = None) -> dict:
    """Fetch meeting notes/transcript content for a specific event.
    
    Args:
        event_id: Calendar event ID
        tool_context: ToolContext for authentication
    
    Returns:
        dict: Meeting notes content
    """
    try:
        from .config import google_auth_scheme, google_auth_credential, GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET
        from .utils import get_meet_code, check_for_transcript_and_recording, read_document_content
        
        services = get_authenticated_google_services(
            tool_context, google_auth_scheme, google_auth_credential,
            GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET
        )
        
        if not services:
            return {"status": "pending", "message": "Awaiting Google authentication"}
        
        cal_service, drive_service = services
        
        # Get event details
        event = cal_service.events().get(calendarId='primary', eventId=event_id).execute()
        summary = event.get('summary', 'No Title')
        start = event['start'].get('dateTime', event['start'].get('date'))
        meet_link = event.get('hangoutLink')
        
        if not meet_link:
            return {"status": "error", "error_message": "No Google Meet link found for this event"}
        
        meet_code = get_meet_code(meet_link)
        event_time = datetime.fromisoformat(start.replace('Z', '+00:00'))
        media = check_for_transcript_and_recording(cal_service, drive_service, meet_code, summary, event_time)
        
        if not media:
            return {"status": "error", "error_message": "No notes or transcript found for this meeting"}
        
        result = {
            "status": "success",
            "event_name": summary,
            "event_time": start
        }
        
        if media.get('notes'):
            content = read_document_content(drive_service, media['notes']['id'])
            result['notes_content'] = content
            result['notes_link'] = media['notes']['link']
        
        if media.get('transcript'):
            content = read_document_content(drive_service, media['transcript']['id'])
            result['transcript_content'] = content
            result['transcript_link'] = media['transcript']['link']
        
        return result
    except Exception as e:
        return {"status": "error", "error_message": str(e)}


def process_manual_transcript(transcript_text: str, default_project: str = "WJR") -> dict:
    """Process manually pasted or uploaded transcript.
    
    Args:
        transcript_text: Raw transcript text
        default_project: Default Jira project key
    
    Returns:
        dict: Parsed transcript data
    """
    return parse_transcript(transcript_text, default_project)
