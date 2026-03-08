from aiogram.fsm.state import StatesGroup, State

class AddBotState(StatesGroup):
    waiting_for_token = State()
    waiting_for_role = State()


class WelcomeStates(StatesGroup):
    waiting_text = State()
    waiting_photo = State()
    waiting_buttons = State()


class DelayedStates(StatesGroup):
    waiting_text = State()
    waiting_photo = State()
    waiting_buttons = State()
    waiting_delay = State()


class BroadcastStates(StatesGroup):
    waiting_text = State()
    waiting_buttons = State()
    waiting_when = State()
    waiting_time = State()
    confirm = State()


class RenameStates(StatesGroup):
    choose_type = State()
    choose_regions = State()
    waiting_new_name = State()


class AvatarStates(StatesGroup):
    waiting_photo = State()


class MassAddBotState(StatesGroup):
    waiting_for_tokens = State()
    waiting_for_role = State()


class MassBroadcastStates(StatesGroup):
    selecting_bots = State()
    waiting_text = State()
    waiting_buttons = State()
    waiting_when = State()
    waiting_time = State()
    confirm = State()


class MassRoleStates(StatesGroup):
    selecting_bots = State()
    selecting_role = State()


class KeyStates(StatesGroup):
    waiting_full_name = State()
    waiting_short_name = State()
    waiting_farm_text = State()
    assign_bots = State()


class KeyAddBotStates(StatesGroup):
    waiting_tokens = State()
    waiting_role = State()


class KeyBroadcastStates(StatesGroup):
    selecting_bots = State()
    waiting_text = State()
    waiting_buttons = State()
    waiting_when = State()
    waiting_time = State()
    confirm = State()


class KeyRoleStates(StatesGroup):
    selecting_bots = State()
    selecting_role = State()
