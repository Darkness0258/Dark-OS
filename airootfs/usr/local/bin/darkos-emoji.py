#!/usr/bin/env python3
"""DarkOS Emoji Picker — searchable grid, click to copy to clipboard.

The emoji set here is a curated ~180 common ones with search keywords, not
the full Unicode emoji list (Unicode 15 alone is 3000+) — that's a real
follow-up if it turns out to matter, not something worth bloating this file
for on a first pass.
"""
import json
import os
import sys

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, GLib, Gtk  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from darkos_shell.app_kit import add_class, run_app  # noqa: E402

APP_ID = "org.darkos.EmojiPicker"
WM_CLASS = "darkos-emoji"

# (emoji, name, keywords)
EMOJI = [
    ("😀", "grinning face", "happy smile"), ("😃", "grinning face big eyes", "happy smile"),
    ("😄", "grinning face smiling eyes", "happy laugh"), ("😁", "beaming face", "happy grin"),
    ("😆", "grinning squinting", "laugh haha"), ("😅", "grinning sweat", "laugh relief nervous"),
    ("🤣", "rolling on floor laughing", "lol rofl"), ("😂", "tears of joy", "lol crying laughing"),
    ("🙂", "slightly smiling face", "smile"), ("😉", "winking face", "wink"),
    ("😊", "smiling face", "blush happy"), ("😍", "heart eyes", "love crush"),
    ("😘", "face blowing kiss", "kiss love"), ("😋", "savoring food", "yum tasty"),
    ("😎", "smiling face sunglasses", "cool"), ("🤩", "star struck", "excited wow"),
    ("🥳", "partying face", "party celebrate"), ("😏", "smirking face", "smug"),
    ("😐", "neutral face", "meh"), ("😑", "expressionless face", "blank"),
    ("😴", "sleeping face", "sleep zzz tired"), ("🥱", "yawning face", "tired bored"),
    ("😪", "sleepy face", "tired"), ("😢", "crying face", "sad tear"),
    ("😭", "loudly crying", "sob sad bawling"), ("😡", "pouting face", "angry mad"),
    ("😠", "angry face", "mad"), ("🤬", "cursing face", "angry swear"),
    ("😱", "screaming in fear", "shocked scared"), ("😨", "fearful face", "scared"),
    ("🤔", "thinking face", "hmm think"), ("🤨", "raised eyebrow", "suspicious skeptic"),
    ("😬", "grimacing face", "awkward"), ("🙄", "rolling eyes", "annoyed"),
    ("😳", "flushed face", "embarrassed"), ("🥺", "pleading face", "puppy eyes beg"),
    ("😷", "face with mask", "sick mask"), ("🤒", "face with thermometer", "sick fever"),
    ("🤕", "face with bandage", "hurt injured"), ("🤢", "nauseated face", "sick gross"),
    ("🥴", "woozy face", "dizzy drunk"), ("🤯", "exploding head", "mind blown shocked"),
    ("🥶", "cold face", "freezing cold"), ("🥵", "hot face", "heat sweating"),
    ("😇", "smiling face halo", "angel innocent"), ("🤗", "hugging face", "hug"),
    ("🤫", "shushing face", "quiet secret"), ("🤭", "hand over mouth", "oops giggle"),
    ("🧐", "face with monocle", "inspect fancy"), ("🤓", "nerd face", "geek glasses"),
    ("👍", "thumbs up", "yes good approve"), ("👎", "thumbs down", "no bad disapprove"),
    ("👌", "ok hand", "okay perfect"), ("✌️", "victory hand", "peace"),
    ("🤞", "crossed fingers", "luck hope"), ("👏", "clapping hands", "applause bravo"),
    ("🙌", "raising hands", "celebrate praise"), ("🙏", "folded hands", "please thanks pray"),
    ("💪", "flexed biceps", "strong muscle gym"), ("👋", "waving hand", "hello bye wave"),
    ("🤝", "handshake", "deal agreement"), ("✋", "raised hand", "stop high five"),
    ("👉", "backhand pointing right", "point"), ("👈", "backhand pointing left", "point"),
    ("☝️", "index pointing up", "point up"), ("🤙", "call me hand", "call shaka"),
    ("💯", "hundred points", "perfect score"), ("🔥", "fire", "lit hot great"),
    ("✨", "sparkles", "shiny magic"), ("🎉", "party popper", "celebrate congrats"),
    ("🎊", "confetti ball", "celebrate party"), ("💥", "collision", "boom explosion"),
    ("💫", "dizzy star", "sparkle"), ("⭐", "star", "favorite"),
    ("❤️", "red heart", "love"), ("🧡", "orange heart", "love"),
    ("💛", "yellow heart", "love friendship"), ("💚", "green heart", "love"),
    ("💙", "blue heart", "love"), ("💜", "purple heart", "love"),
    ("🖤", "black heart", "love dark"), ("🤍", "white heart", "love pure"),
    ("💔", "broken heart", "sad heartbreak"), ("💕", "two hearts", "love"),
    ("💖", "sparkling heart", "love"), ("💗", "growing heart", "love"),
    ("😻", "heart eyes cat", "love cat"), ("😸", "grinning cat", "happy cat"),
    ("🐶", "dog face", "puppy pet"), ("🐱", "cat face", "kitten pet"),
    ("🐭", "mouse face", "mouse"), ("🐹", "hamster", "pet"),
    ("🐰", "rabbit face", "bunny"), ("🦊", "fox", "fox"),
    ("🐻", "bear", "bear"), ("🐼", "panda", "panda"),
    ("🐨", "koala", "koala"), ("🐯", "tiger face", "tiger"),
    ("🦁", "lion", "lion king"), ("🐮", "cow face", "cow"),
    ("🐷", "pig face", "pig"), ("🐸", "frog", "frog"),
    ("🐵", "monkey face", "monkey"), ("🐔", "chicken", "chicken"),
    ("🐧", "penguin", "penguin"), ("🐦", "bird", "bird"),
    ("🦆", "duck", "duck"), ("🦉", "owl", "owl"),
    ("🐺", "wolf", "wolf"), ("🐗", "boar", "boar"),
    ("🐴", "horse face", "horse"), ("🦄", "unicorn", "unicorn magic"),
    ("🐝", "honeybee", "bee insect"), ("🐛", "bug", "insect"),
    ("🦋", "butterfly", "insect"), ("🐢", "turtle", "turtle slow"),
    ("🐍", "snake", "snake"), ("🐙", "octopus", "octopus"),
    ("🐳", "spouting whale", "whale ocean"), ("🐬", "dolphin", "dolphin ocean"),
    ("🦈", "shark", "shark ocean"), ("🐊", "crocodile", "crocodile"),
    ("🌸", "cherry blossom", "flower spring"), ("🌹", "rose", "flower love"),
    ("🌻", "sunflower", "flower"), ("🌲", "evergreen tree", "tree nature"),
    ("🌴", "palm tree", "tree tropical"), ("🌵", "cactus", "desert plant"),
    ("🍀", "four leaf clover", "luck"), ("🌈", "rainbow", "colorful pride"),
    ("☀️", "sun", "sunny weather"), ("🌙", "crescent moon", "night moon"),
    ("☁️", "cloud", "weather"), ("⚡", "high voltage", "lightning bolt energy"),
    ("❄️", "snowflake", "cold winter"), ("💧", "droplet", "water tear"),
    ("🍎", "red apple", "fruit food"), ("🍌", "banana", "fruit food"),
    ("🍕", "pizza", "food"), ("🍔", "hamburger", "food burger"),
    ("🍟", "french fries", "food fries"), ("🌮", "taco", "food mexican"),
    ("🍣", "sushi", "food japanese"), ("🍩", "doughnut", "food sweet dessert"),
    ("🍪", "cookie", "food sweet dessert"), ("🎂", "birthday cake", "cake party"),
    ("🍰", "shortcake", "cake dessert"), ("☕", "hot beverage", "coffee tea"),
    ("🍺", "beer mug", "drink alcohol"), ("🍷", "wine glass", "drink alcohol"),
    ("🍫", "chocolate bar", "food sweet dessert"), ("🍿", "popcorn", "movie snack"),
    ("💻", "laptop", "computer work tech"), ("⌨️", "keyboard", "computer tech"),
    ("🖥️", "desktop computer", "computer tech"), ("📱", "mobile phone", "phone tech"),
    ("💡", "light bulb", "idea"), ("🔋", "battery", "power charge"),
    ("🔌", "electric plug", "power charge"), ("📷", "camera", "photo"),
    ("🎮", "video game controller", "gaming"), ("🎧", "headphone", "music audio"),
    ("🎵", "musical note", "music"), ("🎬", "clapper board", "movie film"),
    ("📚", "books", "reading study"), ("✏️", "pencil", "write edit"),
    ("📝", "memo", "note write"), ("🔒", "locked", "security lock"),
    ("🔑", "key", "unlock password"), ("🛡️", "shield", "security protect"),
    ("⚙️", "gear", "settings config"), ("🚀", "rocket", "launch fast startup"),
    ("✅", "check mark button", "done correct yes"), ("❌", "cross mark", "wrong no error"),
    ("⚠️", "warning", "caution alert"), ("❓", "question mark", "confused question"),
    ("❗", "exclamation mark", "important alert"), ("💤", "zzz", "sleep tired"),
    ("💬", "speech balloon", "chat talk message"), ("👀", "eyes", "look watching"),
    ("🧠", "brain", "smart mind think"), ("🎯", "direct hit", "target goal accurate"),
    ("🏆", "trophy", "win award prize"),
]


class EmojiWindow(Gtk.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title="Emoji Picker")
        self.set_default_size(420, 520)
        add_class(self, "app-window")

        self.recent = self._load_recent()
        self.clipboard = Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD)

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.add(root)

        toolbar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        add_class(toolbar, "toolbar")
        self.search = Gtk.SearchEntry()
        self.search.set_placeholder_text("Search emoji…")
        self.search.set_hexpand(True)
        self.search.connect("search-changed", self._on_search)
        toolbar.pack_start(self.search, True, True, 4)
        root.pack_start(toolbar, False, False, 0)

        self.status_label = Gtk.Label(label="Click an emoji to copy it", xalign=0)
        add_class(self.status_label, "statusbar")

        scroller = Gtk.ScrolledWindow()
        self.flow = Gtk.FlowBox()
        self.flow.set_valign(Gtk.Align.START)
        self.flow.set_max_children_per_line(8)
        self.flow.set_selection_mode(Gtk.SelectionMode.NONE)
        self.flow.set_border_width(8)
        scroller.add(self.flow)
        root.pack_start(scroller, True, True, 0)
        root.pack_start(self.status_label, False, False, 0)

        self._populate()

    def _recent_path(self):
        darkos_dir = os.path.join(GLib.get_user_data_dir(), "darkos")
        os.makedirs(darkos_dir, exist_ok=True)
        return os.path.join(darkos_dir, "emoji-recent.json")

    def _load_recent(self):
        try:
            with open(self._recent_path(), "r", encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, list) else []
        except (OSError, json.JSONDecodeError):
            return []

    def _save_recent(self):
        try:
            with open(self._recent_path(), "w", encoding="utf-8") as f:
                json.dump(self.recent, f)
        except OSError:
            pass

    def _populate(self, query=""):
        for child in list(self.flow.get_children()):
            self.flow.remove(child)
        query = query.strip().lower()

        shown = set()
        if not query and self.recent:
            for ch in self.recent:
                self.flow.add(self._make_button(ch))
                shown.add(ch)

        for ch, name, keywords in EMOJI:
            if ch in shown:
                continue
            if query and query not in name and query not in keywords:
                continue
            self.flow.add(self._make_button(ch))
        self.flow.show_all()

    def _make_button(self, emoji_char):
        btn = Gtk.Button(label=emoji_char)
        btn.set_relief(Gtk.ReliefStyle.NONE)
        add_class(btn, "icon-button")
        name = next((n for e, n, _k in EMOJI if e == emoji_char), "")
        btn.set_tooltip_text(name)
        child = btn.get_child()
        if child:
            child.set_markup(f"<span size='24000'>{GLib.markup_escape_text(emoji_char)}</span>")
        btn.connect("clicked", self._on_pick, emoji_char)
        return btn

    def _on_pick(self, _btn, emoji_char):
        self.clipboard.set_text(emoji_char, -1)
        self.recent = [emoji_char] + [e for e in self.recent if e != emoji_char]
        self.recent = self.recent[:24]
        self._save_recent()
        self.status_label.set_text(f"Copied {emoji_char}")
        if not self.search.get_text().strip():
            self._populate()
        GLib.timeout_add(1200, self._restore_status)

    def _restore_status(self):
        self.status_label.set_text("Click an emoji to copy it")
        return False

    def _on_search(self, entry):
        self._populate(entry.get_text())


def build_window(app):
    return EmojiWindow(app)


if __name__ == "__main__":
    run_app(APP_ID, WM_CLASS, build_window)
