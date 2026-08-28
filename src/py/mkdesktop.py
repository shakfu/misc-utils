#!/usr/bin/env python3
"""Create a freedesktop.org .desktop entry for an executable.

Uses only the Python standard library.
"""

from __future__ import annotations

import argparse
import os
import re
import shlex
import shutil
import stat
import struct
import subprocess
import sys
import tempfile
from collections.abc import Sequence
from typing import NoReturn

USER_DIR = os.path.join(
    os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share"),
    "applications",
)
SYSTEM_DIR = "/usr/share/applications"

USER_ICON_DIR = os.path.join(
    os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share"),
    "icons",
    "hicolor",
)
SYSTEM_ICON_DIR = "/usr/share/icons/hicolor"

# Formats the icon theme spec allows. Anything else has to stay an absolute
# path in Icon=, since a theme lookup would never find it.
THEME_ICON_SUFFIXES = (".png", ".svg", ".xpm")

# Main categories from the freedesktop menu spec. Any one of these is enough
# to place an entry in the menus.
MAIN_CATEGORIES = {
    "AudioVideo", "Audio", "Video", "Development", "Education", "Game",
    "Graphics", "Network", "Office", "Science", "Settings", "System",
    "Utility",
}

# Categories that are only valid alongside one of their related categories
# ("Related Category" column of the spec's tables). Audio and Video are main
# categories but still depend on AudioVideo. Keys not listed here stand alone.
REQUIRED_WITH = {
    "Audio": ("AudioVideo",),
    "Video": ("AudioVideo",),
    "Building": ("Development",), "Debugger": ("Development",),
    "IDE": ("Development",), "GUIDesigner": ("Development",),
    "Profiling": ("Development",), "RevisionControl": ("Development",),
    "Translation": ("Development",), "WebDevelopment": ("Network", "Development"),
    "Calendar": ("Office",), "ContactManagement": ("Office",),
    "Database": ("Office", "Development", "AudioVideo"),
    "Dictionary": ("Office", "TextTools"), "Chart": ("Office",),
    "Email": ("Office", "Network"), "Finance": ("Office",),
    "FlowChart": ("Office",), "PDA": ("Office",),
    "ProjectManagement": ("Office", "Development"),
    "Presentation": ("Office",), "Spreadsheet": ("Office",),
    "WordProcessor": ("Office",),
    "2DGraphics": ("Graphics",), "3DGraphics": ("Graphics",),
    "VectorGraphics": ("Graphics", "2DGraphics"),
    "RasterGraphics": ("Graphics", "2DGraphics"),
    "Scanning": ("Graphics",), "OCR": ("Graphics", "Scanning"),
    "Photography": ("Graphics", "Office"),
    "Publishing": ("Graphics", "Office"),
    "Viewer": ("Graphics", "Office"),
    "TextTools": ("Utility",), "Archiving": ("Utility",),
    "Compression": ("Utility", "Archiving"), "Calculator": ("Utility",),
    "Clock": ("Utility",), "TextEditor": ("Utility",),
    "TelephonyTools": ("Utility",), "Accessibility": ("Settings", "Utility"),
    "DesktopSettings": ("Settings",), "HardwareSettings": ("Settings",),
    "Printing": ("Settings", "HardwareSettings"),
    "PackageManager": ("Settings",), "Security": ("Settings", "System"),
    "Dialup": ("Network",), "InstantMessaging": ("Network",),
    "Chat": ("Network",), "IRCClient": ("Network",), "Feed": ("Network",),
    "FileTransfer": ("Network",), "HamRadio": ("Network", "Audio"),
    "News": ("Network",), "P2P": ("Network",), "RemoteAccess": ("Network",),
    "Telephony": ("Network",), "VideoConference": ("Network",),
    "WebBrowser": ("Network",), "Monitor": ("System", "Network"),
    "FileTools": ("Utility", "System"), "FileManager": ("System", "FileTools"),
    "TerminalEmulator": ("System",), "Filesystem": ("System",),
    "Emulator": ("System", "Game"),
    "Midi": ("AudioVideo", "Audio"), "Mixer": ("AudioVideo", "Audio"),
    "Sequencer": ("AudioVideo", "Audio"), "Tuner": ("AudioVideo", "Audio"),
    "TV": ("AudioVideo", "Video"), "DiscBurning": ("AudioVideo",),
    "AudioVideoEditing": ("Audio", "Video", "AudioVideo"),
    "Player": ("Audio", "Video", "AudioVideo"),
    "Recorder": ("Audio", "Video", "AudioVideo"),
    "Music": ("AudioVideo", "Education"),
    "ActionGame": ("Game",), "AdventureGame": ("Game",),
    "ArcadeGame": ("Game",), "BoardGame": ("Game",), "BlocksGame": ("Game",),
    "CardGame": ("Game",), "KidsGame": ("Game",), "LogicGame": ("Game",),
    "RolePlaying": ("Game",), "Shooter": ("Game",), "Simulation": ("Game",),
    "SportsGame": ("Game",), "StrategyGame": ("Game",),
    "Art": ("Education", "Science"), "Construction": ("Education", "Science"),
    "Languages": ("Education", "Science"),
    "ArtificialIntelligence": ("Education", "Science"),
    "Astronomy": ("Education", "Science"), "Biology": ("Education", "Science"),
    "Chemistry": ("Education", "Science"),
    "ComputerScience": ("Education", "Science"),
    "DataVisualization": ("Education", "Science"),
    "Economy": ("Education", "Science"),
    "Electricity": ("Education", "Science"),
    "Geography": ("Education", "Science"), "Geology": ("Education", "Science"),
    "Geoscience": ("Education", "Science"), "History": ("Education", "Science"),
    "Humanities": ("Education", "Science"),
    "ImageProcessing": ("Education", "Science"),
    "Literature": ("Education", "Science"),
    "Maps": ("Education", "Science", "Utility"),
    "Math": ("Education", "Science"),
    "NumericalAnalysis": ("Education", "Science", "Math"),
    "MedicalSoftware": ("Education", "Science"),
    "Physics": ("Education", "Science"), "Robotics": ("Education", "Science"),
    "Spirituality": ("Education", "Science", "Utility"),
    "Sports": ("Education", "Science"),
    "ParallelComputing": ("Education", "Science", "ComputerScience"),
}

# Recognised categories that carry no requirement of their own.
STANDALONE_CATEGORIES = {
    "Amusement", "Documentation", "Electronics", "Engineering", "Adult",
    "Core", "KDE", "GNOME", "XFCE", "GTK", "Qt", "Motif", "Java",
    "ConsoleOnly", "Screensaver", "TrayIcon", "Applet", "Shell",
}

# Exec field codes (spec section "The Exec key"). At most one of the file and
# URL codes may appear in a single Exec line.
FILE_FIELD_CODES = ("%f", "%F", "%u", "%U")
OTHER_FIELD_CODES = ("%i", "%c", "%k")
DEPRECATED_FIELD_CODES = ("%d", "%D", "%n", "%N", "%v", "%m")

# A launcher action: its identifier, its display name and its Exec value.
Action = tuple[str, str, str]


def die(msg: str) -> NoReturn:
    sys.exit(f"mkdesktop: error: {msg}")


def warn(msg: str) -> None:
    print("mkdesktop: warning: %s" % msg, file=sys.stderr)


def escape_value(value: str) -> str:
    """Escape a string for a desktop-entry value (spec section 'Values')."""
    return (
        value.replace("\\", "\\\\")
        .replace("\n", "\\n")
        .replace("\t", "\\t")
        .replace("\r", "\\r")
    )


def escape_exec_arg(arg: str) -> str:
    """Quote a single Exec argument if it needs it."""
    if arg and not re.search(r'[\s"\'\\><~|&;$*?#()`]', arg):
        return arg
    # Inside double quotes the reserved characters must be backslash-escaped,
    # and the whole thing is then escaped again as a normal value.
    inner = re.sub(r'(["`$\\])', r"\\\1", arg)
    return '"%s"' % inner


def normalise_field_codes(arg: str, seen: list[str]) -> str:
    """Keep the field codes in *arg* and double every other percent sign.

    A bare '%' reads as the start of a field code, so a literal one has to be
    written '%%' or the entry fails validation. *seen* collects the file/URL
    codes found so far across the whole Exec line.
    """
    out: list[str] = []
    index = 0
    while index < len(arg):
        if arg[index] != "%":
            out.append(arg[index])
            index += 1
            continue
        code = arg[index:index + 2]
        if code in FILE_FIELD_CODES:
            if seen:
                die(
                    "Exec may contain at most one of %s (found %s and %s)"
                    % (", ".join(FILE_FIELD_CODES), seen[0], code)
                )
            seen.append(code)
        elif code in DEPRECATED_FIELD_CODES:
            warn("field code %s is deprecated and is ignored by launchers" % code)
        elif code not in OTHER_FIELD_CODES and code != "%%":
            out.append("%%")
            index += 1
            continue
        out.append(code)
        index += 2
    return "".join(out)


def build_exec(program: str, args: Sequence[str]) -> str:
    """Assemble an Exec value from a resolved program and its arguments."""
    seen: list[str] = []
    # The program is a real filesystem path, so any percent in it is literal.
    parts = [escape_exec_arg(program.replace("%", "%%"))]
    parts.extend(escape_exec_arg(normalise_field_codes(a, seen)) for a in args)
    return " ".join(parts)


def resolve_executable(spec: str) -> tuple[str, list[str]]:
    """Split a command line and turn its program into an absolute path."""
    try:
        parts = shlex.split(spec)
    except ValueError as exc:
        die("could not parse command %r: %s" % (spec, exc))
    if not parts:
        die("empty command")

    program, args = parts[0], parts[1:]
    if os.sep in program or program.startswith("."):
        path = os.path.abspath(os.path.expanduser(program))
        if not os.path.isfile(path):
            die("no such file: %s" % path)
        if not os.access(path, os.X_OK):
            die("not executable: %s" % path)
    else:
        found = shutil.which(program)
        if not found:
            die("%r not found on PATH (pass a full path instead)" % program)
        path = found
    return path, args


def resolve_icon(icon: str | None) -> str | None:
    """Absolute path for a file icon, or a bare theme icon name as-is."""
    if icon is None:
        return None
    looks_like_path = (
        os.sep in icon
        or icon.startswith("~")
        or icon.lower().endswith((".png", ".svg", ".xpm", ".ico", ".jpg", ".jpeg"))
    )
    if not looks_like_path:
        return icon
    path = os.path.abspath(os.path.expanduser(icon))
    if not os.path.isfile(path):
        die("no such icon file: %s" % path)
    return path


def image_size(path: str | os.PathLike[str]) -> int | None:
    """Square icon size in pixels, read from the file header, or None."""
    suffix = os.path.splitext(path)[1].lower()
    try:
        with open(path, "rb") as handle:
            head = handle.read(4096)
    except OSError as exc:
        die("could not read %s: %s" % (path, exc))

    if suffix == ".png":
        if len(head) < 24 or head[:8] != b"\x89PNG\r\n\x1a\n" or head[12:16] != b"IHDR":
            return None
        width, height = (int(n) for n in struct.unpack(">II", head[16:24]))
    elif suffix == ".xpm":
        # The first quoted string of an XPM holds "width height ncolors cpp".
        match = re.search(rb'"\s*(\d+)\s+(\d+)\s+\d+\s+\d+', head)
        if not match:
            return None
        width, height = int(match.group(1)), int(match.group(2))
    else:
        return None
    return width if width == height else None


def install_icon(
    icon: str, stem: str, system: bool, size: int | None, dry_run: bool
) -> str:
    """Copy *icon* into the hicolor theme; return the bare name for Icon=.

    A themed icon survives the source file being moved and lets the desktop
    pick a size, which an absolute path in Icon= cannot do.
    """
    source = os.path.abspath(os.path.expanduser(icon))
    if not os.path.isfile(source):
        die("no such icon file: %s" % source)
    suffix = os.path.splitext(source)[1].lower()
    if suffix not in THEME_ICON_SUFFIXES:
        die(
            "--install-icon needs one of %s, got %s (drop --install-icon to "
            "reference the file by path instead)"
            % (", ".join(THEME_ICON_SUFFIXES), suffix or "no suffix")
        )

    if suffix == ".svg":
        subdir = "scalable"
    else:
        pixels = size or image_size(source)
        if not pixels:
            die("could not read the size of %s; pass --icon-size" % source)
        subdir = "%dx%d" % (pixels, pixels)

    base = SYSTEM_ICON_DIR if system else USER_ICON_DIR
    directory = os.path.join(base, subdir, "apps")
    target = os.path.join(directory, stem + suffix)

    if dry_run:
        print("would install icon %s" % target, file=sys.stderr)
        return stem

    try:
        os.makedirs(directory, exist_ok=True)
        shutil.copyfile(source, target)
    except OSError as exc:
        die("could not install icon %s: %s" % (target, exc))
    print("installed icon %s" % target)

    cache = shutil.which("gtk-update-icon-cache")
    if cache:
        subprocess.run([cache, "-q", "-t", "-f", base], capture_output=True)
    return stem


def remove_installed_icons(base: str, stem: str) -> list[str]:
    """Delete themed icons this tool installed for *stem*. Returns the paths."""
    removed: list[str] = []
    for root, _dirs, files in os.walk(base):
        if os.path.basename(root) != "apps":
            continue
        for filename in files:
            name, suffix = os.path.splitext(filename)
            if name == stem and suffix.lower() in THEME_ICON_SUFFIXES:
                candidate = os.path.join(root, filename)
                try:
                    os.remove(candidate)
                except OSError as exc:
                    warn("could not remove %s: %s" % (candidate, exc))
                else:
                    removed.append(candidate)
    return removed


def slugify(name: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", name).strip("-.").lower()
    return slug or "application"


def normalise_categories(raw: Sequence[str]) -> str | None:
    """Turn --categories values into a validated, ';'-terminated string."""
    cats: list[str] = []
    for chunk in raw:
        for cat in chunk.replace(",", ";").split(";"):
            cat = cat.strip()
            if cat and cat not in cats:
                cats.append(cat)
    if not cats:
        return None

    present = set(cats)
    if not present & MAIN_CATEGORIES:
        warn(
            "no main category in %s; some menus may hide the entry"
            % ";".join(cats)
        )

    for cat in cats:
        needed = REQUIRED_WITH.get(cat)
        if needed and not present.intersection(needed):
            warn(
                "category %r is only valid alongside one of: %s "
                "(try --categories %s)"
                % (cat, ", ".join(needed), ",".join([needed[0]] + cats))
            )
        elif (
            needed is None
            and cat not in MAIN_CATEGORIES
            and cat not in STANDALONE_CATEGORIES
            and not cat.startswith("X-")
        ):
            warn(
                "category %r is not in the menu spec; prefix vendor-specific "
                "categories with 'X-'" % cat
            )

    return ";".join(cats) + ";"


def join_list(values: Sequence[str]) -> str | None:
    items: list[str] = []
    for chunk in values:
        for item in chunk.replace(",", ";").split(";"):
            item = item.strip()
            if item and item not in items:
                items.append(item)
    return ";".join(items) + ";" if items else None


def parse_actions(raw: Sequence[str]) -> list[Action]:
    """Turn --action 'Name=command' values into (id, name, exec) triples."""
    actions: list[Action] = []
    for spec in raw:
        name, sep, command = spec.partition("=")
        name = name.strip()
        if not sep or not name or not command.strip():
            die("--action expects 'Name=command', got %r" % spec)
        program, extra = resolve_executable(command)
        # Action identifiers are restricted to A-Za-z0-9- by the spec.
        identifier = re.sub(r"[^A-Za-z0-9-]+", "-", name).strip("-") or "action"
        if any(existing == identifier for existing, _, _ in actions):
            die("action %r collides with an earlier one (id %r)" % (name, identifier))
        actions.append((identifier, name, build_exec(program, extra)))
    return actions


def build_entry(
    args: argparse.Namespace,
    exec_line: str,
    icon: str | None,
    actions: Sequence[Action] = (),
) -> str:
    entry: list[tuple[str, str | None]] = [
        ("Type", "Application"),
        ("Version", "1.5"),
        ("Name", args.name),
        ("GenericName", args.generic_name),
        ("Comment", args.comment),
        ("Exec", exec_line),
        ("TryExec", args.try_exec),
        ("Icon", icon),
        ("Path", args.working_dir),
        ("Terminal", "true" if args.terminal else "false"),
        ("Categories", normalise_categories(args.categories)),
        ("Actions", (";".join(a[0] for a in actions) + ";") if actions else None),
        ("Keywords", join_list(args.keywords)),
        ("MimeType", join_list(args.mime_type)),
        ("StartupWMClass", args.wm_class),
        ("StartupNotify", "false" if args.no_startup_notify else "true"),
        ("NoDisplay", "true" if args.no_display else None),
    ]
    lines = ["[Desktop Entry]"]
    for key, value in entry:
        if value is None:
            continue
        lines.append("%s=%s" % (key, escape_value(value)))
    for identifier, name, action_exec in actions:
        lines.append("")
        lines.append("[Desktop Action %s]" % identifier)
        lines.append("Name=%s" % escape_value(name))
        lines.append("Exec=%s" % escape_value(action_exec))
    return "\n".join(lines) + "\n"


def read_field(path: str, key: str) -> str | None:
    """First value of *key* in the [Desktop Entry] group of *path*, or None."""
    try:
        with open(path, encoding="utf-8", errors="replace") as handle:
            in_group = False
            for line in handle:
                line = line.strip()
                if line.startswith("["):
                    in_group = line == "[Desktop Entry]"
                elif in_group and line.startswith(key + "="):
                    return line.split("=", 1)[1]
    except OSError:
        return None
    return None


def entry_files(directory: str) -> list[str]:
    try:
        return sorted(
            name for name in os.listdir(directory) if name.endswith(".desktop")
        )
    except FileNotFoundError:
        return []
    except OSError as exc:
        die("could not read %s: %s" % (directory, exc))


def list_entries(directory: str) -> int:
    names = entry_files(directory)
    if not names:
        print("no entries in %s" % directory)
        return 0
    width = max(len(name) for name in names)
    print("%s:" % directory)
    for filename in names:
        display = read_field(os.path.join(directory, filename), "Name") or "?"
        print("  %-*s  %s" % (width, filename, display))
    return 0


def find_entry(directory: str, wanted: str) -> list[str]:
    """Entries matching *wanted*, by filename first, then by Name= value."""
    basename = wanted if wanted.endswith(".desktop") else wanted + ".desktop"
    direct = os.path.join(directory, basename)
    if os.path.isfile(direct):
        return [direct]
    matches: list[str] = []
    for filename in entry_files(directory):
        path = os.path.join(directory, filename)
        if (read_field(path, "Name") or "").lower() == wanted.lower():
            matches.append(path)
    return matches


def remove_entry(
    directory: str, wanted: str, system: bool, dry_run: bool
) -> int:
    matches = find_entry(directory, wanted)
    if not matches:
        die("no entry matching %r in %s" % (wanted, directory))
    if len(matches) > 1:
        die(
            "%r matches several entries: %s"
            % (wanted, ", ".join(os.path.basename(m) for m in matches))
        )
    path = matches[0]
    stem = os.path.basename(path)[: -len(".desktop")]
    # Only a themed icon named after the entry can have come from --install-icon.
    icon = read_field(path, "Icon") or ""
    themed = icon == stem

    if dry_run:
        print("would remove %s" % path)
        if themed:
            print("would remove themed icons named %r" % stem)
        return 0

    try:
        os.remove(path)
    except OSError as exc:
        die("could not remove %s: %s" % (path, exc))
    print("removed %s" % path)
    if themed:
        base = SYSTEM_ICON_DIR if system else USER_ICON_DIR
        for removed in remove_installed_icons(base, stem):
            print("removed %s" % removed)
    refresh(directory)
    return 0


def validate(path: str, label: str | None = None) -> bool:
    """Run desktop-file-validate if it is installed; True when the entry is ok."""
    validator = shutil.which("desktop-file-validate")
    if not validator:
        return True
    result = subprocess.run([validator, path], capture_output=True, text=True)
    output = (result.stdout + result.stderr).strip()
    if output:
        warn("desktop-file-validate reported:")
        sys.stderr.write(output.replace(path, label or path) + "\n")
    return result.returncode == 0


def validate_content(content: str) -> bool:
    """Validate an entry that has not been written to its destination yet."""
    if not shutil.which("desktop-file-validate"):
        return True
    handle = tempfile.NamedTemporaryFile(
        "w", suffix=".desktop", encoding="utf-8", delete=False
    )
    try:
        handle.write(content)
        handle.close()
        return validate(handle.name, label="<dry run>")
    finally:
        os.unlink(handle.name)


def refresh(directory: str) -> None:
    """Rebuild the MIME cache so MimeType= associations take effect."""
    updater = shutil.which("update-desktop-database")
    if updater:
        subprocess.run([updater, directory], capture_output=True)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="mkdesktop.py",
        description="Create a .desktop launcher for an executable.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""examples:
  mkdesktop.py PlugData /usr/local/bin/plugdata
  mkdesktop.py PlugData /usr/local/bin/plugdata --icon ~/Pictures/plugdata.png \\
      --categories AudioVideo,Audio --comment "Pure Data patching environment"
  mkdesktop.py Htop htop --terminal --categories System
  mkdesktop.py Editor "/opt/app/bin/app --no-sandbox %U" --dry-run
  mkdesktop.py Term kitty --action "New Window=kitty --single-instance"
  mkdesktop.py Foo /opt/foo/foo --icon foo.png --install-icon
  mkdesktop.py --list
  mkdesktop.py --remove PlugData
""",
    )
    parser.add_argument(
        "name", nargs="?", help="display name shown in the menu"
    )
    parser.add_argument(
        "executable",
        nargs="?",
        help="path to the executable, or a PATH command; may include arguments "
        "if quoted",
    )
    parser.add_argument("-i", "--icon", help="icon file path, or a theme icon name")
    parser.add_argument(
        "--install-icon", action="store_true",
        help="copy --icon into the hicolor theme and reference it by name, so "
        "the entry survives the source file moving",
    )
    parser.add_argument(
        "--icon-size", type=int, metavar="N",
        help="pixel size of the icon, when it cannot be read from the file",
    )
    parser.add_argument("-c", "--comment", help="tooltip / description")
    parser.add_argument("-g", "--generic-name", help="generic name, e.g. 'Text Editor'")
    parser.add_argument(
        "--categories",
        action="append",
        default=[],
        metavar="CAT[,CAT...]",
        help="menu categories (repeatable), e.g. Audio,Development",
    )
    parser.add_argument(
        "-k", "--keywords", action="append", default=[], metavar="WORD[,WORD...]",
        help="search keywords (repeatable)",
    )
    parser.add_argument(
        "-m", "--mime-type", action="append", default=[], metavar="TYPE[,TYPE...]",
        help="MIME types this app can open (repeatable)",
    )
    parser.add_argument(
        "-a", "--action", action="append", default=[], metavar="NAME=COMMAND",
        help="extra launcher action, shown on right-click (repeatable)",
    )
    parser.add_argument(
        "-t", "--terminal", action="store_true", help="run inside a terminal window"
    )
    parser.add_argument(
        "--working-dir", metavar="DIR", help="directory to run the program in (Path=)"
    )
    parser.add_argument("--try-exec", metavar="PATH", help="TryExec= value")
    parser.add_argument(
        "--wm-class", metavar="CLASS",
        help="StartupWMClass=, to bind windows to this entry in the dock",
    )
    parser.add_argument(
        "--no-startup-notify", action="store_true", help="set StartupNotify=false"
    )
    parser.add_argument(
        "--no-display", action="store_true", help="hide the entry from menus"
    )
    parser.add_argument(
        "-f", "--filename", metavar="NAME",
        help="basename of the .desktop file (default: derived from name)",
    )
    dest = parser.add_mutually_exclusive_group()
    dest.add_argument(
        "-o", "--output-dir", metavar="DIR",
        help="directory to write into (default: %s)" % USER_DIR,
    )
    dest.add_argument(
        "-s", "--system", action="store_true",
        help="install to %s (needs root)" % SYSTEM_DIR,
    )
    parser.add_argument(
        "--force", action="store_true", help="overwrite an existing file"
    )
    parser.add_argument(
        "-n", "--dry-run", action="store_true",
        help="print the entry to stdout instead of writing it",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "-l", "--list", action="store_true",
        help="list the entries in the target directory and exit",
    )
    mode.add_argument(
        "-r", "--remove", metavar="ENTRY",
        help="remove an entry, by filename or by its display name, and exit",
    )
    return parser.parse_args(argv)


def target_dir(args: argparse.Namespace) -> str:
    output_dir: str | None = args.output_dir
    if output_dir:
        return os.path.abspath(os.path.expanduser(output_dir))
    return SYSTEM_DIR if args.system else USER_DIR


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    directory = target_dir(args)

    writes = not (args.dry_run or args.list)
    if args.system and writes and hasattr(os, "geteuid") and os.geteuid() != 0:
        die("--system writes to %s; re-run with sudo" % SYSTEM_DIR)

    if args.list:
        return list_entries(directory)
    if args.remove:
        return remove_entry(directory, args.remove, args.system, args.dry_run)

    if not args.name or not args.executable:
        die("name and executable are required (or use --list / --remove)")
    if not args.name.strip():
        die("name must not be empty")

    program, extra_args = resolve_executable(args.executable)
    exec_line = build_exec(program, extra_args)
    actions = parse_actions(args.action)

    if args.working_dir:
        args.working_dir = os.path.abspath(os.path.expanduser(args.working_dir))
        if not os.path.isdir(args.working_dir):
            die("no such directory: %s" % args.working_dir)

    filename = args.filename or slugify(args.name)
    if not filename.endswith(".desktop"):
        filename += ".desktop"
    stem = filename[: -len(".desktop")]

    icon: str | None
    if args.install_icon:
        if not args.icon:
            die("--install-icon needs --icon")
        icon = install_icon(
            args.icon, stem, args.system, args.icon_size, args.dry_run
        )
    else:
        if args.icon_size:
            warn("--icon-size only applies with --install-icon")
        icon = resolve_icon(args.icon)

    content = build_entry(args, exec_line, icon, actions)

    if args.dry_run:
        sys.stdout.write(content)
        sys.stdout.flush()
        return 0 if validate_content(content) else 1

    path = os.path.join(directory, filename)
    if os.path.exists(path) and not args.force:
        die("%s already exists (use --force to overwrite)" % path)

    try:
        os.makedirs(directory, exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(content)
        os.chmod(path, os.stat(path).st_mode | stat.S_IXUSR)
    except OSError as exc:
        die("could not write %s: %s" % (path, exc))

    print("wrote %s" % path)
    sys.stdout.flush()  # keep ordering when stderr is unbuffered

    ok = validate(path)
    refresh(directory)
    return 0 if ok else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)
