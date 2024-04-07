import lvgl as lv
from binascii import hexlify
from io import BytesIO

from app import BaseApp, AppError
from embit import bip39
from gui.common import add_button, add_button_pair, align_button_pair
from gui.decorators import on_release
from gui.screens import Menu, NumericScreen, QRAlert, Alert, InputScreen
from gui.screens.mnemonic import MnemonicScreen
from helpers import SDCardFile

class QRWithSD(QRAlert):
    SAVE = 1
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # add save button
        btn = add_button("Save to SD card", on_release(self.save), scr=self)
        btn.align(self.close_button, lv.ALIGN.OUT_TOP_MID, 0, -20)

    def save(self):
        self.set_value(self.SAVE)

class Bip85MnemonicScreen(MnemonicScreen):
    QR = 1
    SD = 2
    LOAD = 3
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.load_btn = add_button(
            text="Use now (load to device)",
            scr=self,
            callback=on_release(self.load)
        )
        self.load_btn.align(self.table, lv.ALIGN.OUT_BOTTOM_MID, 0, 10)
        self.show_qr_btn, self.save_sd_btn = add_button_pair(
            text1="Show QR code",
            callback1=on_release(self.show_qr),
            text2="Save to SD card",
            callback2=on_release(self.save_sd),
            scr=self,
        )
        self.show_qr_btn.align(self.load_btn, lv.ALIGN.OUT_BOTTOM_MID, 0, 10)
        self.save_sd_btn.align(self.load_btn, lv.ALIGN.OUT_BOTTOM_MID, 0, 10)
        align_button_pair(self.show_qr_btn, self.save_sd_btn)

    def show_qr(self):
        self.set_value(self.QR)

    def save_sd(self):
        self.set_value(self.SD)

    def load(self):
        self.set_value(self.LOAD)

class App(BaseApp):
    """
    WalletManager class manages your wallets.
    It stores public information about the wallets
    in the folder and signs it with keystore's id key
    """

    button = "Deterministic custom derivation"
    name = "custom derivation"

    async def menu(self, show_screen):
        buttons = [
            (None, "Mnemonics"),
            (0, "24-word mnemonic"),
        ]

        # wait for menu selection
        menuitem = await show_screen(
            Menu(
                buttons,
                last=(255, None),
                title="What do you want to derive?",
                note="",
            )
        )

        # process the menu button:
        # back button
        if menuitem == 255:
            return False
        # get derivation index
        hint = await show_screen(
            InputScreen(title="Enter hint for custom derivation", note="Default: 0")
        )
        if hint is None:
            return True # stay in the menu
        note = "hint for derivation: %s" % hint

        fgp = hexlify(self.keystore.fingerprint).decode()
        # mnemonic menu items
        if menuitem == 0:
            num_words = 24
            mnemonic = bip39.mnemonic_to_seed_derived(self.keystore.mnemonic, hint)
            title = "Derived %d-word mnemonic" % num_words
            action = await show_screen(
                Bip85MnemonicScreen(mnemonic=mnemonic, title=title, note=note)
            )
            if action == Bip85MnemonicScreen.QR:
                await show_screen(
                    QRAlert(title=title, message=mnemonic, note=note)
                )
            elif action == Bip85MnemonicScreen.SD:
                fname = "%s-mnemonic-%d.txt" % (
                    fgp, num_words
                )
                with SDCardFile(fname, "w") as f:
                    f.write(mnemonic)
                await show_screen(
                    Alert(
                        title="Success",
                        message="Mnemonic is saved as\n\n%s" % fname,
                        button_text="Close",
                    )
                )
            elif action == Bip85MnemonicScreen.LOAD:
                await self.communicate(
                    BytesIO(b"set_mnemonic "+mnemonic.encode()), app="",
                )
                return False
            return True
        else:
            raise NotImplementedError("Not implemented")
        res = str(res)
        action = await show_screen(
            QRWithSD(title=title, message=res, note=note)
        )
        if action == QRWithSD.SAVE:
            fname = "%s-%s.txt" % (fgp, file_suffix)
            with SDCardFile(fname, "w") as f:
                f.write(res)
            await show_screen(
                Alert(
                    title="Success",
                    message="Data is saved as\n\n%s" % fname,
                    button_text="Close",
                )
            )
        return True

