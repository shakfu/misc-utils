#!/usr/bin/env python3
"""Tests for mkdesktop.py"""

import os
import shutil
import struct
import zlib

import pytest

import mkdesktop
from mkdesktop import (
    build_entry,
    build_exec,
    escape_exec_arg,
    escape_value,
    find_entry,
    image_size,
    install_icon,
    join_list,
    main,
    normalise_categories,
    normalise_field_codes,
    parse_actions,
    read_field,
    resolve_executable,
    resolve_icon,
    slugify,
)

HELPER_TOOLS = (
    "desktop-file-validate",
    "update-desktop-database",
    "gtk-update-icon-cache",
)


@pytest.fixture(autouse=True)
def no_helper_tools(monkeypatch):
    """Pretend the optional desktop helpers are not installed.

    They are absent on some machines and present on others, so the tests would
    otherwise pass or fail depending on the host.
    """
    real = shutil.which

    def which(name, *rest, **kwargs):
        return None if name in HELPER_TOOLS else real(name, *rest, **kwargs)

    monkeypatch.setattr(shutil, "which", which)


@pytest.fixture
def install_root(tmp_path, monkeypatch):
    """Redirect the user applications and icon directories into tmp_path."""
    apps = tmp_path / "applications"
    icons = tmp_path / "icons" / "hicolor"
    monkeypatch.setattr(mkdesktop, "USER_DIR", str(apps))
    monkeypatch.setattr(mkdesktop, "USER_ICON_DIR", str(icons))
    return apps, icons


def write_png(path, width, height):
    def chunk(tag, data):
        body = tag + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body))

    rows = b"".join(b"\x00" + b"\xff\x00\x00" * width for _ in range(height))
    path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(rows))
        + chunk(b"IEND", b"")
    )
    return path


class TestEscaping:
    def test_value_escapes_backslash_and_controls(self):
        assert escape_value("a\\b\nc\td\re") == "a\\\\b\\nc\\td\\re"

    def test_plain_argument_is_left_alone(self):
        assert escape_exec_arg("/usr/bin/app") == "/usr/bin/app"

    @pytest.mark.parametrize("arg", ["a b", "a>b", "a&b", "a$b", "a'b"])
    def test_reserved_characters_force_quoting(self, arg):
        assert escape_exec_arg(arg).startswith('"')

    def test_quotes_are_backslash_escaped_inside_quotes(self):
        assert escape_exec_arg('say "hi"') == '"say \\"hi\\""'

    def test_double_escaping_survives_the_value_pass(self):
        # Exec quoting first, then value escaping: a literal quote reaches the
        # file as \\" so that unescaping the value yields \" for the parser.
        assert escape_value(escape_exec_arg('a"b')) == '"a\\\\"b"'


class TestFieldCodes:
    def test_literal_percent_is_doubled(self):
        assert normalise_field_codes("--width=50%", []) == "--width=50%%"

    def test_trailing_percent_is_doubled(self):
        assert normalise_field_codes("100%", []) == "100%%"

    def test_already_escaped_percent_is_left_alone(self):
        assert normalise_field_codes("50%%", []) == "50%%"

    @pytest.mark.parametrize("code", ["%f", "%F", "%u", "%U", "%i", "%c", "%k"])
    def test_valid_codes_pass_through(self, code):
        assert normalise_field_codes(code, []) == code

    def test_embedded_code_is_recognised(self):
        assert normalise_field_codes("--file=%f", []) == "--file=%f"

    def test_unknown_code_is_treated_as_a_literal_percent(self):
        assert normalise_field_codes("%z", []) == "%%z"

    def test_deprecated_code_warns_but_is_kept(self, capsys):
        assert normalise_field_codes("%d", []) == "%d"
        assert "deprecated" in capsys.readouterr().err

    def test_second_file_code_is_rejected(self):
        seen = []
        normalise_field_codes("%F", seen)
        with pytest.raises(SystemExit) as excinfo:
            normalise_field_codes("%U", seen)
        assert "at most one" in str(excinfo.value)

    def test_build_exec_shares_state_across_arguments(self):
        with pytest.raises(SystemExit):
            build_exec("/bin/ls", ["%F", "%U"])

    def test_percent_in_the_program_path_is_never_a_field_code(self):
        # '%' is not one of the Exec reserved characters, so it needs
        # doubling but no quoting.
        assert build_exec("/opt/50%/app", []) == "/opt/50%%/app"


class TestResolveExecutable:
    def test_path_lookup(self):
        program, args = resolve_executable("sh")
        assert os.path.isabs(program) and args == []

    def test_arguments_are_split(self):
        program, args = resolve_executable("sh -c 'echo hi'")
        assert args == ["-c", "echo hi"]

    def test_absolute_path_is_kept(self, tmp_path):
        app = tmp_path / "app"
        app.write_text("#!/bin/sh\n")
        app.chmod(0o755)
        assert resolve_executable(str(app))[0] == str(app)

    def test_missing_file_is_an_error(self, tmp_path):
        with pytest.raises(SystemExit, match="no such file"):
            resolve_executable(str(tmp_path / "absent"))

    def test_non_executable_file_is_an_error(self, tmp_path):
        app = tmp_path / "app"
        app.write_text("")
        app.chmod(0o644)
        with pytest.raises(SystemExit, match="not executable"):
            resolve_executable(str(app))

    def test_unknown_command_is_an_error(self):
        with pytest.raises(SystemExit, match="not found on PATH"):
            resolve_executable("definitely-not-a-real-command-xyz")

    def test_unbalanced_quotes_are_an_error(self):
        with pytest.raises(SystemExit, match="could not parse"):
            resolve_executable("sh 'unclosed")


class TestIconAndCategories:
    def test_theme_name_is_kept_verbatim(self):
        assert resolve_icon("firefox") == "firefox"

    def test_file_path_is_made_absolute(self, tmp_path):
        icon = tmp_path / "a.png"
        icon.write_bytes(b"")
        assert resolve_icon(str(icon)) == str(icon)

    def test_missing_icon_file_is_an_error(self, tmp_path):
        with pytest.raises(SystemExit, match="no such icon file"):
            resolve_icon(str(tmp_path / "gone.png"))

    def test_categories_are_split_deduped_and_terminated(self):
        assert normalise_categories(["Audio,AudioVideo", "Audio;Player"]) == (
            "Audio;AudioVideo;Player;"
        )

    def test_missing_main_category_warns(self, capsys):
        normalise_categories(["TextEditor"])
        assert "no main category" in capsys.readouterr().err

    def test_related_category_requirement_warns(self, capsys):
        normalise_categories(["Utility", "IDE"])
        assert "only valid alongside" in capsys.readouterr().err

    def test_unknown_category_warns(self, capsys):
        normalise_categories(["Utility", "Nonsense"])
        assert "not in the menu spec" in capsys.readouterr().err

    def test_vendor_prefix_is_accepted(self, capsys):
        normalise_categories(["Utility", "X-Mine"])
        assert capsys.readouterr().err == ""

    def test_empty_input_yields_nothing(self):
        assert normalise_categories([]) is None

    def test_join_list_dedupes_and_terminates(self):
        assert join_list(["a,b", "b;c"]) == "a;b;c;"
        assert join_list([]) is None

    @pytest.mark.parametrize(
        "name, expected",
        [("Foo App", "foo-app"), ("...", "application"), ("A/B", "a-b")],
    )
    def test_slugify(self, name, expected):
        assert slugify(name) == expected


class TestActions:
    def test_action_becomes_a_group_and_an_id(self):
        actions = parse_actions(["New Window=sh -c true"])
        assert actions[0][0] == "New-Window"
        assert actions[0][1] == "New Window"

    def test_missing_separator_is_an_error(self):
        with pytest.raises(SystemExit, match="expects"):
            parse_actions(["New Window"])

    def test_empty_command_is_an_error(self):
        with pytest.raises(SystemExit, match="expects"):
            parse_actions(["New Window=  "])

    def test_colliding_identifiers_are_rejected(self):
        with pytest.raises(SystemExit, match="collides"):
            parse_actions(["New Window=sh", "New/Window=sh"])


class TestImageSize:
    def test_square_png(self, tmp_path):
        assert image_size(write_png(tmp_path / "i.png", 48, 48)) == 48

    def test_non_square_png_is_rejected(self, tmp_path):
        assert image_size(write_png(tmp_path / "i.png", 48, 32)) is None

    def test_corrupt_png(self, tmp_path):
        path = tmp_path / "i.png"
        path.write_bytes(b"not a png at all, really not")
        assert image_size(path) is None

    def test_xpm_header(self, tmp_path):
        path = tmp_path / "i.xpm"
        path.write_text('/* XPM */\nstatic char *x[] = {\n"32 32 2 1",\n};\n')
        assert image_size(path) == 32

    def test_unknown_suffix(self, tmp_path):
        path = tmp_path / "i.svg"
        path.write_text("<svg/>")
        assert image_size(path) is None


class TestInstallIcon:
    def test_png_lands_in_its_size_directory(self, tmp_path, install_root):
        _apps, icons = install_root
        source = write_png(tmp_path / "src.png", 64, 64)
        assert install_icon(str(source), "foo", False, None, False) == "foo"
        assert (icons / "64x64" / "apps" / "foo.png").is_file()

    def test_svg_lands_in_scalable(self, tmp_path, install_root):
        _apps, icons = install_root
        source = tmp_path / "src.svg"
        source.write_text("<svg/>")
        install_icon(str(source), "foo", False, None, False)
        assert (icons / "scalable" / "apps" / "foo.svg").is_file()

    def test_explicit_size_overrides_the_header(self, tmp_path, install_root):
        _apps, icons = install_root
        source = write_png(tmp_path / "src.png", 64, 64)
        install_icon(str(source), "foo", False, 128, False)
        assert (icons / "128x128" / "apps" / "foo.png").is_file()

    def test_unreadable_size_asks_for_one(self, tmp_path, install_root):
        source = tmp_path / "src.png"
        source.write_bytes(b"junk")
        with pytest.raises(SystemExit, match="--icon-size"):
            install_icon(str(source), "foo", False, None, False)

    def test_untheme_able_format_is_rejected(self, tmp_path, install_root):
        source = tmp_path / "src.jpg"
        source.write_bytes(b"")
        with pytest.raises(SystemExit, match="--install-icon needs"):
            install_icon(str(source), "foo", False, None, False)

    def test_dry_run_copies_nothing(self, tmp_path, install_root):
        _apps, icons = install_root
        source = write_png(tmp_path / "src.png", 64, 64)
        assert install_icon(str(source), "foo", False, None, True) == "foo"
        assert not icons.exists()


class TestBuildEntry:
    def make(self, tmp_path, **overrides):
        args = mkdesktop.parse_args(["Foo", "sh"])
        for key, value in overrides.items():
            setattr(args, key, value)
        return args

    def test_action_groups_follow_the_main_group(self, tmp_path):
        args = self.make(tmp_path)
        actions = [("New-Window", "New Window", "/bin/sh -c true")]
        content = build_entry(args, "/bin/sh", None, actions)
        assert "Actions=New-Window;" in content
        assert content.index("[Desktop Entry]") < content.index("[Desktop Action")
        assert "[Desktop Action New-Window]\nName=New Window\nExec=/bin/sh" in content

    def test_no_actions_means_no_actions_key(self, tmp_path):
        content = build_entry(self.make(tmp_path), "/bin/sh", None)
        assert "Actions=" not in content
        assert "[Desktop Action" not in content

    def test_unset_fields_are_omitted(self, tmp_path):
        content = build_entry(self.make(tmp_path), "/bin/sh", None)
        for key in ("Icon", "Comment", "Path", "NoDisplay", "MimeType"):
            assert "\n%s=" % key not in content

    def test_terminal_and_no_display_flags(self, tmp_path):
        args = self.make(tmp_path, terminal=True, no_display=True)
        content = build_entry(args, "/bin/sh", None)
        assert "Terminal=true" in content and "NoDisplay=true" in content


class TestEntryFiles:
    def test_read_field_ignores_other_groups(self, tmp_path):
        path = tmp_path / "a.desktop"
        path.write_text(
            "[Desktop Entry]\nName=Real\n\n[Desktop Action x]\nName=Action\n"
        )
        assert read_field(str(path), "Name") == "Real"

    def test_read_field_missing_key(self, tmp_path):
        path = tmp_path / "a.desktop"
        path.write_text("[Desktop Entry]\nName=Real\n")
        assert read_field(str(path), "Icon") is None

    def test_read_field_missing_file(self, tmp_path):
        assert read_field(str(tmp_path / "gone.desktop"), "Name") is None

    def test_find_entry_by_filename_with_or_without_suffix(self, tmp_path):
        path = tmp_path / "foo.desktop"
        path.write_text("[Desktop Entry]\nName=Foo\n")
        assert find_entry(str(tmp_path), "foo") == [str(path)]
        assert find_entry(str(tmp_path), "foo.desktop") == [str(path)]

    def test_find_entry_by_display_name_is_case_insensitive(self, tmp_path):
        path = tmp_path / "foo.desktop"
        path.write_text("[Desktop Entry]\nName=Foo App\n")
        assert find_entry(str(tmp_path), "foo app") == [str(path)]

    def test_find_entry_reports_every_match(self, tmp_path):
        for stem in ("a", "b"):
            (tmp_path / ("%s.desktop" % stem)).write_text(
                "[Desktop Entry]\nName=Same\n"
            )
        assert len(find_entry(str(tmp_path), "Same")) == 2

    def test_find_entry_in_a_missing_directory(self, tmp_path):
        assert find_entry(str(tmp_path / "absent"), "foo") == []


class TestMain:
    def test_dry_run_prints_and_writes_nothing(self, capsys, install_root):
        apps, _icons = install_root
        assert main(["Foo", "sh", "-n"]) == 0
        assert "[Desktop Entry]" in capsys.readouterr().out
        assert not apps.exists()

    def test_write_creates_an_executable_entry(self, capsys, install_root):
        apps, _icons = install_root
        assert main(["Foo App", "sh"]) == 0
        path = apps / "foo-app.desktop"
        assert path.is_file()
        assert os.access(path, os.X_OK)
        assert "Name=Foo App" in path.read_text()

    def test_existing_file_needs_force(self, install_root):
        main(["Foo", "sh"])
        with pytest.raises(SystemExit, match="already exists"):
            main(["Foo", "sh"])
        assert main(["Foo", "sh", "--force"]) == 0

    def test_filename_override(self, install_root):
        apps, _icons = install_root
        main(["Foo", "sh", "--filename", "org.example.Foo"])
        assert (apps / "org.example.Foo.desktop").is_file()

    def test_output_dir_overrides_the_default(self, tmp_path, install_root):
        main(["Foo", "sh", "-o", str(tmp_path / "out")])
        assert (tmp_path / "out" / "foo.desktop").is_file()

    def test_empty_name_is_rejected(self, install_root):
        with pytest.raises(SystemExit, match="must not be empty"):
            main(["   ", "sh"])

    def test_missing_executable_argument_is_rejected(self, install_root):
        with pytest.raises(SystemExit, match="an executable is required"):
            main(["Foo"])

    def test_missing_working_dir_is_rejected(self, tmp_path, install_root):
        with pytest.raises(SystemExit, match="no such directory"):
            main(["Foo", "sh", "--working-dir", str(tmp_path / "absent")])

    def test_install_icon_without_icon_is_rejected(self, install_root):
        with pytest.raises(SystemExit, match="--install-icon needs --icon"):
            main(["Foo", "sh", "--install-icon"])

    def test_icon_size_without_install_icon_warns(self, capsys, install_root):
        main(["Foo", "sh", "-n", "--icon-size", "48"])
        assert "--icon-size only applies" in capsys.readouterr().err

    def test_install_icon_end_to_end(self, tmp_path, install_root):
        apps, icons = install_root
        source = write_png(tmp_path / "src.png", 32, 32)
        assert main(["Foo", "sh", "--icon", str(source), "--install-icon"]) == 0
        assert (icons / "32x32" / "apps" / "foo.png").is_file()
        assert "Icon=foo\n" in (apps / "foo.desktop").read_text()

    def test_system_without_root_is_refused(self, monkeypatch, install_root):
        monkeypatch.setattr(os, "geteuid", lambda: 1000)
        with pytest.raises(SystemExit, match="re-run with sudo"):
            main(["Foo", "sh", "--system"])

    def test_system_dry_run_needs_no_root(self, monkeypatch, install_root):
        monkeypatch.setattr(os, "geteuid", lambda: 1000)
        assert main(["Foo", "sh", "--system", "-n"]) == 0

    def test_list_reports_entries(self, capsys, install_root):
        main(["Foo App", "sh"])
        capsys.readouterr()
        assert main(["--list"]) == 0
        out = capsys.readouterr().out
        assert "foo-app.desktop" in out and "Foo App" in out

    def test_list_on_an_empty_directory(self, capsys, install_root):
        assert main(["--list"]) == 0
        assert "no entries" in capsys.readouterr().out

    def test_remove_by_display_name(self, install_root):
        apps, _icons = install_root
        main(["Foo App", "sh"])
        assert main(["--remove", "Foo App"]) == 0
        assert not (apps / "foo-app.desktop").exists()

    def test_remove_takes_the_installed_icon_with_it(self, tmp_path, install_root):
        _apps, icons = install_root
        source = write_png(tmp_path / "src.png", 32, 32)
        main(["Foo", "sh", "--icon", str(source), "--install-icon"])
        main(["--remove", "foo"])
        assert not (icons / "32x32" / "apps" / "foo.png").exists()

    def test_remove_leaves_a_theme_icon_alone(self, install_root):
        apps, icons = install_root
        target = icons / "32x32" / "apps"
        target.mkdir(parents=True)
        write_png(target / "firefox.png", 32, 32)
        main(["Foo", "sh", "--icon", "firefox"])
        main(["--remove", "foo"])
        assert (target / "firefox.png").is_file()

    def test_remove_is_ambiguous_when_names_collide(self, install_root):
        apps, _icons = install_root
        main(["Same", "sh", "--filename", "a"])
        main(["Same", "sh", "--filename", "b"])
        with pytest.raises(SystemExit, match="matches several entries"):
            main(["--remove", "Same"])

    def test_remove_dry_run_keeps_the_file(self, capsys, install_root):
        apps, _icons = install_root
        main(["Foo", "sh"])
        assert main(["--remove", "foo", "-n"]) == 0
        assert "would remove" in capsys.readouterr().out
        assert (apps / "foo.desktop").is_file()

    def test_actions_reach_the_written_entry(self, install_root):
        apps, _icons = install_root
        main(["Foo", "sh", "--action", "New Window=sh -c true"])
        content = (apps / "foo.desktop").read_text()
        assert "Actions=New-Window;" in content
        assert "[Desktop Action New-Window]" in content


class TestValidation:
    def test_failing_validator_sets_the_exit_status(self, monkeypatch, install_root):
        real = shutil.which

        def which(name, *rest, **kwargs):
            if name == "desktop-file-validate":
                return "/usr/bin/desktop-file-validate"
            return None if name in HELPER_TOOLS else real(name, *rest, **kwargs)

        monkeypatch.setattr(shutil, "which", which)

        class Result:
            returncode = 1
            stdout = "boom\n"
            stderr = ""

        monkeypatch.setattr(mkdesktop.subprocess, "run", lambda *a, **k: Result())
        assert main(["Foo", "sh"]) == 1

    def test_dry_run_validates_too(self, monkeypatch, capsys, install_root):
        real = shutil.which
        monkeypatch.setattr(
            shutil,
            "which",
            lambda name, *a, **k: (
                "/usr/bin/desktop-file-validate"
                if name == "desktop-file-validate"
                else (None if name in HELPER_TOOLS else real(name, *a, **k))
            ),
        )

        class Result:
            returncode = 1
            stdout = "boom\n"
            stderr = ""

        monkeypatch.setattr(mkdesktop.subprocess, "run", lambda *a, **k: Result())
        assert main(["Foo", "sh", "-n"]) == 1
        assert "boom" in capsys.readouterr().err


class TestEdit:
    def entry(self, apps, name="Foo"):
        return (apps / ("%s.desktop" % name.lower())).read_text()

    def test_only_the_options_given_are_touched(self, install_root):
        apps, _icons = install_root
        main(["Foo", "sh", "--comment", "first", "--categories", "Utility"])
        assert main(["Foo", "--edit", "--comment", "second"]) == 0
        content = self.entry(apps)
        assert "Comment=second" in content
        assert "Categories=Utility;" in content

    def test_a_default_is_not_a_change(self, install_root):
        """--terminal defaults to false; not passing it must leave the key be."""
        apps, _icons = install_root
        main(["Foo", "sh", "--terminal"])
        main(["Foo", "--edit", "--comment", "x"])
        assert "Terminal=true" in self.entry(apps)

    def test_a_flag_that_is_given_does_change(self, install_root):
        apps, _icons = install_root
        main(["Foo", "sh", "--terminal"])
        main(["Foo", "--edit", "--no-display"])
        assert "NoDisplay=true" in self.entry(apps)

    def test_new_key_joins_the_end_of_the_group(self, install_root):
        apps, _icons = install_root
        main(["Foo", "sh"])
        main(["Foo", "--edit", "--wm-class", "GLFW-Application"])
        content = self.entry(apps)
        assert "StartupWMClass=GLFW-Application" in content
        assert content.index("StartupWMClass") > content.index("Exec=")

    def test_existing_key_keeps_its_position(self, install_root):
        apps, _icons = install_root
        main(["Foo", "sh", "--comment", "first"])
        before = self.entry(apps).splitlines().index("Comment=first")
        main(["Foo", "--edit", "--comment", "second"])
        assert self.entry(apps).splitlines().index("Comment=second") == before

    def test_unset_removes_a_key(self, tmp_path, install_root):
        apps, _icons = install_root
        main(["Foo", "sh", "--working-dir", str(tmp_path)])
        assert main(["Foo", "--edit", "--unset", "Path"]) == 0
        assert "Path=" not in self.entry(apps)

    def test_unset_of_an_absent_key_warns(self, capsys, install_root):
        main(["Foo", "sh"])
        capsys.readouterr()
        assert main(["Foo", "--edit", "--unset", "Icon"]) == 0
        assert "has no Icon to unset" in capsys.readouterr().err

    def test_comments_and_unknown_keys_survive(self, install_root):
        apps, _icons = install_root
        path = apps / "foo.desktop"
        main(["Foo", "sh"])
        path.write_text(
            path.read_text().replace(
                "Terminal=false", "# note\nX-Vendor-Key=yes\nTerminal=false"
            )
        )
        main(["Foo", "--edit", "--comment", "x"])
        content = path.read_text()
        assert "# note" in content and "X-Vendor-Key=yes" in content

    def test_executable_updates_exec(self, install_root):
        apps, _icons = install_root
        main(["Foo", "sh"])
        main(["Foo", "--edit", "echo"])
        assert "Exec=" in self.entry(apps)
        assert "/sh\n" not in self.entry(apps)

    def test_actions_and_their_groups_stay_in_step(self, install_root):
        apps, _icons = install_root
        main(["Foo", "sh", "--action", "One=sh -c true"])
        main(["Foo", "--edit", "--action", "Two=sh -c false"])
        content = self.entry(apps)
        assert "Actions=Two;" in content
        assert "[Desktop Action Two]" in content
        assert "[Desktop Action One]" not in content
        assert "\n\n\n" not in content

    def test_actions_are_left_alone_when_not_given(self, install_root):
        apps, _icons = install_root
        main(["Foo", "sh", "--action", "One=sh -c true"])
        main(["Foo", "--edit", "--comment", "x"])
        assert "[Desktop Action One]" in self.entry(apps)

    def test_edit_finds_the_entry_by_display_name(self, install_root):
        apps, _icons = install_root
        main(["Foo App", "sh"])
        assert main(["Foo App", "--edit", "--comment", "x"]) == 0
        assert "Comment=x" in (apps / "foo-app.desktop").read_text()

    def test_edit_of_a_missing_entry_is_an_error(self, install_root):
        with pytest.raises(SystemExit, match="no entry matching"):
            main(["Nope", "--edit", "--comment", "x"])

    def test_edit_needs_something_to_change(self, install_root):
        main(["Foo", "sh"])
        with pytest.raises(SystemExit, match="at least one option"):
            main(["Foo", "--edit"])

    def test_ambiguous_name_is_refused(self, install_root):
        main(["Same", "sh", "--filename", "a"])
        main(["Same", "sh", "--filename", "b"])
        with pytest.raises(SystemExit, match="matches several entries"):
            main(["Same", "--edit", "--comment", "x"])

    def test_dry_run_prints_without_writing(self, capsys, install_root):
        apps, _icons = install_root
        main(["Foo", "sh"])
        capsys.readouterr()
        assert main(["Foo", "--edit", "--comment", "x", "-n"]) == 0
        assert "Comment=x" in capsys.readouterr().out
        assert "Comment=x" not in (apps / "foo.desktop").read_text()

    def test_install_icon_reuses_the_existing_filename(self, tmp_path, install_root):
        apps, icons = install_root
        main(["Foo App", "sh"])
        source = write_png(tmp_path / "src.png", 32, 32)
        main(["Foo App", "--edit", "--icon", str(source), "--install-icon"])
        assert (icons / "32x32" / "apps" / "foo-app.png").is_file()
        assert "Icon=foo-app" in (apps / "foo-app.desktop").read_text()

    def test_unset_without_edit_warns(self, capsys, install_root):
        main(["Foo", "sh", "--unset", "Path"])
        assert "--unset only applies with --edit" in capsys.readouterr().err

    def test_missing_desktop_entry_group_is_an_error(self, install_root):
        apps, _icons = install_root
        apps.mkdir(parents=True, exist_ok=True)
        (apps / "broken.desktop").write_text("[Desktop Action x]\nName=x\n")
        with pytest.raises(SystemExit, match="no \\[Desktop Entry\\] group"):
            main(["broken", "--edit", "--comment", "x"])
