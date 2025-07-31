import logging
import time
from pywa import WhatsApp
from pywa.types import Message, CallbackButton, Button, MessageStatus, MessageStatusType, Template

from guests import GuestsManager, ResponseStatus, SendState, Guest
from consts import *


class RSVPBot:
    """WhatsApp RSVP Bot"""
    
    def __init__(self, 
                 guests: GuestsManager,
                 wa: WhatsApp,
                 invitation_url: str,
                 group_invite: str,
                 template_name: str = "rsvp_invitation",
                 reminder_template_name: str = "rsvp_reminder"):
        self.wa = wa
        self.invitation_url = invitation_url
        self.group_invite = group_invite
        self.template_name = template_name
        self.reminder_template_name = reminder_template_name
        self.guests = guests
        
        # Register message handlers
        self._register_handlers()

        self.invitiation_buttons = [
            Button("כן אני אגיע!", ResponseStatus.COMING.name),
            Button("לצערי לא", ResponseStatus.NOT_COMING.name),
            Button("עוד לא יודעים", ResponseStatus.UNSURE.name)
        ]
        self.template_buttons = [
            Template.QuickReplyButtonData(ResponseStatus.COMING.name),
            Template.QuickReplyButtonData(ResponseStatus.NOT_COMING.name),
            Template.QuickReplyButtonData(ResponseStatus.UNSURE.name)
        ]
    
    def _register_handlers(self):
        """Register WhatsApp message handlers"""

        @self.wa.on_callback_button()
        def handle_button(client: WhatsApp, btn: CallbackButton):
            btn.mark_as_read()
            self._handle_rsvp_response(btn)
        
        @self.wa.on_message_status()
        def handle_message_status(client: WhatsApp, status: MessageStatus):
            self._handle_message_status(status)
            
        @self.wa.on_message()
        def handle_general_message(client: WhatsApp, msg: Message):
            msg.mark_as_read()
            self._handle_general_message(msg)
    
    def _handle_rsvp_response(self, btn: CallbackButton):
        """Handle responses"""
        try:
            guest = self.guests.get_guest_by_phone(btn.from_user.wa_id)
            if not guest:
                self.wa.send_message(
                    to=btn.from_user.wa_id,
                    text=UNKNOWN_GUEST_RESPONSE
                )
                return
            
            response_status = ResponseStatus[btn.data]

            # Update status
            self.guests.update_response_status(
                guest,
                response_status
            )
            
            if response_status == ResponseStatus.COMING:
                # Ask for guest count
                self.wa.send_message(
                    to=btn.from_user.wa_id,
                    text=RESPONSEֹֹ_COMING
                )
            elif response_status == ResponseStatus.NOT_COMING:
                self.wa.send_message(
                    to=btn.from_user.wa_id,
                    text=RESPONSE_NOT_COMING
                )
            elif response_status == ResponseStatus.UNSURE:
                self.wa.send_message(
                    to=btn.from_user.wa_id,
                    text=RESPONSE_UNSURE,
                    buttons=self.invitiation_buttons
                )
            
        except Exception as e:
            logging.exception(f"Error handling accept response")
    
    def _handle_message_status(self, status: MessageStatus):
        try:
            guest = self.guests.get_guest_by_phone(status.from_user.wa_id)
            if not guest:
                return

            update_func = None
            if status.tracker == "INVITATION":
                update_func = self.guests.update_invitation_state
            elif status.tracker == "REMINDER":
                update_func = self.guests.update_reminder_state
            
            if update_func:
                if status.status == MessageStatusType.SENT:
                    update_func(guest, SendState.SENT)
                elif status.status == MessageStatusType.DELIVERED:
                    update_func(guest, SendState.RECEIVED)
                elif status.status == MessageStatusType.READ:
                    update_func(guest, SendState.READ)
                elif status.status == MessageStatusType.FAILED:
                    logging.error(f"A message delivery has failed for {guest}")
                    update_func(guest, SendState.ERROR)

        except Exception as e:
            logging.exception(f"Error handling message status")
    
    def _handle_guest_count_response(self, guest: Guest, msg: Message):
        """Handle guest count responses"""
        try:
            guest_count = int(msg.text.strip())
            
            if guest_count <= 0:
                self.wa.send_message(
                    to=msg.from_user.wa_id,
                    text=RESPONSE_INVALID_GUEST_COUNT
                )
                return
            
            # Update guest count
            self.guests.update_response_status(
                guest,
                ResponseStatus.COMING, 
                expected_guests=guest_count
            )
            
            self.wa.send_message(
                to=msg.from_user.wa_id,
                text=RESPONSE_GUEST_COUNT+self.group_invite
            )
            
        except ValueError:
            self.wa.send_message(
                to=msg.from_user.wa_id,
                text=RESPONSE_INVALID_GUEST_COUNT
            )
        except Exception as e:
            logging.exception(f"Error handling guest count")
    
    def _handle_general_message(self, msg: Message):
        try:
            guest = self.guests.get_guest_by_phone(msg.from_user.wa_id)
            if not guest:
                logging.warning(f"Received message from unknown number {msg.from_user.wa_id}: {msg.text}")
                self.wa.send_message(
                    to=msg.from_user.wa_id,
                    text=UNKNOWN_GUEST_RESPONSE
                )
                return

            if not guest.whatsapp_name and msg.from_user.name:
                self.guests.update_whatsapp_name(guest.row_index, msg.from_user.name)
            
            if guest.invitation_state != None and msg.text and msg.text.isnumeric():
                self._handle_guest_count_response(guest, msg)
            else:
                logging.warning(f"Received unexpected message from {guest.full_name} ({guest.row_index}): {msg.text}")
                self.wa.send_message(
                    to=msg.from_user.wa_id,
                    text=RESPONSE_UNKNOWN
                )
                
        except Exception as e:
            logging.exception(f"Error handling general message")

    def send_template(self, template: Template, tracker: str, guest: Guest) -> bool:
        logging.debug(f"Sending template {tracker} to {guest.full_name}")
        try:
            sent_message = self.wa.send_template(
                to=guest.phone_number,
                template=template,
                tracker=tracker
            )
            logging.info(f"Sent template to {guest.full_name} at {guest.phone_number} <{sent_message.id}>")
            return True
        except Exception as e:
            logging.exception(f"Failed to send invitation to {guest.full_name}")
        return False
    
    def send_invitations(self, limit: int = 0) -> int:
        """
        Send invitations to all guests who haven't received one yet
        """
        try:
            uninvited_guests = self.guests.get_uninvited_guests()
            if limit:
                uninvited_guests = uninvited_guests[:limit]

            logging.info(f"Sending invitations ({limit})")
            sent_count = 0
            
            for guest in uninvited_guests:
                logging.info(f"Sending invitation to {guest.full_name}: {guest}")
                template = Template(
                    self.template_name,
                    language=Template.Language.HEBREW,
                    header=Template.Image(self.invitation_url),
                    body=[
                        Template.TextValue(guest.display_name, "name_and_greeting"),
                        Template.TextValue(INVITATION_DATE_AND_VENUE, "date_and_venue"),
                        Template.TextValue(INVITATION_EMOJI, "emoji")
                    ],
                    buttons=self.template_buttons
                )
                
                if self.send_template(template, "INVITATION", guest):
                    self.guests.update_invitation_state(guest, SendState.PROCESSED)
                    sent_count += 1

            logging.info(f"Successfuly sent {sent_count} / {len(uninvited_guests)} invitations")
            return sent_count
            
        except Exception as e:
            logging.exception(f"Error sending invitations")
            return 0
        
    def send_reminders(self, limit: int = 0) -> int:
        """
        Send invitations to all guests who haven't received one yet
        """
        try:
            unreminded_guests = self.guests.get_unreminded_guests()
            if limit:
                unreminded_guests = unreminded_guests[:limit]

            logging.info(f"Sending reminders ({limit})")
            sent_count = 0
            
            for guest in unreminded_guests:
                logging.info(f"Sending reminder to {guest.full_name}")
                template = Template(
                    self.reminder_template_name,
                    language=Template.Language.HEBREW,
                    header=Template.Image(self.invitation_url),
                    body=[
                        Template.TextValue(guest.display_name, None),
                        Template.TextValue(INVITATION_DATE_AND_VENUE, None),
                    ],
                    buttons=self.template_buttons
                )
                
                if self.send_template(template, "REMINDER", guest):
                    self.guests.update_reminder_state(guest, SendState.PROCESSED)
                    sent_count += 1

            logging.info(f"Successfuly sent {sent_count} / {len(unreminded_guests)} invitations")
            return sent_count
            
        except Exception as e:
            logging.exception(f"Error sending invitations")
            return 0