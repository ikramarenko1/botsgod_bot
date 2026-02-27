from aiogram.fsm.state import StatesGroup, State

class AddBotState(StatesGroup):
    waiting_for_token = State()


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