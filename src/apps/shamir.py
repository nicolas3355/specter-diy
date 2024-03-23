import lvgl as lv
from binascii import hexlify
from io import BytesIO

from app import BaseApp, AppError
from embit import bip85
from embit import shamir_crypto
from gui.common import add_button, add_button_pair, align_button_pair
from gui.decorators import on_release
from gui.screens import Menu, NumericScreen, QRAlert, Alert
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

class ShamirScreen(MnemonicScreen):
    QR = 1
    SD = 2
    NEXT = 3
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.next_btn = add_button(
            text="Next Share",
            scr=self,
            callback=on_release(self.next)
        )
        self.next_btn.align(self.table, lv.ALIGN.OUT_BOTTOM_MID, 0, 10)
        self.show_qr_btn, self.save_sd_btn = add_button_pair(
            text1="Show QR code",
            callback1=on_release(self.show_qr),
            text2="Save to SD card",
            callback2=on_release(self.save_sd),
            scr=self,
        )
        self.show_qr_btn.align(self.next_btn, lv.ALIGN.OUT_BOTTOM_MID, 0, 10)
        self.save_sd_btn.align(self.next_btn, lv.ALIGN.OUT_BOTTOM_MID, 0, 10)
        align_button_pair(self.show_qr_btn, self.save_sd_btn)

    def show_qr(self):
        self.set_value(self.QR)

    def save_sd(self):
        self.set_value(self.SD)

    def next(self):
        self.set_value(self.NEXT)

class App(BaseApp):
    """
    WalletManager class manages your wallets.
    It stores public information about the wallets
    in the folder and signs it with keystore's id key
    """

    button = "Secret Sharing (Shamir)"
    name = "Split"

    async def menu(self, show_screen):
        buttons = [
            (None, "Shamir Secret Sharing"),
            (0, "Split"),
            (1, "Combine")
        ]

        # wait for menu selection
        menuitem = await show_screen(
            Menu(
                buttons,
                last=(255, None),
                title="Secret Sharing",
                note="",
            )
        )

        # process the menu button:
        # back button
        if menuitem == 255:
            return False

        # get total number of shares
        total_shares = await show_screen(
            NumericScreen(title="What is the total number of shares to generate?", note="Default: 3")
        )
        if total_shares is None:
            return True # stay in the menu
        if total_shares == "":
            total_shares = 3
        total_shares = int(total_shares)


        # get total number of shares
        min_shares = await show_screen(
            NumericScreen(title="What is the minimum number of shares to reconstruct?", note="Must be less than " + str(total_shares))
        )
        if min_shares is None:
            return True # stay in the menu

        if min_shares == "":
            min_shares = total_shares - 1

        if int(min_shares) >= total_shares:
            return True # stay in the menu

        min_shares = int(min_shares)




        fgp = hexlify(self.keystore.fingerprint).decode()
        # mnemonic menu items
        if menuitem == 0:
            shares = shamir_crypto.Shamir.split(min_shares, total_shares, self.keystore.mnemonic)
            current = 0

            def display(shares, current):
                title = "Total number of shares is %d" % total_shares
                mnemonic = shares[current][1]
                index = shares[current][0]
                note = "Share number " + str(index)

                action = await show_screen(
                    ShamirScreen(mnemonic=mnemonic, title=title, note=note)
                )

                if action == ShamirScreen.QR:
                    await show_screen(
                        QRAlert(title=title, message=mnemonic, note=note)
                    )
                    return current

                elif action == ShamirScreen.SD:
                    fname = "ssss-%s-mnemonic-%d-%d.txt" % (
                        fgp, min_shares, index
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
                    return current

                elif action == ShamirScreen.NEXT:
                    return current + 1

                # in case they press okay let them leave
                return total_shares

            while current < total_shares:
                current = await display(shares, current)

            return True
        # other stuff
        if menuitem == 2:
            shares = shamir_crypto.Shamir.split(2, 3, self.keystore.mnemonic)
            print(shares)
            print(shamir_crypto.Shamir.combine(shares))
        else:
            raise NotImplementedError("Not implemented")
        return True

