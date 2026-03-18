from aiogram.fsm.state import State, StatesGroup


class SellFlow(StatesGroup):
    account_type = State()
    phone = State()


class DepositFlow(StatesGroup):
    amount = State()


class WithdrawFlow(StatesGroup):
    cryptobot_id = State()
    amount = State()


class AdminNoteFlow(StatesGroup):
    text = State()


class AdminSettingsFlow(StatesGroup):
    account_types = State()


class AdminTreasuryTopupFlow(StatesGroup):
    amount = State()


class AdminTopupUserFlow(StatesGroup):
    user_id = State()
    amount = State()


class AdminBroadcastFlow(StatesGroup):
    text = State()


class AdminBlacklistFlow(StatesGroup):
    phone = State()


class AdminAdminsFlow(StatesGroup):
    admin_id = State()
