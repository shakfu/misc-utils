"""Tests for gha_update.py"""

import tempfile
from pathlib import Path

import pytest

from gha_update import (
    Updater,
    VersionLookupError,
    VersionSource,
    discover,
    find_project_roots,
    is_prerelease,
    is_project_root,
    is_sha,
    main,
    parse_uses_line,
    parse_version,
    render_uses_line,
    target_ref,
    targets_from_args,
    update_comment,
    version_sort_key,
)

SHA_OLD = "a" * 40
SHA_NEW = "b" * 40


@pytest.fixture
def temp_dir():
    """Create a temporary directory for fixture repositories."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


def make_source(tags=None, shas=None, pypi=None, fail=()):
    """Build a VersionSource backed by canned API responses."""
    tags = tags or {}
    shas = shas or {}
    pypi = pypi or {}

    def fetch(url, token):
        for repo in fail:
            if f"/repos/{repo}/" in url:
                raise VersionLookupError(f"{repo}: HTTP 404")
        if "/releases/latest" in url:
            repo = url.split("/repos/", 1)[1].rsplit("/releases", 1)[0]
            if repo not in tags:
                raise VersionLookupError(f"{repo}: HTTP 404")
            return {"tag_name": tags[repo]}
        if "/git/ref/tags/" in url:
            rest = url.split("/repos/", 1)[1]
            repo, _, tag = rest.partition("/git/ref/tags/")
            if (repo, tag) not in shas:
                raise VersionLookupError(f"{repo}: HTTP 404")
            return {"object": {"type": "commit", "sha": shas[(repo, tag)]}}
        if "/tags?" in url:
            repo = url.split("/repos/", 1)[1].rsplit("/tags", 1)[0]
            return [{"name": name} for name in tags.get(repo + ":all", [])]
        if url.startswith("https://pypi.org"):
            package = url.rsplit("/pypi/", 1)[1].rsplit("/json", 1)[0]
            if package not in pypi:
                raise VersionLookupError(f"{package}: HTTP 404")
            return {"info": {"version": pypi[package]}}
        raise AssertionError(f"unexpected url: {url}")

    return VersionSource(fetch=fetch)


class TestParseVersion:
    @pytest.mark.parametrize(
        "text,expected",
        [
            ("v4", ((4,), "")),
            ("v4.1.7", ((4, 1, 7), "")),
            ("4.1.7", ((4, 1, 7), "")),
            ("v3.0.0rc1", ((3, 0, 0), "rc1")),
            ("v2.1.0-beta.1", ((2, 1, 0), "beta.1")),
        ],
    )
    def test_parses_versions(self, text, expected):
        assert parse_version(text) == expected

    @pytest.mark.parametrize("text", ["main", "master", "", "v", SHA_OLD, "release/v1"])
    def test_rejects_non_versions(self, text):
        assert parse_version(text) is None

    def test_prerelease_detection(self):
        assert is_prerelease("v3.0.0rc1") is True
        assert is_prerelease("v3.0.0") is False
        assert is_prerelease("main") is False

    def test_ordering(self):
        versions = ["v1.10.0", "v1.9.0", "v2", "v2.0.0rc1"]
        assert sorted(versions, key=version_sort_key) == [
            "v1.9.0",
            "v1.10.0",
            "v2.0.0rc1",
            "v2",
        ]

    def test_omitted_components_are_zero(self):
        assert version_sort_key("v1.9") == version_sort_key("v1.9.0")

    def test_two_component_pin_orders_below_patch_release(self):
        assert version_sort_key("v4.1") < version_sort_key("v4.1.7")

    def test_is_sha(self):
        assert is_sha(SHA_OLD) is True
        assert is_sha("v4") is False
        assert is_sha("a" * 39) is False


class TestTargetRef:
    @pytest.mark.parametrize(
        "current,latest,expected",
        [
            ("v4", "v5.1.2", "v5"),
            ("v4.1", "v5.1.2", "v5.1"),
            ("v4.1.7", "v5.1.2", "v5.1.2"),
            ("4.1.7", "v5.1.2", "5.1.2"),
            ("2.21.3", "3.2.1", "3.2.1"),
            ("v1", "v1.2.3", None),
            ("v5.1.2", "v5.1.2", None),
            ("v6", "v5.1.2", None),
            ("main", "v5.1.2", None),
        ],
    )
    def test_preserves_pin_granularity(self, current, latest, expected):
        assert target_ref(current, latest) == expected

    def test_prerelease_suffix_kept_at_matching_depth(self):
        assert target_ref("v3.0.0", "v4.0.0rc1") == "v4.0.0rc1"
        assert target_ref("v3", "v4.0.0rc1") == "v4"


class TestParseUsesLine:
    def test_simple(self):
        ref = parse_uses_line("      - uses: actions/checkout@v4")
        assert ref.repo == "actions/checkout"
        assert ref.ref == "v4"
        assert ref.subpath == ""
        assert ref.comment == ""

    def test_with_comment(self):
        ref = parse_uses_line(f"        uses: actions/checkout@{SHA_OLD} # v4.1.7")
        assert ref.ref == SHA_OLD
        assert ref.comment == "v4.1.7"

    def test_quoted_value(self):
        ref = parse_uses_line('        uses: "pypa/cibuildwheel@v2.21.3"')
        assert ref.repo == "pypa/cibuildwheel"
        assert ref.ref == "v2.21.3"

    def test_subdirectory_action(self):
        ref = parse_uses_line("        uses: owner/repo/sub/dir@v1")
        assert ref.repo == "owner/repo"
        assert ref.subpath == "sub/dir"

    @pytest.mark.parametrize(
        "line",
        [
            "        uses: ./.github/actions/build",
            "        uses: docker://alpine:3.18",
            "        # uses: actions/checkout@v4",
            "        with: actions/checkout@v4",
            "        uses: actions/checkout",
            "        run: echo uses: actions/checkout@v4",
        ],
    )
    def test_ignores_non_updatable_lines(self, line):
        assert parse_uses_line(line) is None


class TestRenderUsesLine:
    def test_keeps_indentation_and_trailing_comment(self):
        line = "      - uses: actions/checkout@v4  # keep me"
        assert render_uses_line(line, "v5") == "      - uses: actions/checkout@v5  # keep me"

    def test_keeps_quotes(self):
        line = '        uses: "actions/checkout@v4"'
        assert render_uses_line(line, "v5") == '        uses: "actions/checkout@v5"'

    def test_adds_comment_when_missing(self):
        line = f"        uses: actions/checkout@{SHA_OLD}"
        assert render_uses_line(line, SHA_NEW, "v5.0.1") == (
            f"        uses: actions/checkout@{SHA_NEW}  # v5.0.1"
        )

    def test_preserves_carriage_return(self):
        line = "      - uses: actions/checkout@v4\r"
        assert render_uses_line(line, "v5") == "      - uses: actions/checkout@v5\r"

    def test_keeps_subpath(self):
        line = "        uses: owner/repo/sub@v1"
        assert render_uses_line(line, "v2") == "        uses: owner/repo/sub@v2"


class TestUpdateComment:
    def test_empty_comment_becomes_tag(self):
        assert update_comment("", "v5.0.1") == "v5.0.1"

    def test_replaces_version_token(self):
        assert update_comment("v4.1.7", "v5.0.1") == "v5.0.1"
        assert update_comment("pin to v4.1.7 for now", "v5.0.1") == "pin to v5.0.1 for now"

    def test_leaves_versionless_comment(self):
        assert update_comment("do not touch", "v5.0.1") == "do not touch"


WORKFLOW = """\
name: build
jobs:
  wheels:
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5.1.0
      - uses: pypa/cibuildwheel@v2.21.3
      - uses: actions/cache@main
      - uses: ./.github/actions/local
      - name: pin
        uses: actions/upload-artifact@{sha}  # v4.3.1
      - run: python -m pip install cibuildwheel==2.21.3
""".format(sha=SHA_OLD)

TAGS = {
    "actions/checkout": "v5.0.1",
    "actions/setup-python": "v5.4.0",
    "pypa/cibuildwheel": "v3.2.1",
    "actions/upload-artifact": "v4.6.0",
}


class TestUpdateUses:
    def _run(self, text, **kwargs):
        source = make_source(
            tags=TAGS,
            shas={("actions/upload-artifact", "v4.6.0"): SHA_NEW},
            pypi={"cibuildwheel": "3.2.1"},
        )
        updater = Updater(source, **kwargs)
        return updater, updater.update_text(Path("ci.yml"), text, True)

    def test_updates_each_pin_style(self):
        updater, out = self._run(WORKFLOW)
        assert "actions/checkout@v5" in out
        assert "actions/setup-python@v5.4.0" in out
        assert "pypa/cibuildwheel@v3.2.1" in out
        assert f"actions/upload-artifact@{SHA_NEW}  # v4.6.0" in out
        assert "cibuildwheel==3.2.1" in out

    def test_leaves_branch_and_local_refs(self):
        _, out = self._run(WORKFLOW)
        assert "actions/cache@main" in out
        assert "uses: ./.github/actions/local" in out

    def test_branch_ref_is_reported_as_skipped(self):
        updater, _ = self._run(WORKFLOW)
        reasons = {(skip.name, skip.reason) for skip in updater.result.skips}
        assert ("actions/cache", "not a version pin") in reasons

    def test_records_changes_with_line_numbers(self):
        updater, _ = self._run(WORKFLOW)
        checkout = [c for c in updater.result.changes if c.name == "actions/checkout"]
        assert len(checkout) == 1
        assert checkout[0].old == "v4"
        assert checkout[0].new == "v5"
        assert checkout[0].line_no == 5

    def test_idempotent(self):
        _, once = self._run(WORKFLOW)
        updater, twice = self._run(once)
        assert twice == once
        assert updater.result.changes == []

    def test_same_major_blocks_major_bumps(self):
        updater, out = self._run(WORKFLOW, same_major=True)
        assert "actions/checkout@v4" in out
        assert "actions/setup-python@v5.4.0" in out
        assert any(skip.name == "actions/checkout" for skip in updater.result.skips)

    def test_only_filter(self):
        updater, out = self._run(WORKFLOW, only=["cibuildwheel"])
        assert "actions/checkout@v4" in out
        assert "pypa/cibuildwheel@v3.2.1" in out

    def test_lookup_failure_is_reported_not_fatal(self):
        source = make_source(tags=TAGS, fail=["actions/checkout"])
        updater = Updater(source)
        out = updater.update_text(Path("ci.yml"), WORKFLOW, True)
        assert "actions/checkout@v4" in out
        assert "actions/setup-python@v5.4.0" in out
        assert updater.result.errors

    def test_up_to_date_sha_pin_untouched(self):
        text = f"        uses: actions/upload-artifact@{SHA_OLD}  # v4.6.0\n"
        _, out = self._run(text)
        assert out == text

    def test_preserves_unrelated_content(self):
        _, out = self._run(WORKFLOW)
        assert out.startswith("name: build\njobs:\n")
        assert out.count("\n") == WORKFLOW.count("\n")


class TestUpdatePins:
    def _run(self, text, latest="3.2.1"):
        source = make_source(pypi={"cibuildwheel": latest})
        updater = Updater(source)
        return updater, updater.update_pins(Path("pyproject.toml"), text)

    def test_updates_equality_pin(self):
        _, out = self._run('requires = ["cibuildwheel==2.21.3"]')
        assert out == 'requires = ["cibuildwheel==3.2.1"]'

    def test_updates_compatible_release_pin(self):
        _, out = self._run("cibuildwheel~=2.21.3")
        assert out == "cibuildwheel~=3.2.1"

    def test_preserves_pin_granularity(self):
        _, out = self._run("cibuildwheel==2.21")
        assert out == "cibuildwheel==3.2"

    def test_lower_bound_left_alone(self):
        updater, out = self._run("cibuildwheel>=2.21.3")
        assert out == "cibuildwheel>=2.21.3"
        assert any(skip.reason == "lower bound" for skip in updater.result.skips)

    def test_ignores_similar_names(self):
        text = "my-cibuildwheel==1.0.0\ncibuildwheel_helper==1.0.0"
        _, out = self._run(text)
        assert out == text

    def test_ignores_action_reference(self):
        text = "      - uses: pypa/cibuildwheel@v2.21.3"
        _, out = self._run(text)
        assert out == text

    def test_handles_extras_and_spacing(self):
        _, out = self._run("cibuildwheel[uv] == 2.21.3")
        assert out == "cibuildwheel[uv] == 3.2.1"

    def test_already_current_is_noop(self):
        updater, out = self._run("cibuildwheel==3.2.1")
        assert out == "cibuildwheel==3.2.1"
        assert updater.result.changes == []

    def test_pypi_failure_recorded(self):
        source = make_source(pypi={})
        updater = Updater(source)
        text = "cibuildwheel==2.21.3"
        assert updater.update_pins(Path("p.toml"), text) == text
        assert updater.result.errors


class TestVersionSource:
    def test_falls_back_to_tag_list_without_releases(self):
        source = make_source(tags={"owner/repo:all": ["v1.0.0", "v1.2.0", "v1.1.0"]})
        assert source.latest_tag("owner/repo") == "v1.2.0"

    def test_skips_prereleases_by_default(self):
        source = make_source(tags={"owner/repo:all": ["v1.2.0", "v2.0.0rc1"]})
        assert source.latest_tag("owner/repo") == "v1.2.0"

    def test_release_lookup_is_cached(self):
        calls = []

        def fetch(url, token):
            calls.append(url)
            return {"tag_name": "v5.0.1"}

        source = VersionSource(fetch=fetch)
        assert source.latest_tag("actions/checkout") == "v5.0.1"
        assert source.latest_tag("actions/checkout") == "v5.0.1"
        assert len(calls) == 1

    def test_annotated_tag_is_dereferenced(self):
        def fetch(url, token):
            if "/git/ref/tags/" in url:
                return {"object": {"type": "tag", "sha": "c" * 40}}
            if "/git/tags/" in url:
                return {"object": {"type": "commit", "sha": SHA_NEW}}
            raise AssertionError(url)

        source = VersionSource(fetch=fetch)
        assert source.tag_sha("actions/checkout", "v5.0.1") == SHA_NEW

    def test_missing_version_raises(self):
        source = make_source()
        with pytest.raises(VersionLookupError):
            source.latest_tag("owner/repo")


def make_repo(root: Path, workflow: bool = True, git: bool = False) -> Path:
    """Create a minimal project checkout on disk."""
    root.mkdir(parents=True, exist_ok=True)
    if workflow:
        workflows = root / ".github" / "workflows"
        workflows.mkdir(parents=True, exist_ok=True)
        (workflows / "ci.yml").write_text(
            "jobs:\n  b:\n    steps:\n      - uses: actions/checkout@v4\n",
            encoding="utf-8",
        )
    if git:
        (root / ".git").mkdir(exist_ok=True)
    (root / "requirements.txt").write_text("cibuildwheel==2.21.3\n", encoding="utf-8")
    return root


class TestProjectDiscovery:
    def test_workflow_directory_is_a_project(self, temp_dir):
        assert is_project_root(make_repo(temp_dir / "repo")) is True

    def test_git_checkout_without_workflows_is_a_project(self, temp_dir):
        repo = make_repo(temp_dir / "repo", workflow=False, git=True)
        assert is_project_root(repo) is True

    def test_plain_directory_is_not_a_project(self, temp_dir):
        (temp_dir / "plain").mkdir()
        assert is_project_root(temp_dir / "plain") is False

    def test_empty_workflow_directory_is_not_a_project(self, temp_dir):
        (temp_dir / "repo" / ".github" / "workflows").mkdir(parents=True)
        assert is_project_root(temp_dir / "repo") is False

    def test_finds_sibling_projects(self, temp_dir):
        make_repo(temp_dir / "repoA")
        make_repo(temp_dir / "repoB")
        (temp_dir / "notes").mkdir()
        assert find_project_roots(temp_dir) == [temp_dir / "repoA", temp_dir / "repoB"]

    def test_finds_projects_below_intermediate_directories(self, temp_dir):
        make_repo(temp_dir / "work" / "clients" / "repo")
        assert find_project_roots(temp_dir) == [temp_dir / "work" / "clients" / "repo"]

    def test_stops_at_the_outermost_project(self, temp_dir):
        outer = make_repo(temp_dir / "outer")
        make_repo(outer / "vendor_lib", git=True)
        assert find_project_roots(temp_dir) == [outer]

    def test_root_itself_can_be_the_project(self, temp_dir):
        repo = make_repo(temp_dir / "repo")
        assert find_project_roots(repo) == [repo]

    def test_prunes_noise_directories(self, temp_dir):
        make_repo(temp_dir / "node_modules" / "pkg")
        make_repo(temp_dir / ".cache" / "pkg")
        assert find_project_roots(temp_dir) == []

    def test_respects_max_depth(self, temp_dir):
        make_repo(temp_dir / "a" / "b" / "c" / "repo")
        assert find_project_roots(temp_dir, max_depth=2) == []
        assert find_project_roots(temp_dir, max_depth=4) == [
            temp_dir / "a" / "b" / "c" / "repo"
        ]


class TestTargetSelection:
    def test_globs_do_not_reach_into_sibling_projects(self, temp_dir):
        make_repo(temp_dir / "repoA")
        make_repo(temp_dir / "repoB")
        assert discover(temp_dir) == []

    def test_directory_is_one_project_by_default(self, temp_dir):
        make_repo(temp_dir / "repoA")
        assert targets_from_args([temp_dir]) == []

    def test_recursive_collects_every_project(self, temp_dir):
        make_repo(temp_dir / "repoA")
        make_repo(temp_dir / "repoB")
        found = {path for path, _ in targets_from_args([temp_dir], recursive=True)}
        assert found == {
            temp_dir / "repoA" / ".github" / "workflows" / "ci.yml",
            temp_dir / "repoA" / "requirements.txt",
            temp_dir / "repoB" / ".github" / "workflows" / "ci.yml",
            temp_dir / "repoB" / "requirements.txt",
        }

    def test_workflow_files_are_marked_as_such(self, temp_dir):
        repo = make_repo(temp_dir / "repo")
        flags = dict(targets_from_args([repo]))
        assert flags[repo / ".github" / "workflows" / "ci.yml"] is True
        assert flags[repo / "requirements.txt"] is False

    def test_overlapping_arguments_are_not_processed_twice(self, temp_dir):
        repo = make_repo(temp_dir / "repo")
        workflow = repo / ".github" / "workflows" / "ci.yml"
        targets = targets_from_args([temp_dir, repo, workflow], recursive=True)
        assert [path for path, _ in targets].count(workflow) == 1

    def test_explicit_file_outside_the_standard_layout(self, temp_dir):
        odd = temp_dir / "ci" / "constraints.txt"
        odd.parent.mkdir(parents=True)
        odd.write_text("cibuildwheel==2.21.3\n", encoding="utf-8")
        assert targets_from_args([odd]) == [(odd, False)]

    def test_missing_path_warns(self, temp_dir, capsys):
        assert targets_from_args([temp_dir / "nope"]) == []
        assert "does not exist" in capsys.readouterr().err


class TestCli:
    def _repo(self, root: Path) -> Path:
        workflows = root / ".github" / "workflows"
        workflows.mkdir(parents=True)
        (workflows / "ci.yml").write_text(WORKFLOW, encoding="utf-8")
        (root / "pyproject.toml").write_text(
            '[project]\ndependencies = ["cibuildwheel==2.21.3"]\n', encoding="utf-8"
        )
        return root

    def _source(self):
        return make_source(
            tags=TAGS,
            shas={("actions/upload-artifact", "v4.6.0"): SHA_NEW},
            pypi={"cibuildwheel": "3.2.1"},
        )

    def test_writes_updates(self, temp_dir, capsys):
        root = self._repo(temp_dir)
        assert main([str(root)], source=self._source()) == 0
        workflow = (root / ".github" / "workflows" / "ci.yml").read_text()
        assert "actions/checkout@v5" in workflow
        assert "cibuildwheel==3.2.1" in (root / "pyproject.toml").read_text()
        assert "Updated" in capsys.readouterr().out

    def test_dry_run_leaves_files_alone(self, temp_dir, capsys):
        root = self._repo(temp_dir)
        assert main(["-d", str(root)], source=self._source()) == 0
        assert (root / ".github" / "workflows" / "ci.yml").read_text() == WORKFLOW
        assert "Would update" in capsys.readouterr().out

    def test_check_reports_stale_pins(self, temp_dir):
        root = self._repo(temp_dir)
        assert main(["--check", str(root)], source=self._source()) == 2
        assert (root / ".github" / "workflows" / "ci.yml").read_text() == WORKFLOW

    def test_check_passes_when_current(self, temp_dir):
        root = self._repo(temp_dir)
        assert main([str(root)], source=self._source()) == 0
        assert main(["--check", str(root)], source=self._source()) == 0

    def test_single_file_argument(self, temp_dir):
        root = self._repo(temp_dir)
        workflow = root / ".github" / "workflows" / "ci.yml"
        assert main([str(workflow)], source=self._source()) == 0
        assert "actions/checkout@v5" in workflow.read_text()
        assert "cibuildwheel==2.21.3" in (root / "pyproject.toml").read_text()

    def test_errors_exit_nonzero(self, temp_dir):
        root = self._repo(temp_dir)
        source = make_source(tags=TAGS, pypi={"cibuildwheel": "3.2.1"}, fail=["actions/checkout"])
        assert main([str(root)], source=source) == 1

    def test_missing_target_reports_failure(self, temp_dir, capsys):
        assert main([str(temp_dir / "nope")], source=self._source()) == 1
        assert "No workflow" in capsys.readouterr().err

    def test_directory_of_repos_fails_loudly_without_recursive(self, temp_dir, capsys):
        make_repo(temp_dir / "repoA")
        make_repo(temp_dir / "repoB")
        assert main([str(temp_dir)], source=self._source()) == 1
        assert "use -r" in capsys.readouterr().err
        assert "cibuildwheel==2.21.3" in (temp_dir / "repoA" / "requirements.txt").read_text()

    def test_recursive_updates_every_repo(self, temp_dir):
        make_repo(temp_dir / "repoA")
        make_repo(temp_dir / "repoB")
        assert main(["-r", str(temp_dir)], source=self._source()) == 0
        for name in ("repoA", "repoB"):
            repo = temp_dir / name
            assert "actions/checkout@v5" in (
                repo / ".github" / "workflows" / "ci.yml"
            ).read_text()
            assert "cibuildwheel==3.2.1" in (repo / "requirements.txt").read_text()

    def test_recursive_shares_one_lookup_across_repos(self, temp_dir):
        make_repo(temp_dir / "repoA")
        make_repo(temp_dir / "repoB")
        make_repo(temp_dir / "repoC")
        calls = []

        def fetch(url, token):
            calls.append(url)
            if url.startswith("https://pypi.org"):
                return {"info": {"version": "3.2.1"}}
            return {"tag_name": "v5.0.1"}

        assert main(["-r", str(temp_dir)], source=VersionSource(fetch=fetch)) == 0
        assert len(calls) == 2

    def test_recursive_max_depth_is_honoured(self, temp_dir, capsys):
        make_repo(temp_dir / "a" / "b" / "repo")
        assert main(["-r", "--max-depth", "1", str(temp_dir)], source=self._source()) == 1
        assert main(["-r", str(temp_dir)], source=self._source()) == 0
