import logging
import time
from pywa import WhatsApp
from pywa.types import Message, CallbackButton, Button, MessageStatus, MessageStatusType, Template

from guests import GuestsManager, ResponseStatus, InvitationState, Guest
from consts import *


class RSVPBot:
    """WhatsApp RSVP Bot"""
    
    def __init__(self, 
                 guests: GuestsManager,
                 wa: WhatsApp,
                 invitation_url: str,
                 group_invite: str,
                 template_name: str = "rsvp_invitation"):
        self.wa = wa
        self.invitation_url = invitation_url
        self.group_invite = group_invite
        self.template_name = template_name
        self.guests = guests
        
        # Register message handlers
        self._register_handlers()

        self.invitiation_buttons = [
            Button("כן אני אגיע!", ResponseStatus.COMING.name),
            Button("לצערי לא", ResponseStatus.NOT_COMING.name),
            Button("עוד לא יודעים", ResponseStatus.UNSURE.name)
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

            if status.tracker == "INVITATION":
                if status.status == MessageStatusType.SENT:
                    self.guests.update_invitation_state(guest, InvitationState.SENT)
                elif status.status == MessageStatusType.DELIVERED:
                    self.guests.update_invitation_state(guest, InvitationState.RECEIVED)
                elif status.status == MessageStatusType.READ:
                    self.guests.update_invitation_state(guest, InvitationState.READ)
                elif status.status == MessageStatusType.FAILED:
                    logging.error(f"A message delivery has failed for {guest}")
                    self.guests.update_invitation_state(guest, InvitationState.ERROR)

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
                self.wa.send_message(
                    to=msg.from_user.wa_id,
                    text=RESPONSE_UNKNOWN
                )
                
        except Exception as e:
            logging.exception(f"Error handling general message")
    
    def send_invitations(self, limit: int = 0) -> int:
        """
        Send invitations to all guests who haven't received one yet
        
        Returns:
            Number of invitations sent
        """
        try:
            uninvited_guests = self.guests.get_uninvited_guests()
            if limit:
                uninvited_guests = uninvited_guests[:limit]
            sent_count = 0

            logging.info(f"Sending invites ({limit})")
                        
            for guest in uninvited_guests:
                full_name = f"{guest.first_name} {guest.last_name}"
                logging.info(f"Sending invitation to {full_name}: {guest}")
                try:
                    # Send invitation message
                    sent_message = self.wa.send_template(
                        to=guest.phone_number,
                        template=Template(
                            self.template_name,
                            language=Template.Language.HEBREW,
                            header=Template.Image(self.invitation_url),
                            body=[
                                Template.TextValue(guest.display_name, "name_and_greeting"),
                                Template.TextValue(INVITATION_DATE_AND_VENUE, "date_and_venue"),
                                Template.TextValue(INVITATION_EMOJI, "emoji")
                            ],
                            buttons=[
                                Template.QuickReplyButtonData(ResponseStatus.COMING.name),
                                Template.QuickReplyButtonData(ResponseStatus.NOT_COMING.name),
                                Template.QuickReplyButtonData(ResponseStatus.UNSURE.name)
                            ]
                        ),
                        tracker="INVITATION"
                    )
                    
                    # sent_message = self.wa.send_image(
                    #     to=guest.phone_number,
                    #     image="https://storage.googleapis.com/zimun-rsvp/invitation_sample.png",
                    #     caption=INVITATION_TEXT.format(
                    #         name=display_name,
                    #         date_and_venue=INVITATION_DATE_AND_VENUE,
                    #         emoji=INVITATION_EMOJI
                    #     ),
                    #     buttons=self.invitiation_buttons,
                    #     tracker="INVITATION"
                    # )
                    
                    # Update invitation sent status
                    logging.info(f"Sent invitation to {full_name} at {guest.phone_number} <{sent_message.id}>")
                    self.guests.update_invitation_state(guest, InvitationState.PROCESSED)
                    sent_count += 1
                    
                except Exception as e:
                    logging.exception(f"Failed to send invitation to {full_name}")
            
            logging.info(f"Sent {sent_count} invitations")
            return sent_count
            
        except Exception as e:
            logging.exception(f"Error sending invitations")
            return 0