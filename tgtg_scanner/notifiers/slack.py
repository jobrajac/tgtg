import datetime
import logging
import random
from time import sleep
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
        self.mute = None
        self.app = None
        self.message_queue = queue.Queue()
        self._start_slack_socket(self)

        self.app = App(token=self.bot_token)
        self._register_commands()
        self._start_socket_thread()
        self._start_listener()

    def _register_commands(self):
        @self.app.command("/tgtg")
        def handle_command(body, ack, respond, logger):
            logger.info(body)
            ack(text="ok")

    def _start_socket_thread(self):
        slack_socket_thread = threading.Thread(target=SocketModeHandler(self.app, self.app_token).start)
        slack_socket_thread.daemon = True
        slack_socket_thread.start()

    def _start_listener(self):
        slack_queue_listener_thread = threading.Thread(target=SlackQueueListener(self.message_queue))
        slack_queue_listener_thread.daemon = True
        slack_queue_listener_thread.start()


    def _send(self, item: Item) -> None:
        """Send item information as Telegram message"""
        if self.mute and self.mute > datetime.datetime.now():
            return
        if self.mute:
            log.info("Reactivated Telegram Notifications")
            self.mute = None
        # message = self._unmask(self.body, item)
        # image = None
        # if self.image:
        #     image = self._unmask(self.image, item)
        # self._send_message(message, image)



class SlackQueueListener():
    def __init__(self, queue):
        self.queue = queue
        self._run()

    def _run(self):
        while True:
            item = self.queue.get()
            if item == "exit":
                break