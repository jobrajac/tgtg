import datetime
import logging
import random
from time import sleep
import time
from tgtg_scanner.models import Config, Favorites, Item, Reservations
from tgtg_scanner.models.cron import Cron
from tgtg_scanner.models.errors import (MaskConfigurationError)
from tgtg_scanner.models.favorites import (AddFavoriteRequest,
                                           RemoveFavoriteRequest)
from tgtg_scanner.models.reservations import Order, Reservation
from tgtg_scanner.notifiers.base import Notifier
import queue
import threading
from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler

log = logging.getLogger('tgtg')

class Slack(Notifier):
   
    MAX_RETRIES = 10

    def __init__(self, config: Config, reservations: Reservations,
                 favorites: Favorites):
        self.config = config
        self.enabled = config.slack.get("enabled", False)
        self.app_token = config.slack.get("app_token")
        self.bot_token = config.slack.get("bot_token")
        self.user_id = config.slack.get("user_id")
        self.cron = Cron()
        self.favorites = favorites

        logging.debug(self.cron)

        log.debug(self.user_id)

        self.mute = None

        self.commands = [
            ('help', 'Information about available commands', self._help),
            ('mute', 'Deactivate Slack notifications for 1 or x days', self._mute),
            ('unmute', 'Reactivate Slack notifications', self._unmute),
            ('reserve', 'Reserve the next available Magic Bag', self._reserve_item_menu),
            ('listfavorites', 'List all favorites', self._list_favorites),
        ]

        self.message_queue = queue.Queue()
        self.app = App(token=self.bot_token, logger=log)

        self._register_commands()
        self._start_socket_thread()
        self._start_listener()
        self._check_websocket_status()

    def _check_websocket_status(self):
        while True:
            try:
                response = self.app.client.auth_test()
                if response["ok"]:
                    return
                else:
                    print("No response from Slack socket connection...")

            except Exception as e:
                print("Error checking Slack WebSocket status:", e)
            
            time.sleep(1)

    def _start_socket_thread(self):
        slack_socket_thread = threading.Thread(target=SocketModeHandler(self.app, self.app_token).start)
        slack_socket_thread.daemon = True
        slack_socket_thread.start()
        log.debug("Slack socket thread started")

    def _start_listener(self):
        slack_queue_listener_thread = threading.Thread(target=SlackQueueListener(self.app, self.user_id, self.message_queue).start)
        slack_queue_listener_thread.daemon = True
        slack_queue_listener_thread.start()
        log.debug("Slack message queue listener thread started")



    def _send(self, item: Item) -> None:
        """Send item information as Slack message"""
        if self.mute and self.mute > datetime.datetime.now():
            return
        if self.mute:
            log.info("Reactivated Slack Notifications")
            self.mute = None

        self._send_message("test")

    def _send_message(self, message):
        log.info("%s message: %s", self.name, message)
        self.message_queue.put(message)

    def _mute(self, respond, days="1", *args):
        """Deactivates Slack notifications for x days"""
        days = int(days)
        self.mute = datetime.datetime.now() + datetime.timedelta(days=days)
        log.info('Deactivated Slack notifications for %s days', days)
        log.info('Reactivation at %s', self.mute)

        resp = f"Deactivated Telegram Notifications for {days} days.\nReactivating at {self.mute} or use /unmute."
        respond(self._format_markdown_response(resp))

    
    def _unmute(self, respond, *args):
        """Reactivate Slack notifications"""
        self.mute = None
        log.info("Reactivated Slack notifications")
        resp = "Reactivated Slack notifications"
        respond(self._format_markdown_response(resp))

    
    def _reserve_item_menu(self, respond, *args):
        buttons = [[
            self._get_slack_button(
                f"{item.display_name}: {item.items_available}",
                item)
        ] for item in self.favorites.get_favorites()]
        
        if len(buttons) == 0:
            respond("No bags to reserve.")
            return
        
        respond(self._format_markdown_response("Select a bag to reserve:", buttons))


    def _list_favorites(self, respond, *args):
        """List all favorites"""
        favorites = self.favorites.get_favorites()
        if not favorites:
            return "You currently don't have any favorites."
        
        resp = "\n".join([f"• {item.item_id} - {item.display_name}"
                        for item in favorites])
        respond(self._format_markdown_response(resp))
        
    def _help(self, respond):
        resp = "Available commands:\n"
        for (command, text, _) in self.commands:
            if command == "help":
                continue
            resp += f"*{command}:* {text}\n"
        respond(self._format_markdown_response(resp))

    def _get_slack_button(self, text, value):
        return {
            "type": "button",
            "text": {
                "type": "plain_text",
                "text": text
            },
            "value": value
        }

    def _format_markdown_response(self, text, buttons=[]):
        return {
            "blocks": [
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": text
                    }
                }
            ],
            "text": 'Could not generate markdown response.'
        }
    
    def _register_commands(self):
        @self.app.command("/tgtg")
        def handle_command(body, ack, respond, logger):
            log.debug(body)
            ack()
            command_parts = body["text"].split()
            if len(command_parts) <= 0:
                response_text = self._help()
                respond(self._format_markdown_response(response_text))

            command = command_parts[0]
            args = command_parts[1:] if len(command_parts) > 1 else []
            
            for (command_key, _, func) in self.commands:
                if command == command_key:
                    resp = func(respond, *args) 
                    return
            respond(self._format_markdown_response("I did not recognize that.\nType */tgtg help* for available commands."))   

class SlackQueueListener():
    def __init__(self, app, user_id, queue):
        self.app = app
        self.user_id = user_id
        self.queue = queue

    def start(self):
        while True:
            item = self.queue.get()
            if item == "exit":
                break
            self._send_message(item)

    def _send_message(self, message):
        conv = self.app.client.conversations_open(users=self.user_id)
        if conv["ok"] != True:
            log.error("Could not open slack conversation with user.")
        self.app.client.chat_postMessage(
            channel=conv["channel"]["id"],
            text="Hi there!\n",
            blocks=[
                {
                    "type": "section",
                    "block_id": "b",
                    "text": {
                        "type": "mrkdwn",
                        "text": message,
                    },
                    # "accessory": {
                    #     "type": "button",
                    #     "action_id": "reserve_button_clicked",
                    #     "text": {"type": "plain_text", "text": "Reserve"},
                    #     "value": "click_me_123",
                    # },
                }
            ],
        )