from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
from enum import Enum
import logging
import re

import gspread
from google.oauth2.service_account import Credentials

class InvitationState(Enum):
    PROCESSED = "⏱"
    SENT = "✔"
    RECEIVED = "✔✔"
    READ = "☑☑"

class ResponseStatus(Enum):
    COMING = "מגיע"
    NOT_COMING = "לא מגיע"
    UNSURE = "לא יודע"

@dataclass
class Guest:
    """Data class representing a guest"""
    first_name: str
    last_name: str
    display_name: str
    phone_number: str
    whatsapp_name: str
    should_send: bool = False
    invitation_state: Optional[InvitationState] = None
    response: Optional[ResponseStatus] = None
    expected_guests: Optional[int] = None
    row_index: Optional[int] = None

# Column mappings
class Columns(Enum):
    first_name = 0
    last_name = 1
    phone_number = 6
    display_name = 8
    should_send = 9
    invitation_state = 10
    response = 11
    expected_guests = 12
    whatsapp_name = 13

class GuestsManager:
    """Handles Google Sheets operations for RSVP management"""
    
    def __init__(self, credentials: Credentials, spreadsheet_id: str, worksheet_id: str):
        """
        Initialize Google Sheets RSVP Manager
        
        Args:
            credentials_path: Path to Google Service Account credentials JSON
            spreadsheet_id: Google Sheets spreadsheet ID
        """
        self.credentials = credentials
        self.spreadsheet_id = spreadsheet_id
        self.worksheet_id = worksheet_id
        
        
        # Initialize connection
        self._init_connection()

    @staticmethod
    def creds_from_file(credentials_path):
        scope = [
            'https://www.googleapis.com/auth/spreadsheets',
            'https://www.googleapis.com/auth/drive'
        ]

        return Credentials.from_service_account_file(
            credentials_path, 
            scopes=scope
        )
        
    def _init_connection(self):
        """Initialize Google Sheets connection"""
        try:
            
            self.gc = gspread.authorize(self.credentials)
            self.sheet = self.gc.open_by_key(self.spreadsheet_id).get_worksheet_by_id(self.worksheet_id)
                        
        except Exception as e:
            logging.exception(f"Failed to initialize Google Sheets connection")
            raise
    
    PHONE_REGEX = re.compile(r'[^\d]')
    def _normalize_phone(self, phone: str) -> str:
        return self.PHONE_REGEX.sub("", phone)
    
    def _row_to_guest(self, row_data: List, row_index: int) -> Guest:
        """Convert sheet row to Guest object"""
        row_data.extend(["" for _ in range(max([c.value for c in Columns]) - len(row_data) + 1)])
        assert len(row_data) > max([c.value for c in Columns])

        try:
            guest_dict = {
                c.name: row_data[c.value] for c in Columns
            }

            guest_dict['should_send'] = guest_dict['should_send'] == 'TRUE'
            guest_dict['phone_number'] = self._normalize_phone(guest_dict['phone_number'])
            guest_dict['invitation_state'] = InvitationState(guest_dict['invitation_state']) if guest_dict['invitation_state'] else None
            guest_dict['response'] = ResponseStatus(guest_dict['response']) if guest_dict['response'] else None
            guest_dict['expected_guests'] = int(guest_dict['expected_guests']) if guest_dict['expected_guests'] else None

            return Guest(
                **guest_dict,
                row_index=row_index
            )
        except (ValueError, IndexError) as e:
            logging.exception(f"Error converting row to guest")
            return None
        
    def get_guest_by_phone(self, phone: str) -> Optional[Guest]:
        """
        Get guest by phone number
        
        Args:
            phone: Phone number to search for
            
        Returns:
            Guest object if found, None otherwise
        """
        try:
            logging.debug(f"Getting guest for phone number {phone}")
            all_rows = self.sheet.get_all_values()[1:]  # Skip header row
            normalized_phone = self._normalize_phone(phone)
            
            for i, row in enumerate(all_rows):
                if len(row) > Columns.phone_number.value:
                    row_phone = self._normalize_phone(row[Columns.phone_number.value])
                    if row_phone == phone:
                        guest = self._row_to_guest(row, i+2)  # +2 for header and 0-indexing
                        if guest:
                            return guest
            
            logging.warn(f"Unkown phone number {phone}")
            return None
            
        except Exception as e:
            logging.exception(f"Error getting guest by phone")
            return None
    
    def get_all_guests(self) -> List[Guest]:
        """
        Get all guests from the sheet
        
        Returns:
            List of Guest objects
        """
        try:
            all_rows = self.sheet.get_all_values()[1:]  # Skip header row
            guests = []
            
            for i, row in enumerate(all_rows):
                if row and any(row):  # Skip empty rows
                    guest = self._row_to_guest(row, i + 2)
                    if guest:
                        guests.append(guest)
            
            return guests
            
        except Exception as e:
            logging.exception(f"Error getting all guests")
            raise
        
    def get_guest_by_row(self, row_id) -> Optional[Guest]:
        """
        Get guest at specified row
        
        Returns:
            Guest object
        """
        logging.debug(f"Getting guest at row {row_id}")
        try:
            row_values = self.sheet.row_values(row_id)
            return self._row_to_guest(row_values, row_id)
        except Exception as e:
            logging.exception(f"Error getting getting guest")
            raise
    
    def get_uninvited_guests(self) -> List[Guest]:
        """
        Get guests who haven't been sent invitations yet
        
        Returns:
            List of Guest objects who haven't received invitations
        """
        all_guests = self.get_all_guests()
        return [guest for guest in all_guests if guest.should_send and not guest.invitation_state]
    
    def update_invitation_state(self, row_index: int, state: InvitationState) -> bool:
        """
        Update invitation status for a guest
        
        Args:
            phone: Guest's phone number
            sent: Whether invitation was sent
            
        Returns:
            bool: True if successful, False otherwise
        """
        logging.debug(f"Updating invitation state for row {row_index} to {state}")
        try:
            guest = self.get_guest_by_row(row_index)
            if not guest:
                logging.warning(f"Guest not found for row: {row_index}")
                return False
            
            self.sheet.update_cell(
                guest.row_index, 
                Columns.invitation_state.value + 1,
                state.value
            )
            
            logging.info(f"Updated invitation sent status for {guest.first_name} {guest.last_name} to {state}")
            return True
            
        except Exception as e:
            logging.exception(f"Error updating invitation status")
            return False
        
    def update_response_status(self, row_index: int, status: ResponseStatus, expected_guests: Optional[int] = None) -> bool:
        """
        Update guest response status and expected guests
        
        Args:
            phone: Guest's phone number
            status: Response status (Accepted, Declined, Unsure, Pending)
            expected_guests: Number of expected guests (optional)
            
        Returns:
            bool: True if successful, False otherwise
        """
        logging.debug(f"Updating response status for row {row_index} to {status}")
        try:
            guest = self.get_guest_by_row(row_index)
            if not guest:
                logging.warning(f"Guest not found for row: {row_index}")
                return False
            
            # Update response status
            self.sheet.update_cell(
                guest.row_index, 
                Columns.response.value + 1,
                status.value
            )
            
            # Update expected guests if provided
            if expected_guests is not None:
                self.sheet.update_cell(
                    guest.row_index, 
                    Columns.expected_guests.value + 1,
                    expected_guests
                )
            
            logging.info(f"Updated response for {guest.first_name} {guest.last_name}: {status}" + f" ({expected_guests})" if expected_guests else "")
            return True
            
        except Exception as e:
            logging.error(f"Error updating response status")
            return False    
    
    def update_whatsapp_name(self, row_index: int, whatsapp_name: str) -> bool:
        logging.debug(f"Updating whatsapp name for row {row_index} to {whatsapp_name}")
        try:
            self.sheet.update_cell(
                row_index,
                Columns.whatsapp_name.value + 1,
                whatsapp_name
            )
            
            logging.info(f"Updating whatsapp name for row {row_index} to {whatsapp_name}")
            return True
            
        except Exception as e:
            logging.error(f"Error updating whatsapp name")
            return False    