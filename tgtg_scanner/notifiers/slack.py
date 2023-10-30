import datetime
import logging
import random
from time import sleep
import time
from tgtg_scanner.models import Config, Favorites, Item, Reservations
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
        self.cron = config.slack.get("cron")

        logging.debug(self.cron)

        log.debug(self.user_id)

        self.mute = None
        self.message_queue = queue.Queue()
        self.app = App(token=self.bot_token, logger=log)


        self._register_commands()
        self._start_socket_thread()
        self._start_listener()

    def _register_commands(self):
        @self.app.command("/tgtg")
        def handle_command(body, ack, respond, logger):
            logger.debug(body)
            ack(text="ok")

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
        self.message_queue(message)



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