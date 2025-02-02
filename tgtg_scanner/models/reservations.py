import logging
from dataclasses import dataclass
import time
from typing import Callable, Dict, List

from tgtg_scanner.models.item import Item
from tgtg_scanner.tgtg import TgtgClient

log = logging.getLogger("tgtg")


@dataclass
class Order():
    id: str
    item_id: str
    amount: int
    display_name: str


@dataclass
class Reservation():
    item_id: str
    amount: int
    display_name: str

@dataclass
class Payment():
    order_id: str
    payload: str
    state: str


class Reservations():
    def __init__(self, client: TgtgClient) -> None:
        self.client = client
        self.reservation_query: List[Reservation] = []
        self.active_orders: Dict[str, Order] = {}

    def reserve(self, item_id: str,
                display_name: str,
                amount: int = 1) -> None:
        """Create a new reservation

        Args:
            item_id (str): Item ID
            display_name (str): Item display name
            amount (int, optional): Amount. Defaults to 1.
        """
        self.reservation_query.append(
            Reservation(item_id, amount, display_name))

    def make_orders(self, state: Dict[str, Item],
                    callback: Callable[[Reservation], None]) -> None:
        """Create orders for reservations

        Args:
            state (Dict[str, Item]): Current item state
            callback (Callable[[Reservation], None]): Callback for each order
        """
        for reservation in self.reservation_query:
            if state.get(reservation.item_id).items_available > 0:
                try:
                    self._create_order(reservation)
                    self.reservation_query.remove(reservation)
                    callback(reservation)
                except Exception as exc:
                    log.error("Create Order Error: %s", exc)

    def update_active_orders(self) -> None:
        """Remove orders that are not active anymore
        """
        for order_id in list(self.active_orders):
            res = self.client.get_order_status(order_id)
            if res.get("state") != "RESERVED":
                del self.active_orders[order_id]

    def cancel_order(self, order_id: str) -> None:
        """Cancel an order
        """
        self.client.abort_order(order_id)

    def cancel_all_orders(self) -> None:
        """Cancel all active orders
        """
        for order_id in list(self.active_orders):
            self.cancel_order(order_id)

    def _create_order(self, reservation: Reservation) -> None:
        res = self.client.create_order(
            reservation.item_id, reservation.amount)
        order_id = res.get("id")
        if order_id:
            order = Order(order_id,
                          reservation.item_id,
                          reservation.amount,
                          reservation.display_name)
            self.active_orders[order_id] = order

            # TODO remove
            self.pay_order(order_id)

    def pay_order(self, order_id: str) -> None:
        order_status = self.client.get_order_status(order_id)
        if order_status.get("state") != "RESERVED":
            log.info("Order with id %s is no lenger reserved.", order_id)
            return

        payment_init = self.client.init_payment(order_id)
        self._poll_payment(payment_init.get("payment_id"))

    def _poll_payment(self, payment_id: str):
        payment_status = self.client.poll_payment(payment_id)
        if payment_status.get("state") == "ADDITIONAL_AUTHORIZATION_REQUIRED":
            payload = payment_status.get("payload")
            log.info(payload)

        while payment_status.get("state") == "ADDITIONAL_AUTHORIZATION_REQUIRED":
            log.info("Waiting for external authorization.")
            time.sleep(1)
            payment_status = self.client.poll_payment(payment_id)

        raise Exception(payment_status.status_code, payment_status.content)
        
    def temp_test(self):
        reservation = Reservation(15159, 1, "Test item")
        self._create_order(reservation=reservation)