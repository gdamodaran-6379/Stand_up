"""Main agent configuration for Standup Agent."""

from google.adk.agents import Agent
from google.adk.tools import FunctionTool

from .config import (
    google_auth_scheme,
    google_auth_credential,
    jira_auth_scheme,
    jira_auth_credential,
    GOOGLE_CLIENT_ID,
    GOOGLE_CLIENT_SECRET,
    JIRA_SITE_URL,
)
from .tools import (
    fetch_calendar_events,
    get_meeting_notes,
    parse_transcript,
    validate_jira_tickets,
    generate_jira_comment,
    post_jira_comment,
    process_manual_transcript
)
from .prompts import FULL_INSTRUCTION

# Create FunctionTools
fetch_calendar_events_tool = FunctionTool(func=fetch_calendar_events)
get_meeting_notes_tool = FunctionTool(func=get_meeting_notes)
parse_transcript_tool = FunctionTool(func=parse_transcript)
validate_jira_tickets_tool = FunctionTool(func=validate_jira_tickets)
generate_jira_comment_tool = FunctionTool(func=generate_jira_comment)
post_jira_comment_tool = FunctionTool(func=post_jira_comment)
process_manual_transcript_tool = FunctionTool(func=process_manual_transcript)

# Create the Standup Agent
root_agent = Agent(
    name="standup_agent",
    model="gemini-2.0-flash",
    description=(
        "Standup Agent converts meeting transcripts into structured Jira comments. "
        "It extracts ticket references, validates them via Jira API, and posts "
        "timestamped comments with full transparency and user approval."
    ),
    instruction=FULL_INSTRUCTION,
    tools=[
        fetch_calendar_events_tool,
        get_meeting_notes_tool,
        parse_transcript_tool,
        validate_jira_tickets_tool,
        generate_jira_comment_tool,
        post_jira_comment_tool,
        process_manual_transcript_tool,
    ],
)

__all__ = ['root_agent']
