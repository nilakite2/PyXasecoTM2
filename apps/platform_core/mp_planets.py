"""ManiaPlanet server balance, donation bills and confirmed admin payouts."""

from dataclasses import dataclass
from html import escape
import logging
from secrets import randbelow
from time import monotonic

from pyxaseco.app_services import localdb_update_donations
from pyxaseco.core.widget_delivery import deliver_ui
from pyxaseco.helpers import strip_colors
from pyxaseco.maniaplanet_runtime import safe_login

from .donate import ML_ID_PAYMENT, _mindonation, _publicappr, _send_all, _send_login


logger = logging.getLogger(__name__)
SCORE_DONATE_BASE = 2801000
SCORE_DONATE_MAX = 100
CONFIRM_SECONDS = 30
MAX_OPEN_BILLS = 256


@dataclass(frozen=True)
class Bill:
    requester: str
    target: str
    amount: int
    donation: bool


@dataclass(frozen=True)
class Confirmation:
    player: object
    bill: Bill
    action: int
    expires: float


def _amount(text):
    if not isinstance(text, str) or not text.isascii() or not text.isdecimal() or len(text) > 10:
        return 0
    value = int(text)
    return value if 0 < value <= 2_147_483_647 else 0


def _payment_dialog(server_name, bill, action):
    server = strip_colors(server_name, for_tm=False)
    if len(server) > 45:
        server = server[:42] + '...'
    server = escape(server.replace('$', '$$'), quote=True)
    # Keep the exact recipient visible, even for a login too long for one row.
    lines = [bill.target[i:i + 36] for i in range(0, len(bill.target), 36)]
    question_y = -18 - 3.5 * len(lines)
    buttons_y = question_y - 6
    height = 9 - buttons_y
    parts = [
        f'<manialink id="{ML_ID_PAYMENT}" version="3"><frame pos="-52 {height / 2:g}">',
        f'<quad pos="0 0" z-index="0" size="104 {height:g}" style="Bgs1" substyle="BgTitlePage"/>',
        '<label pos="5 -4" z-index="1" size="94 4" textsize="2" textcolor="FFFFFFFF"'
        ' text="Initiating payment from server"/>',
        f'<label pos="5 -9" z-index="1" size="94 4" textsize="1" textcolor="DDE6EFFF" text="{server}"/>',
        f'<label pos="5 -14" z-index="1" size="94 4" textsize="1" textcolor="FFFFFFFF"'
        f' text="Pay {bill.amount} Planets to:"/>',
    ]
    for i, line in enumerate(lines):
        parts.append(f'<label pos="8 {-18 - 3.5 * i:g}" z-index="1" size="91 3.5" textsize="1"'
                     f' textcolor="FFFFFFFF" text="{escape(line, quote=True)}"/>')
    parts.extend([
        f'<label pos="5 {question_y:g}" z-index="1" size="94 4" textsize="1" textcolor="DDE6EFFF"'
        ' text="Pay now? The game may charge a fee."/>',
        f'<label pos="30 {buttons_y:g}" z-index="1" halign="center" style="CardButtonMedium" text="Yes" action="{action}"/>',
        f'<label pos="74 {buttons_y:g}" z-index="1" halign="center" style="CardButtonMedium" text="No" action="{action + 1}"/>',
        '</frame></manialink>',
    ])
    return ''.join(parts)


class Planets:
    def __init__(self):
        self.bills = {}
        self.confirmations = {}

    async def reply(self, aseco, login, text):
        await _send_login(aseco, login, '{#server}> ' + text)

    async def balance(self, aseco, command):
        login = command['author'].login
        try:
            amount = await self._balance(aseco)
        except Exception:
            await self.reply(aseco, login, '{#error}Server Planets balance is unavailable.')
        else:
            await self.reply(aseco, login, f'Server balance: {amount} Planets.')

    async def _balance(self, aseco):
        amount = await aseco.client.query('GetServerPlanets')
        if type(amount) is not int or amount < 0:
            raise ValueError('Unexpected server balance.')
        return amount

    async def _start_bill(self, aseco, bill):
        if (getattr(aseco.server, 'isrelay', False) or len(self.bills) >= MAX_OPEN_BILLS
                or any(b.requester == bill.requester and b.donation == bill.donation
                       for b in self.bills.values())):
            await self.reply(aseco, bill.requester, '{#error}Planets transaction unavailable or already pending.')
            return
        try:
            if bill.donation:
                bid = await aseco.client.query('SendBill', bill.requester, bill.amount,
                                              f'Donate {bill.amount} Planets to this server', '')
            else:
                bid = await aseco.client.query('Pay', bill.target, bill.amount,
                                              f'Server payment of {bill.amount} Planets')
            if type(bid) is not int or bid <= 0 or bid in self.bills:
                raise ValueError('Dedicated server did not return a new bill ID.')
        except Exception as error:
            logger.warning('[Planets] Bill could not be confirmed (%s)', type(error).__name__)
            await self.reply(aseco, bill.requester,
                             '{#error}Could not confirm the Planets transaction. Check for an existing bill before retrying.')
            return
        self.bills[bid] = bill
        await self.reply(aseco, bill.requester, 'Confirm the donation in the game.' if bill.donation
                         else 'Planets payment submitted; waiting for the result.')

    async def donate(self, aseco, command):
        player = command['author']
        if aseco.server.players.get_player(player.login) is not player:
            return
        amount = _amount((command.get('params') or '').strip())
        if amount < _mindonation:
            await self.reply(aseco, player.login, f'Use /donate <amount> (at least {_mindonation} Planets).')
            return
        await self._start_bill(aseco, Bill(player.login, '', amount, True))

    def _can_pay(self, aseco, player):
        return (not getattr(aseco.server, 'isrelay', False)
                and aseco.server.players.get_player(player.login) is player
                and aseco.allow_ability(player, 'pay'))

    async def pay(self, aseco, command):
        player = command['author']
        if not self._can_pay(aseco, player):
            await self.reply(aseco, player.login, '{#error}You do not have permission to pay from the server.')
            return
        args = (command.get('params') or '').split()
        target = safe_login(args[0]) if len(args) == 2 else None
        amount = _amount(args[1]) if target else 0
        if not amount or target.casefold() == aseco.server.serverlogin.casefold():
            await self.reply(aseco, player.login, 'Use /pay <player login> <amount> (not the server login).')
            return
        try:
            balance = await self._balance(aseco)
        except Exception:
            await self.reply(aseco, player.login, '{#error}Server Planets balance is unavailable; no payment sent.')
            return
        if amount > balance:
            await self.reply(aseco, player.login, f'{{#error}}Server has only {balance} Planets.')
            return
        action = 1300000000 + 2 * randbelow(100000000)
        bill = Bill(player.login, target, amount, False)
        self.confirmations[player.login] = Confirmation(player, bill, action, monotonic() + CONFIRM_SECONDS)
        server_name = getattr(aseco.server, 'name', '') or aseco.server.serverlogin
        xml = _payment_dialog(server_name, bill, action)
        await deliver_ui(aseco, 'SendDisplayManialinkPageToLogin', player.login, xml,
                         CONFIRM_SECONDS * 1000, True, remember=False)

    async def answer(self, aseco, answer):
        if len(answer) < 3:
            return
        login, action = answer[1:3]
        try:
            action = int(action)
        except (TypeError, ValueError):
            return
        confirmation = self.confirmations.get(login)
        if confirmation and action in (confirmation.action, confirmation.action + 1):
            self.confirmations.pop(login, None)
            await deliver_ui(aseco, 'SendDisplayManialinkPageToLogin', login,
                             f'<manialink id="{ML_ID_PAYMENT}" version="3"/>', 0, False, remember=False)
            if action == confirmation.action + 1:
                await self.reply(aseco, login, 'Payment cancelled.')
            elif monotonic() >= confirmation.expires or not self._can_pay(aseco, confirmation.player):
                await self.reply(aseco, login, '{#error}Payment confirmation expired or permission changed.')
            else:
                await self._start_bill(aseco, confirmation.bill)
            return
        if (SCORE_DONATE_BASE <= action < SCORE_DONATE_BASE + SCORE_DONATE_MAX
                and 'ui' in aseco.active_apps and getattr(aseco, 'score_phase', False)):
            from apps.ui.config import _state
            cfg = _state.donation_cfg
            amounts = cfg.get('amounts', ())
            index = action - SCORE_DONATE_BASE
            player = aseco.server.players.get_player(login)
            if player is not None and cfg.get('enabled') and index < len(amounts):
                await self.donate(aseco, {'author': player, 'params': str(amounts[index])})

    async def on_bill_updated(self, aseco, params):
        if len(params) < 4:
            return
        bill_id, state, _, txid = params[:4]
        if type(bill_id) is not int or type(state) is not int or state not in (4, 5, 6):
            return
        bill = self.bills.pop(bill_id, None)
        if bill is None:
            return
        if state != 4:
            await self.reply(aseco, bill.requester,
                             '{#error}Planets transaction refused.' if state == 5 else '{#error}Planets transaction failed.')
            return
        logger.info('[Planets] Confirmed %s of %d (bill %d; transaction %s)',
                    'donation' if bill.donation else 'payment', bill.amount, bill_id, txid)
        if not bill.donation:
            await self.reply(aseco, bill.requester, f'Paid {bill.amount} Planets to {bill.target}.')
            return
        try:
            await localdb_update_donations(aseco, bill.requester, bill.amount)
        except Exception:
            logger.exception('[Planets] Donation paid but local totals could not be updated')
        await aseco.release_event('onDonation', [bill.requester, bill.amount])
        if bill.amount >= _publicappr:
            await _send_all(aseco, f'{{#server}}> {bill.requester} donated {bill.amount} Planets. Thank you!')
        else:
            await self.reply(aseco, bill.requester, f'Thank you for donating {bill.amount} Planets!')

    def disconnect(self, _aseco, player):
        self.confirmations.pop(player.login, None)


def register(aseco):
    service = aseco._mp_planets = Planets()
    aseco.add_chat_command('donate', 'Donates Planets to the server')
    aseco.add_chat_command('planets', 'Shows the server Planets balance')
    aseco.add_chat_command('pay', 'Pays server Planets to a player after confirmation',
                           is_admin=True, public=False, permission='pay')
    aseco.register_event('onChat_donate', service.donate)
    aseco.register_event('onChat_planets', service.balance)
    aseco.register_event('onChat_pay', service.pay)
    aseco.register_event('onBillUpdated', service.on_bill_updated)
    aseco.register_event('onPlayerManialinkPageAnswer', service.answer)
    aseco.register_event('onPlayerDisconnect', service.disconnect)
