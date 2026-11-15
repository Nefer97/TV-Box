"""Tastiera e mouse virtuali (uinput): per Chrome sono tasti e clic veri."""


class VirtualInput:
    KEYS = {"up": "KEY_UP", "down": "KEY_DOWN", "left": "KEY_LEFT", "right": "KEY_RIGHT",
            "enter": "KEY_ENTER", "esc": "KEY_ESC", "space": "KEY_SPACE", "tab": "KEY_TAB",
            "backspace": "KEY_BACKSPACE"}

    def __init__(self):
        from evdev import UInput
        from evdev import ecodes as E
        self.E = E
        self.codes = {k: getattr(E, v) for k, v in self.KEYS.items()}
        self.kbd = UInput({E.EV_KEY: list(self.codes.values())}, name="tvbox-keyboard")
        self.mouse = UInput({E.EV_KEY: [E.BTN_LEFT, E.BTN_RIGHT],
                             E.EV_REL: [E.REL_X, E.REL_Y, E.REL_WHEEL]}, name="tvbox-mouse")

    def key(self, name):
        code = self.codes[name]
        for v in (1, 0):
            self.kbd.write(self.E.EV_KEY, code, v)
            self.kbd.syn()

    def move(self, dx, dy):
        if dx:
            self.mouse.write(self.E.EV_REL, self.E.REL_X, dx)
        if dy:
            self.mouse.write(self.E.EV_REL, self.E.REL_Y, dy)
        self.mouse.syn()

    def click(self):
        for v in (1, 0):
            self.mouse.write(self.E.EV_KEY, self.E.BTN_LEFT, v)
            self.mouse.syn()
