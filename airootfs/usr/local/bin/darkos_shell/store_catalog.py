"""The Store's curated catalogue and the starter packs: data and lookups only.

No GTK, no subprocess, nothing runs on import, so every rule here is testable
without a display. What happens to the system (install, remove, data
deletion) lives in store_actions.py; what is on screen lives in darkos-store.py
and pack_picker.py.

Rules the data keeps (ci/test-store-catalog.py enforces them):

* Opt-in. Nothing here installs, enables or starts anything. A pack is a
  suggestion; every app in it starts unticked.
* No invented metadata. An entry carries only what is known without asking the
  system: its name, source and package names. Sizes, permissions and whether it
  starts at login are read live (or shown as "Unknown"), never typed in here.
* Honest sources. pacman entries come from the Arch repositories and go through
  Shield's scan-before-install gate. Flatpak entries come from Flathub and are
  labelled Unscanned: Flatpak verifies the signature and sandboxes the app, but
  Shield does not scan it. AUR stays out of the catalogue (search only).

Names: the Flatpak ids were checked against the Flathub organisation on GitHub.
The pacman names are checked against the real repositories by
ci/test-store-catalogue-live.py, which runs only where pacman exists (CI).
"""
from dataclasses import dataclass

SOURCE_PACMAN = "pacman"
SOURCE_FLATPAK = "flatpak"
SOURCES = (SOURCE_PACMAN, SOURCE_FLATPAK)

# (badge text, one sentence of what it means). One place, so no screen words it differently.
SOURCE_LABELS = {
    SOURCE_PACMAN: ("Arch repositories", "Shield scans it before it installs."),
    SOURCE_FLATPAK: ("Flathub \u00b7 Unscanned",
                     "Flatpak checks the download's signature and sandboxes the app, "
                     "but Shield does not scan it."),
}

FLATHUB_REMOTE = "flathub"
FLATHUB_URL = "https://dl.flathub.org/repo/flathub.flatpakrepo"

CATEGORIES = (
    ("internet", "Internet"),
    ("office", "Office & study"),
    ("graphics", "Graphics"),
    ("media", "Audio & video"),
    ("develop", "Developer"),
    ("games", "Games"),
)


@dataclass(frozen=True)
class Entry:
    id: str               # lowercase slug, used in commands and ids
    name: str
    summary: str          # one plain sentence; no ratings, no "best", no "popular"
    category: str
    source: str
    packages: tuple       # pacman package names, or (Flatpak application id,)
    data_paths: tuple = ()  # folders under $HOME that hold this app's own data (pacman apps only)


@dataclass(frozen=True)
class Pack:
    id: str
    name: str
    tagline: str
    entries: tuple        # Entry ids


def _pacman(id_, name, summary, category, packages, data_paths=()):
    return Entry(id_, name, summary, category, SOURCE_PACMAN, tuple(packages), tuple(data_paths))


def _flatpak(id_, name, summary, category, app_id):
    return Entry(id_, name, summary, category, SOURCE_FLATPAK, (app_id,))


ENTRIES = (
    # Internet
    _pacman("thunderbird", "Thunderbird", "Mail, calendar and chat in one app.", "internet",
            ["thunderbird"], [".thunderbird", ".cache/thunderbird"]),
    _pacman("geary", "Geary", "A simple mail app.", "internet",
            ["geary"], [".local/share/geary", ".cache/geary"]),
    _flatpak("signal", "Signal", "Private messaging.", "internet", "org.signal.Signal"),
    _flatpak("telegram", "Telegram", "Messaging.", "internet", "org.telegram.desktop"),
    _flatpak("discord", "Discord", "Voice, video and text chat.", "internet", "com.discordapp.Discord"),
    # Office & study
    _pacman("libreoffice", "LibreOffice", "Documents, spreadsheets and slides.", "office",
            ["libreoffice-fresh"], [".config/libreoffice"]),
    _pacman("xournalpp", "Xournal++", "Handwritten notes and PDF markup.", "office",
            ["xournalpp"], [".config/xournalpp"]),
    _pacman("calibre", "Calibre", "Manage and read e-books.", "office",
            ["calibre"], [".config/calibre", ".cache/calibre"]),
    _pacman("foliate", "Foliate", "A quiet e-book reader.", "office", ["foliate"]),
    _pacman("simple-scan", "Simple Scan", "Scan documents and photos.", "office", ["simple-scan"]),
    _pacman("gnucash", "GnuCash", "Personal and small-business accounts.", "office",
            ["gnucash"], [".config/gnucash", ".local/share/gnucash"]),
    _flatpak("anki", "Anki", "Flashcards that remember when you need them.", "office", "net.ankiweb.Anki"),
    _flatpak("obsidian", "Obsidian", "Linked notes in plain files.", "office", "md.obsidian.Obsidian"),
    _flatpak("zotero", "Zotero", "Collect and cite research.", "office", "org.zotero.Zotero"),
    # Graphics
    _pacman("gimp", "GIMP", "Edit photos and images.", "graphics", ["gimp"], [".config/GIMP"]),
    _pacman("krita", "Krita", "Digital painting.", "graphics",
            ["krita"], [".local/share/krita", ".config/kritarc"]),
    _pacman("inkscape", "Inkscape", "Vector graphics.", "graphics", ["inkscape"], [".config/inkscape"]),
    _pacman("darktable", "Darktable", "Develop RAW photos.", "graphics",
            ["darktable"], [".config/darktable", ".cache/darktable"]),
    _pacman("blender", "Blender", "3D modelling, animation and rendering.", "graphics",
            ["blender"], [".config/blender"]),
    # Audio & video
    _pacman("kdenlive", "Kdenlive", "Video editing.", "media",
            ["kdenlive"], [".config/kdenliverc", ".local/share/kdenlive"]),
    _pacman("obs-studio", "OBS Studio", "Record and stream your screen.", "media",
            ["obs-studio"], [".config/obs-studio"]),
    _pacman("audacity", "Audacity", "Record and edit audio.", "media",
            ["audacity"], [".config/audacity", ".local/share/audacity"]),
    _pacman("handbrake", "HandBrake", "Convert video between formats.", "media",
            ["handbrake"], [".config/ghb"]),
    _pacman("kooha", "Kooha", "A simple screen recorder.", "media", ["kooha"]),
    # Developer
    _pacman("vscode", "Visual Studio Code", "Code editor (the open-source build).", "develop",
            ["code"], [".config/Code - OSS", ".vscode-oss"]),
    _pacman("nodejs", "Node.js", "JavaScript runtime and npm.", "develop", ["nodejs", "npm"]),
    _pacman("go", "Go", "The Go compiler and tools.", "develop", ["go"]),
    _pacman("rust", "Rust", "The Rust compiler and cargo.", "develop", ["rust"]),
    _pacman("github-cli", "GitHub CLI", "GitHub from the terminal.", "develop",
            ["github-cli"], [".config/gh"]),
    _pacman("cmake-gdb", "CMake and GDB", "Build C and C++ projects and debug them.", "develop",
            ["cmake", "gdb"]),
    # Games
    _pacman("steam", "Steam", "Buy and play games.", "games", ["steam"],
            [".local/share/Steam", ".steam"]),
    _pacman("lutris", "Lutris", "One place for games from every platform.", "games",
            ["lutris"], [".local/share/lutris", ".config/lutris", ".cache/lutris"]),
    _pacman("wine", "Wine", "Run Windows programs.", "games",
            ["wine", "wine-gecko", "wine-mono", "winetricks"], [".wine", ".cache/wine", ".cache/winetricks"]),
    _pacman("waydroid", "Waydroid", "Run Android apps.", "games", ["waydroid"], [".local/share/waydroid"]),
    _pacman("gamemode", "GameMode", "Asks the system to favour a running game.", "games", ["gamemode"]),
    _pacman("mangohud", "MangoHud", "Frame rate and temperature overlay.", "games",
            ["mangohud"], [".config/MangoHud"]),
    _pacman("prismlauncher", "Prism Launcher", "Manage Minecraft installs.", "games",
            ["prismlauncher"], [".local/share/PrismLauncher"]),
    _flatpak("heroic", "Heroic Games Launcher", "Play games from Epic, GOG and Amazon.", "games",
             "com.heroicgameslauncher.hgl"),
)

# Six starter packs. A pack is a list of suggestions, nothing more: the picker shows them all unticked.
PACKS = (
    Pack("everyday", "Everyday", "Mail, documents and a few handy tools.",
         ("geary", "libreoffice", "simple-scan", "foliate", "kooha")),
    Pack("student", "Student", "Notes, flashcards, papers and handwriting.",
         ("libreoffice", "xournalpp", "anki", "obsidian", "zotero", "calibre")),
    Pack("developer", "Developer", "An editor and the usual toolchains.",
         ("vscode", "nodejs", "go", "rust", "github-cli", "cmake-gdb")),
    Pack("creator", "Creator", "Photos, painting, video and audio.",
         ("gimp", "krita", "inkscape", "darktable", "kdenlive", "obs-studio", "audacity", "blender")),
    Pack("gamer", "Gamer", "Game stores, Windows compatibility and overlays.",
         ("steam", "lutris", "wine", "gamemode", "mangohud", "prismlauncher", "heroic", "waydroid")),
    Pack("office", "Office", "Documents, mail, accounts and scanning.",
         ("libreoffice", "thunderbird", "xournalpp", "simple-scan", "gnucash", "calibre")),
)

_BY_ID = {entry.id: entry for entry in ENTRIES}
_PACK_BY_ID = {pack.id: pack for pack in PACKS}


def get(entry_id):
    """The entry with this id, or None."""
    return _BY_ID.get(entry_id)


def pack(pack_id):
    return _PACK_BY_ID.get(pack_id)


def category_label(category):
    return dict(CATEGORIES).get(category, category)


def badge(source):
    """Short source badge text, e.g. "Flathub \u00b7 Unscanned"."""
    return SOURCE_LABELS[source][0]


def source_note(source):
    return SOURCE_LABELS[source][1]


def in_category(category):
    return [entry for entry in ENTRIES if entry.category == category]


def pack_entries(pack_id):
    """The Entry objects of a pack, in the pack's order."""
    found = _PACK_BY_ID.get(pack_id)
    return [_BY_ID[entry_id] for entry_id in found.entries] if found else []


def search(query, entries=None):
    """Entries whose name, summary or category label contains every word of the query.

    An empty query matches everything. Case does not matter. This only filters the curated catalogue; the
    Store's Search tab is the one that asks pacman, the AUR and Flathub.
    """
    words = (query or "").lower().split()
    pool = ENTRIES if entries is None else entries
    if not words:
        return list(pool)
    hits = []
    for entry in pool:
        text = " ".join((entry.name, entry.summary, category_label(entry.category), entry.id)).lower()
        if all(word in text for word in words):
            hits.append(entry)
    return hits


def recommend(profile=None):
    """Packs worth offering, most relevant first.

    This is the one seam for personalising the picker later (`profile` is what Welcome has learned about the
    person). Today it is static on purpose: every pack, in a fixed order, and the picker pre-selects nothing.
    Callers must not assume more than that.
    """
    return list(PACKS)


def packages_of(entries):
    """pacman package names and Flatpak ids needed for these entries, without repeats, in order.

    Returns (pacman_packages, flatpak_ids).
    """
    pacman, flatpak = [], []
    for entry in entries:
        target = pacman if entry.source == SOURCE_PACMAN else flatpak
        for name in entry.packages:
            if name not in target:
                target.append(name)
    return pacman, flatpak
