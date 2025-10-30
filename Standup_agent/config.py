"""Configuration for Standup Agent authentication."""

from google.adk.auth import AuthCredential, AuthCredentialTypes, OAuth2Auth
from fastapi.openapi.models import OAuth2, OAuthFlows, OAuthFlowAuthorizationCode

from .utils import load_oauth_credentials, GOOGLE_SCOPES, JIRA_SCOPES

# Load Google OAuth credentials
GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET = load_oauth_credentials()

# Google OAuth2 configuration
google_auth_scheme = OAuth2(
    flows=OAuthFlows(
        authorizationCode=OAuthFlowAuthorizationCode(
            authorizationUrl="https://accounts.google.com/o/oauth2/auth",
            tokenUrl="https://oauth2.googleapis.com/token",
            scopes=GOOGLE_SCOPES,
        )
    )
)

google_auth_credential = AuthCredential(
    auth_type=AuthCredentialTypes.OAUTH2,
    oauth2=OAuth2Auth(
        client_id=GOOGLE_CLIENT_ID,
        client_secret=GOOGLE_CLIENT_SECRET,
    ),
)

# Jira OAuth2 configuration (Atlassian)
JIRA_CLIENT_ID = "Nt6B1qBlZUUvhzjOb3GqNLBuZS42ocdy"
JIRA_CLIENT_SECRET = "ATOAe8z17GQ0MQ1sCXxjiWY7insyTMRgXeGmQg7-mJasxocBdMDPUCAIcRatxAUv1k_kC3835C0F"
JIRA_SITE_URL = "wow-sandbox2.atlassian.net"

jira_auth_scheme = OAuth2(
    flows=OAuthFlows(
        authorizationCode=OAuthFlowAuthorizationCode(
            authorizationUrl="https://auth.atlassian.com/authorize",
            tokenUrl="https://auth.atlassian.com/oauth/token",
            scopes=JIRA_SCOPES,
        )
    )
)

jira_auth_credential = AuthCredential(
    auth_type=AuthCredentialTypes.OAUTH2,
    oauth2=OAuth2Auth(
        client_id=JIRA_CLIENT_ID,
        client_secret=JIRA_CLIENT_SECRET,
    ),
)
