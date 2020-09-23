from .core import KeyStoreError, PinError
from .ram import RAMKeyStore
from .javacard.applets.memorycard import MemoryCardApplet, SecureError
from .javacard.util import get_connection
from platform import CriticalErrorWipeImmediately
import platform
from rng import get_random_bytes
from bitcoin import bip39
from gui.screens import Alert, Progress, Menu, MnemonicScreen
import asyncio
from io import BytesIO


class MemoryCard(RAMKeyStore):
    """
    KeyStore that stores secrets on a smartcard
    using MemoryCard Java applet.
    Secret is secured by the PIN code,
    when PIN is entered the secret is moved to
    RAM of the MCU.
    ColdCard's security model.
    """
    NAME = "Smartcard"
    NOTE = """Saves encryption key and Bitcoin key on a PIN-protected external smartcard (requires devkit).
In this mode device can only operate when the smartcard is inserted!"""
    # constants for secret storage
    MAGIC = b"sdiy\x00" # specter-DIY version 0
    KEYS = {
        b"\x01": "enc",
        b"\x02": "entropy",
    }
    # Button to go to storage menu
    # Menu should be implemented in async storage_menu function
    # Here we only have a single option - to show mnemonic
    storage_button = "Smartcard storage"
    def __init__(self):
        super().__init__()
        # javacard connection
        self.connection = get_connection()
        # applet
        self.applet = MemoryCardApplet(self.connection)
        self._is_key_saved = False

    @property
    def is_pin_set(self):
        return self.applet.is_pin_set

    @property
    def pin_attempts_left(self):
        return self.applet.pin_attempts_left

    @property
    def pin_attempts_max(self):
        return self.applet.pin_attempts_max

    @property
    def is_locked(self):
        return self.applet.is_locked

    def _unlock(self, pin):
        """
        Unlock the keystore, raises PinError if PIN is invalid.
        Raises CriticalErrorWipeImmediately if no attempts left.
        """
        try:
            self.applet.unlock(pin)
        except SecureError as e:
            if str(e) == "0502": # wrong PIN
                raise PinError("Invalid PIN!\n%d of %d attempts left..." % (
                    self.pin_attempts_left, self.pin_attempts_max)
                )
            elif str(e) == "0503": # bricked
                self.wipe(self.path)
                raise CriticalErrorWipeImmediately("No more PIN attempts!\nWipe!")
            else:
                raise e
        self.load_enc_secret()

    def load_enc_secret(self):
        data = self.applet.get_secret()
        # no data yet
        if len(data) == 0:
            # create new key if it doesn't exist
            secret = get_random_bytes(32)
            # format: magic, 01 len enc_secret, 02 len entropy
            d = self.serialize_data({
                "enc": secret
            })
            self.applet.save_secret(d)
            self._is_key_saved = False
        else:
            d = self.parse_data(data)
            secret = d["enc"]
            if "entropy" in d:
                self._is_key_saved = True
        self.enc_secret = secret

    def serialize_data(self, obj):
        """Serialize secrets for storage on the card"""
        r = self.MAGIC
        for k in self.KEYS:
            v = self.KEYS[k]
            if v in obj:
                r += k + bytes([len(obj[v])]) + obj[v]
        return r

    def parse_data(self, data):
        """Parse data stored on the card"""
        s = BytesIO(data)
        assert s.read(len(self.MAGIC)) == self.MAGIC
        o = {}
        while True:
            k = s.read(1)
            if len(k) == 0:
                break
            l = s.read(1)[0]
            v = s.read(l)
            assert len(v) == l
            if k in self.KEYS:
                o[self.KEYS[k]] = v
        return o

    def lock(self):
        """Locks the keystore, requires PIN to unlock"""
        self.applet.lock()
        return self.is_locked

    def _change_pin(self, old_pin, new_pin):
        # lock-unlock then change
        # so if we've got wrong PIN
        # we remain is_locked
        self.lock()
        self._unlock(old_pin)
        self.applet.change_pin(old_pin, new_pin)
        self._unlock(new_pin)

    def _set_pin(self, pin):
        """Sets PIN code for verification later"""
        if self.is_pin_set:
            raise KeyStoreError("PIN is already set")
        self.applet.set_pin(pin)
        # call unlock now
        self._unlock(pin)

    def save_mnemonic(self):
        d = self.serialize_data({
            "enc": self.enc_secret,
            "entropy": bip39.mnemonic_to_bytes(self.mnemonic)
        })
        self.applet.save_secret(d)
        self._is_key_saved = True
        # check it's ok
        self.load_mnemonic()

    @property
    def is_key_saved(self):
        return self._is_key_saved

    def load_mnemonic(self):
        if not self._is_key_saved:
            raise KeyStoreError("Key is not saved")
        data = self.applet.get_secret()
        entropy = self.parse_data(data)["entropy"]
        mnemonic = bip39.mnemonic_from_bytes(entropy)
        self.set_mnemonic(mnemonic, "")

    def delete_mnemonic(self):
        d = self.serialize_data({
            "enc": self.enc_secret
        })
        self.applet.save_secret(d)
        self._is_key_saved = False

    async def wait_for_card(self, scr):
        while not self.connection.isCardInserted():
            await asyncio.sleep_ms(30)
            scr.tick(5)
        if scr.waiting:
            scr.waiting = False

    async def init(self, show_fn):
        """
        Waits for keystore media 
        and loads internal secret and PIN state
        """
        self.show = show_fn
        platform.maybe_mkdir(self.path)
        self.load_secret(self.path)

        if not self.connection.isCardInserted():
            # wait for card
            scr = Progress("Smartcard is not inserted",
                           "Please insert the smartcard...",
                           button_text=None) # no button
            asyncio.create_task(self.wait_for_card(scr))
            await show_fn(scr)
        # connect and select applet
        self.connection.connect(self.connection.T1_protocol)
        try:
            self.applet.select()
        except:
            raise KeyStoreError("Failed to select MemoryCardApplet")
        self.applet.open_secure_channel()
        # the rest can be done with parent
        await super().init(show_fn)

    async def storage_menu(self):
        """Manage storage and display of the recovery phrase"""
        buttons = [
            # id, text
            (None, "Smartcard storage"),
            (0, "Save key to the card"),
            (1, "Load key from the card"),
            (2, "Delete key from the card"),
            (3, "Show recovery phrase"),
        ]

        # we stay in this menu until back is pressed
        while True:
            # wait for menu selection
            menuitem = await self.show(Menu(buttons, last=(255, None)))
            # process the menu button:
            # back button
            if menuitem == 255:
                return
            elif menuitem == 0:
                self.save_mnemonic()
                await self.show(Alert("Success!",
                                     "Your key is stored on the smartcard now.",
                                     button_text="OK"))
            elif menuitem == 1:
                self.load_mnemonic()
                await self.show(Alert("Success!",
                                     "Your key is loaded.",
                                     button_text="OK"))
            elif menuitem == 2:
                self.delete_mnemonic()
                await self.show(Alert("Success!",
                                     "Your key is deleted from the smartcard.",
                                     button_text="OK"))
            elif menuitem == 3:
                await self.show(MnemonicScreen(self.mnemonic))
