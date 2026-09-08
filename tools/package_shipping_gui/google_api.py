from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .parser import extract_order_numbers
from .planner import SheetTab


SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/spreadsheets",
]


class GoogleApiUnavailable(RuntimeError):
    pass


@dataclass(frozen=True)
class EmailCandidate:
    message_id: str
    text: str


class GoogleApiClient:
    def __init__(self, credentials_file: Path, token_file: Path):
        self.credentials_file = credentials_file
        self.token_file = token_file
        self.gmail = None
        self.sheets = None

    def connect(self) -> None:
        try:
            from google.auth.transport.requests import Request
            from google.oauth2.credentials import Credentials
            from google_auth_oauthlib.flow import InstalledAppFlow
            from googleapiclient.discovery import build
        except ImportError as exc:
            raise GoogleApiUnavailable(
                "Google API packages are not installed. Install google-api-python-client, "
                "google-auth-httplib2, google-auth-oauthlib."
            ) from exc

        creds = None
        if self.token_file.exists():
            creds = Credentials.from_authorized_user_file(str(self.token_file), SCOPES)
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                if not self.credentials_file.exists():
                    raise GoogleApiUnavailable(
                        f"OAuth client secret is missing: {self.credentials_file}"
                    )
                flow = InstalledAppFlow.from_client_secrets_file(str(self.credentials_file), SCOPES)
                creds = flow.run_local_server(port=0)
            self.token_file.parent.mkdir(parents=True, exist_ok=True)
            self.token_file.write_text(creds.to_json(), encoding="utf-8")

        self.gmail = build("gmail", "v1", credentials=creds)
        self.sheets = build("sheets", "v4", credentials=creds)

    def find_order_numbers(self, tracking_number: str) -> list[str]:
        if self.gmail is None:
            raise GoogleApiUnavailable("Google API client is not connected")
        result = (
            self.gmail.users()
            .messages()
            .list(userId="me", q=f'in:anywhere "{tracking_number}"', maxResults=10)
            .execute()
        )
        order_numbers: list[str] = []
        for message in result.get("messages", []):
            detail = (
                self.gmail.users()
                .messages()
                .get(userId="me", id=message["id"], format="full")
                .execute()
            )
            for number in extract_order_numbers(_message_text(detail)):
                if number not in order_numbers:
                    order_numbers.append(number)
        return order_numbers

    def list_sheet_tabs_with_h2(self, spreadsheet_id: str) -> list[SheetTab]:
        if self.sheets is None:
            raise GoogleApiUnavailable("Google API client is not connected")
        metadata = self.sheets.spreadsheets().get(spreadsheetId=spreadsheet_id).execute()
        sheets = metadata.get("sheets", [])
        ranges = [
            f"'{_escape_sheet_name(sheet['properties']['title'])}'!H2"
            for sheet in sheets
        ]
        value_ranges = []
        if ranges:
            value_result = (
                self.sheets.spreadsheets()
                .values()
                .batchGet(
                    spreadsheetId=spreadsheet_id,
                    ranges=ranges,
                    majorDimension="ROWS",
                )
                .execute()
            )
            value_ranges = value_result.get("valueRanges", [])

        tabs = []
        for index, sheet in enumerate(sheets):
            props = sheet["properties"]
            title = props["title"]
            value = ""
            rows = value_ranges[index].get("values", []) if index < len(value_ranges) else []
            if rows and rows[0]:
                value = rows[0][0]
            tabs.append(SheetTab(sheet_id=props["sheetId"], title=title, current_h2=value))
        return tabs

    def write_h2_values(self, spreadsheet_id: str, sheet_ids: list[int], amount: int) -> None:
        if self.sheets is None:
            raise GoogleApiUnavailable("Google API client is not connected")
        requests = [
            {
                "repeatCell": {
                    "range": {
                        "sheetId": sheet_id,
                        "startRowIndex": 1,
                        "endRowIndex": 2,
                        "startColumnIndex": 7,
                        "endColumnIndex": 8,
                    },
                    "cell": {"userEnteredValue": {"numberValue": amount}},
                    "fields": "userEnteredValue",
                }
            }
            for sheet_id in sheet_ids
        ]
        self.sheets.spreadsheets().batchUpdate(
            spreadsheetId=spreadsheet_id, body={"requests": requests}
        ).execute()


def spreadsheet_id_from_url(value: str) -> str:
    marker = "/spreadsheets/d/"
    if marker in value:
        rest = value.split(marker, 1)[1]
        return rest.split("/", 1)[0]
    return value.strip()


def _escape_sheet_name(name: str) -> str:
    return name.replace("'", "''")


def _message_text(message: dict) -> str:
    parts = []
    payload = message.get("payload", {})
    _collect_parts(payload, parts)
    return "\n".join(parts)


def _collect_parts(part: dict, output: list[str]) -> None:
    body = part.get("body", {})
    data = body.get("data")
    if data:
        import base64

        output.append(base64.urlsafe_b64decode(data + "==="[: len(data) % 4]).decode("utf-8", "ignore"))
    for child in part.get("parts", []) or []:
        _collect_parts(child, output)
