#!/usr/bin/env python3
# Copyright (C) 2026 bartman081523 (gpl-3.0-or-later)
"""Test harness for this repository's HA add-on plumbing.

Runs the real version/sed shell blocks extracted from the build
workflows against sandboxed copies of the add-on directories, so a wrong
sed path or broken version logic fails here instead of in an auto-push
(the edge-path regression in build_ha_addon_test.yml, fixed in PR #92,
would have been caught by this file). Also validates that the test
update-repo job commits to this repository (like edge) and validates the
add-on config.json/CHANGELOG.md consistency and the workflow wiring.
"""

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

try:
    import yaml
except ImportError:
    print("ERROR! pyyaml is required: pip install pyyaml")
    sys.exit(1)

ROOT = Path(__file__).resolve().parent.parent
WF = ROOT / ".github" / "workflows"
STABLE = "wmbusmeters-ha-addon"
EDGE = "wmbusmeters-ha-addon-edge"
TEST = "wmbusmeters-ha-addon-test"
ADDONS = [STABLE, EDGE, TEST]

# The payload version expression used by the dispatch workflows.
VER_EXPR = re.compile(r"\$\{\{\s*github\.event\.client_payload\.ver\s*\}\}")
VERSION_RE = re.compile(r"^\d+\.\d+\.\d+(\.\d+|-[0-9A-Za-z][0-9A-Za-z.\-]*)?$")

FAILURES = []


def check(cond, msg):
    if cond:
        print(f"OK   {msg}")
    else:
        FAILURES.append(msg)
        print(f"FAIL {msg}")
    return bool(cond)


def load_workflow(name):
    return yaml.safe_load((WF / name).read_text())


def triggers(wf):
    # PyYAML parses the unquoted "on:" key as boolean True.
    return wf.get("on") if "on" in wf else wf.get(True)


def get_step(wf, job, step_id=None, name_contains=None):
    for step in wf["jobs"][job]["steps"]:
        if step_id is not None and step.get("id") == step_id:
            return step
        if name_contains is not None and name_contains in step.get("name", ""):
            return step
    return None


def run_shell(script, cwd, raw_ver=None):
    """Run a workflow run-block locally with the payload expression substituted."""
    script = VER_EXPR.sub("${RAW_VER}", script)
    out = Path(cwd) / ".github_output"
    if out.exists():
        out.unlink()
    env = dict(os.environ, GITHUB_OUTPUT=str(out))
    if raw_ver is not None:
        env["RAW_VER"] = raw_ver
    proc = subprocess.run(
        ["bash", "-c", script], cwd=str(cwd), env=env, capture_output=True, text=True
    )
    outputs = {}
    if out.exists():
        for line in out.read_text().splitlines():
            if "=" in line:
                key, value = line.split("=", 1)
                outputs[key] = value
    return proc, outputs


def sandbox(tmp, name):
    ws = Path(tmp) / name
    ws.mkdir(parents=True)
    for addon in ADDONS:
        shutil.copytree(ROOT / addon, ws / addon)
    return ws


def snapshot(ws, addons):
    """Bytes of config.json + CHANGELOG.md, to pin dirs as untouched."""
    return {
        addon: (
            (ws / addon / "config.json").read_bytes(),
            (ws / addon / "CHANGELOG.md").read_bytes(),
        )
        for addon in addons
    }


def seed_version(addon_dir, ver):
    """Write a version the same way the workflows' sed does."""
    path = Path(addon_dir) / "config.json"
    text = path.read_text()
    text = re.sub(r'([ \t]{4,})"version".*', r'\g<1>"version": "%s",' % ver, text, count=1)
    path.write_text(text)


def config_version(ws, addon):
    return json.loads((ws / addon / "config.json").read_text())["version"]


def changelog_head(ws, addon):
    for line in (ws / addon / "CHANGELOG.md").read_text().splitlines():
        if line.strip():
            return line
    return ""


def test_workflows_parse_and_wiring(tmp):
    for name in [
        "build_ha_addon_edge.yml",
        "build_ha_addon_test.yml",
        "build_ha_addon_stable.yml",
        "build_ha_addon_on_pr.yml",
        "lint.yml",
        "dockerhub-description.yml",
        "tests.yml",
    ]:
        path = WF / name
        if not check(path.exists(), f"workflow {name} exists"):
            continue
        try:
            wf = load_workflow(name)
            check(triggers(wf) is not None, f"{name} parses with a trigger")
        except Exception as exc:
            check(False, f"{name} parses: {exc!r}")
    for name, expected in [
        ("build_ha_addon_edge.yml", "build_ha_edge"),
        ("build_ha_addon_test.yml", "build_ha_test"),
        ("build_ha_addon_stable.yml", "build_ha_stable"),
    ]:
        types = triggers(load_workflow(name))["repository_dispatch"]["types"]
        check(types == [expected], f"{name} is dispatched by {expected}")
    on_pr = triggers(load_workflow("build_ha_addon_on_pr.yml"))
    check(
        on_pr.get("push", {}).get("branches") == ["main"],
        "build_ha_addon_on_pr.yml triggers on push to main",
    )


def test_addon_configs(tmp):
    for addon in ADDONS:
        cfg = json.loads((ROOT / addon / "config.json").read_text())
        for key in ["name", "version", "slug", "description", "arch", "image"]:
            check(key in cfg, f"{addon}/config.json has {key}")
        check(cfg.get("slug") == addon, f"{addon}: slug matches the directory name")
        check(
            VERSION_RE.match(str(cfg.get("version", ""))) is not None,
            f"{addon}: version {cfg.get('version')!r} is well formed",
        )
        check(
            set(cfg.get("arch", [])) >= {"amd64", "aarch64"},
            f"{addon}: builds for amd64 and aarch64",
        )
        check(
            addon in str(cfg.get("image", "")),
            f"{addon}: image references the slug",
        )
        for fname in ["CHANGELOG.md", "Dockerfile", "DOCS.md", "run.sh", "rootfs", "translations"]:
            check((ROOT / addon / fname).exists(), f"{addon}/{fname} exists")
        check(
            changelog_head(ROOT, addon).startswith(f"## {cfg['version']}"),
            f"{addon}: CHANGELOG head matches config version {cfg['version']}",
        )
    edge_cfg = json.loads((ROOT / EDGE / "config.json").read_text())
    test_cfg = json.loads((ROOT / TEST / "config.json").read_text())
    stable_cfg = json.loads((ROOT / STABLE / "config.json").read_text())
    check(edge_cfg["name"].startswith("[edge] "), "edge name carries the [edge] channel prefix")
    check(test_cfg["name"].startswith("[test] "), "test name carries the [test] channel prefix")
    check(not stable_cfg["name"].startswith("["), "stable name has no channel prefix")


def test_edge_version_step(tmp):
    wf = load_workflow("build_ha_addon_edge.yml")
    step = get_step(wf, "prepare", step_id="version")
    if not check(step is not None, "edge workflow has an id: version step"):
        return
    check(
        (step.get("env") or {}).get("RAW_VER") == "${{ github.event.client_payload.ver || github.event.inputs.ver }}",
        "edge version step reads RAW_VER from the client payload or the Run workflow input",
    )
    ws = sandbox(tmp, "edge")
    seed_version(ws / EDGE, "3.0.0.100")
    before = snapshot(ws, [STABLE, TEST])
    proc, outputs = run_shell(step["run"], ws, raw_ver="3.0.0-138")
    check(proc.returncode == 0, f"edge version step exits 0 ({proc.stderr.strip()[:200]})")
    check(
        outputs.get("version") == "3.0.0.138",
        f"edge normalizes 3.0.0-138 to 3.0.0.138 (got {outputs.get('version')!r})",
    )
    check(
        config_version(ws, EDGE) == "3.0.0.138",
        "edge config.json version becomes 3.0.0.138",
    )
    check(
        changelog_head(ws, EDGE).startswith("## 3.0.0.138"),
        "edge CHANGELOG head matches the new version",
    )
    check(
        snapshot(ws, [STABLE, TEST]) == before,
        "edge version step leaves the stable and test dirs untouched",
    )


def test_edge_version_step_exact_tag_passthrough(tmp):
    wf = load_workflow("build_ha_addon_edge.yml")
    step = get_step(wf, "prepare", step_id="version")
    if step is None:
        return
    ws = sandbox(tmp, "edge_tag")
    proc, outputs = run_shell(step["run"], ws, raw_ver="3.0.0-RC1")
    check(proc.returncode == 0, "edge version step (exact tag) exits 0")
    check(
        outputs.get("version") == "3.0.0-RC1"
        and config_version(ws, EDGE) == "3.0.0-RC1",
        "edge passes exact tags like 3.0.0-RC1 through unchanged",
    )


def test_test_version_step(tmp):
    wf = load_workflow("build_ha_addon_test.yml")
    step = get_step(wf, "prepare", step_id="version")
    if not check(step is not None, "test workflow has an id: version step"):
        return
    check(
        (step.get("env") or {}).get("RAW_VER") == "${{ github.event.client_payload.ver || github.event.inputs.ver }}",
        "test version step reads RAW_VER from the client payload or the Run workflow input",
    )
    run_text = step["run"]
    check(
        f"{TEST}/config.json" in run_text,
        "test version step edits the test add-on config",
    )
    check(
        f"{EDGE}/config.json" not in run_text,
        "test version step no longer edits the edge add-on config (PR #92 regression)",
    )
    ws = sandbox(tmp, "test")
    seed_version(ws / TEST, "3.0.0.100")
    before = snapshot(ws, [STABLE, EDGE])
    proc, outputs = run_shell(run_text, ws, raw_ver="3.0.0-138")
    check(proc.returncode == 0, f"test version step exits 0 ({proc.stderr.strip()[:200]})")
    check(
        outputs.get("version") == "3.0.0.138",
        f"test workflow normalizes 3.0.0-138 to 3.0.0.138 (got {outputs.get('version')!r})",
    )
    check(config_version(ws, TEST) == "3.0.0.138", "test config.json version becomes 3.0.0.138")
    check(
        changelog_head(ws, TEST).startswith("## 3.0.0.138"),
        "test CHANGELOG head matches the new version",
    )
    check(
        snapshot(ws, [STABLE, EDGE]) == before,
        "test version step leaves the edge and stable dirs untouched",
    )


def test_test_breaking_notice(tmp, TEST=TEST, WF="build_ha_addon_test.yml"):
    """A pending BREAKING.md is applied once by the test version step: changelog entry,
    breaking_versions in config.json and NOTICE.md for the run.sh notification."""
    wf = load_workflow(WF)
    run_text = get_step(wf, "prepare", step_id="version")["run"]
    ws = sandbox(tmp, "test_breaking")
    seed_version(ws / TEST, "3.0.0.100")
    notice = "Entity names changed, see the changelog."
    # The real config.json may already list earlier breaking versions.
    earlier = json.loads((ws / TEST / "config.json").read_text()).get("breaking_versions", [])
    (ws / TEST / "BREAKING.md").write_text(notice + "\n")
    proc, _ = run_shell(run_text, ws, raw_ver="3.0.0-140")
    check(proc.returncode == 0, f"breaking version step exits 0 ({proc.stderr.strip()[:200]})")
    cfg = json.loads((ws / TEST / "config.json").read_text())
    check(cfg.get("version") == "3.0.0.140", "breaking build keeps the version")
    check(cfg.get("breaking_versions") == ["3.0.0.140"] + earlier, f"breaking_versions gets the version (got {cfg.get('breaking_versions')!r})")
    lines = (ws / TEST / "CHANGELOG.md").read_text().splitlines()
    check(lines[0].startswith("## 3.0.0.140"), "CHANGELOG head is still the new version")
    check("- **Breaking change:**" in lines[1:4] and f"  {notice}" in lines[1:5], "CHANGELOG entry carries the breaking change text")
    check(not (ws / TEST / "BREAKING.md").exists(), "BREAKING.md is consumed")
    check((ws / TEST / "NOTICE.md").read_text().splitlines() == ["3.0.0.140", notice], "NOTICE.md has the version and the text")

    # The next build without BREAKING.md: version update still works, nothing is added.
    proc, _ = run_shell(run_text, ws, raw_ver="3.0.0-141")
    cfg = json.loads((ws / TEST / "config.json").read_text())
    check(proc.returncode == 0 and cfg.get("version") == "3.0.0.141", "next build still updates the version")
    check(cfg.get("breaking_versions") == ["3.0.0.140"] + earlier, "next build keeps breaking_versions as is")
    check((ws / TEST / "NOTICE.md").read_text().splitlines()[0] == "3.0.0.140", "next build keeps the last NOTICE.md")

    # A second breaking build appends to breaking_versions.
    (ws / TEST / "BREAKING.md").write_text("Second change.\n")
    proc, _ = run_shell(run_text, ws, raw_ver="3.0.0-142")
    cfg = json.loads((ws / TEST / "config.json").read_text())
    check(sorted(cfg.get("breaking_versions", [])) == sorted(["3.0.0.140", "3.0.0.142"] + earlier), f"second breaking build appends (got {cfg.get('breaking_versions')!r})")


def test_test_update_repo(tmp):
    wf = load_workflow("build_ha_addon_test.yml")
    edge = load_workflow("build_ha_addon_edge.yml")
    job = wf["jobs"].get("update-repo")
    edge_job = edge["jobs"].get("update-repo")
    if not check(
        job is not None and edge_job is not None,
        "test and edge workflows both have an update-repo job",
    ):
        return
    steps_of = lambda j: j.get("steps", [])
    checkout = next((s for s in steps_of(job) if str(s.get("uses", "")).startswith("actions/checkout")), None)
    edge_checkout = next((s for s in steps_of(edge_job) if str(s.get("uses", "")).startswith("actions/checkout")), None)
    if not check(checkout is not None and edge_checkout is not None, "update-repo has a checkout step"):
        return
    check(
        "repository" not in (checkout.get("with") or {}),
        "test update-repo checks out this repository (no separate store repo, PR #92 regression)",
    )
    check(
        (checkout.get("with") or {}) == (edge_checkout.get("with") or {}),
        "test update-repo checkout options match the edge workflow",
    )
    download = next((s for s in steps_of(job) if str(s.get("uses", "")).startswith("actions/download-artifact")), None)
    check(
        download is not None and "path" not in (download.get("with") or {}),
        "test update-repo unpacks the artifact at the workspace root (like edge)",
    )
    check(
        not any("rsync" in s.get("run", "") for s in steps_of(job)),
        "test update-repo has no rsync step",
    )
    commit = next((s for s in steps_of(job) if str(s.get("uses", "")).startswith("EndBug/add-and-commit")), None)
    edge_commit = next((s for s in steps_of(edge_job) if str(s.get("uses", "")).startswith("EndBug/add-and-commit")), None)
    check(
        commit is not None
        and edge_commit is not None
        and (commit.get("with") or {}).get("message") == (edge_commit.get("with") or {}).get("message"),
        "test auto-push message matches the edge auto-push message",
    )
    # The BREAKING.md consumed by the prepare job must also leave the repository,
    # otherwise every later build announces the same breaking change again.
    for j, addon in ((job, TEST), (edge_job, EDGE)):
        check_breaking_removal(tmp, j, addon)


def check_breaking_removal(tmp, job, addon):
    steps_of = lambda j: j.get("steps", [])
    commit = next((s for s in steps_of(job) if str(s.get("uses", "")).startswith("EndBug/add-and-commit")), None)
    remove = next((s for s in steps_of(job) if "BREAKING.md" in s.get("run", "")), None)
    if not check(
        remove is not None and commit is not None and steps_of(job).index(remove) < steps_of(job).index(commit),
        f"{addon} update-repo removes the announced BREAKING.md before pushing",
    ):
        return
    cases = [
        ("announced now", "3.0.0.226", True, False),
        ("added after this build started", "3.0.0.222", True, True),
        ("no BREAKING.md", "3.0.0.226", False, False),
    ]
    for label, notice_ver, has_breaking, kept in cases:
        ws = Path(tmp) / f"update_repo_{addon}_{label.replace(' ', '_')}" / addon
        ws.mkdir(parents=True)
        (ws / "NOTICE.md").write_text(f"{notice_ver}\nSome change.\n")
        if has_breaking:
            (ws / "BREAKING.md").write_text("Some change.\n")
        script = remove["run"].replace("${{ needs.prepare.outputs.version }}", "3.0.0.226")
        proc = subprocess.run(["bash", "-c", script], cwd=ws.parent, capture_output=True, text=True, timeout=30)
        check(proc.returncode == 0, f"{addon} update-repo BREAKING.md step '{label}' exits 0 ({proc.stderr.strip()[:200]})")
        check(
            (ws / "BREAKING.md").exists() == kept,
            f"{addon} update-repo BREAKING.md step '{label}': BREAKING.md {'kept' if kept else 'removed or absent'}",
        )


def test_push_dispatches_builds(tmp):
    """A push to main dispatches the edge build, and the test build when the [test]
    add-on changed, to the same workflows as a wmbusmeters commit (version numbering
    and BREAKING.md in one place)."""
    wf = load_workflow("build_ha_addon_on_pr.yml")
    steps = [st for job in wf["jobs"].values() for st in job.get("steps", [])]
    dispatch = {
        (st.get("with") or {}).get("event-type"): st
        for st in steps
        if str(st.get("uses", "")).startswith("peter-evans/repository-dispatch")
    }
    check(set(dispatch) == {"build_ha_edge", "build_ha_test"}, f"push dispatches edge and test builds (got {sorted(dispatch)})")
    check("if" not in dispatch.get("build_ha_edge", {}), "push always dispatches the edge build")
    check("steps.changed.outputs.test" in str(dispatch.get("build_ha_test", {}).get("if", "")), "push dispatches the test build only when [test] changed")
    check(
        not any(str(st.get("uses", "")).startswith("home-assistant/builder") for st in steps),
        "push workflow does not build an add-on itself",
    )


def test_version_never_reused(tmp):
    """Without a version, or with one that is not higher than the current one, a build
    gets the current one + 1; a higher version is used as is."""
    cases = [
        # current, requested, expected
        ("3.0.0.229", "", "3.0.0.230"),
        ("3.0.0.229", "3.0.0-229", "3.0.0.230"),
        ("3.0.0.229", "3.0.0-150", "3.0.0.230"),
        ("3.0.0.229", "3.0.0-231", "3.0.0.231"),
        ("3.0.0.229", "3.0.0-RC1", "3.0.0-RC1"),
        ("3.0.0-134-3", "", "3.0.0-134-4"),
        ("3.0.0-134", "", "3.0.0-134-1"),
    ]
    for wf_name, addon in (("build_ha_addon_test.yml", TEST), ("build_ha_addon_edge.yml", EDGE)):
        step = get_step(load_workflow(wf_name), "prepare", step_id="version")
        if not check(step is not None, f"{wf_name} has an id: version step"):
            continue
        for cur, req, expected in cases:
            ws = sandbox(tmp, f"ver_{addon}_{cur}_{req or 'none'}".replace(".", "_"))
            seed_version(ws / addon, cur)
            breaking = ws / addon / "BREAKING.md"
            if breaking.exists():
                breaking.unlink()
            proc, outputs = run_shell(step["run"], ws, raw_ver=req)
            check(proc.returncode == 0, f"{addon} version {cur} + {req!r} exits 0 ({proc.stderr.strip()[:200]})")
            check(
                outputs.get("version") == expected and config_version(ws, addon) == expected,
                f"{addon}: current {cur}, requested {req!r} gives {expected} (got {outputs.get('version')!r})",
            )


def test_stable_version_step(tmp):
    wf = load_workflow("build_ha_addon_stable.yml")
    step = get_step(wf, "prepare", name_contains="set version")
    if not check(step is not None, "stable workflow has a version step"):
        return
    ws = sandbox(tmp, "stable")
    before = snapshot(ws, [TEST])
    proc, _ = run_shell(step["run"], ws, raw_ver="3.0.0")
    check(proc.returncode == 0, f"stable version step exits 0 ({proc.stderr.strip()[:200]})")
    stable_cfg = json.loads((ws / STABLE / "config.json").read_text())
    check(
        stable_cfg["version"] == "3.0.0",
        f"stable config version becomes the raw tag (got {stable_cfg['version']!r})",
    )
    check(
        "[edge]" not in stable_cfg.get("name", "")
        and "-edge" not in stable_cfg.get("slug", "")
        and "-edge" not in stable_cfg.get("image", ""),
        "stable config has no edge markers",
    )
    check(
        changelog_head(ws, STABLE).startswith("## 3.0.0 "),
        "stable CHANGELOG head matches the tag",
    )
    check(snapshot(ws, [TEST]) == before, "stable version step leaves the test dir untouched")


def test_dockerhub_matrix(tmp):
    dh = load_workflow("dockerhub-description.yml")
    releases = []
    for job in (dh.get("jobs") or {}).values():
        matrix = (job.get("strategy") or {}).get("matrix") or {}
        if isinstance(matrix.get("release"), list):
            releases = matrix["release"]
    check(
        sorted(releases) == sorted(ADDONS),
        f"dockerhub-description covers exactly the three add-on image repos (got {releases})",
    )


def test_lint_path(tmp):
    lint = load_workflow("lint.yml")
    paths = []
    for job in (lint.get("jobs") or {}).values():
        for step in job.get("steps", []):
            if "path" in (step.get("with") or {}):
                paths.append(step["with"]["path"].lstrip("./"))
    check(
        len(paths) == 1 and paths[0] in ADDONS,
        f"lint.yml lints one existing add-on dir (got {paths})",
    )


def test_ci_runs_the_harness(tmp):
    found = any("tests/test_workflows.py" in path.read_text() for path in WF.glob("*.yml"))
    check(found, "a workflow runs tests/test_workflows.py")


def test_test_discovery_hook(tmp, TEST=TEST):
    """The test add-on generates discovery on the first telegram via the
    metershell hook. wmbusmeters only accepts the key "metershell"
    (src/config.cc), and the hook needs the xmq binary plus libxslt in
    the runtime image to render the discovery json (wmbusmeters#2092)."""
    run_text = (ROOT / TEST / "run.sh").read_text()
    check(
        run_text.count("meter_shell") == 1 and "del(.conf.meter_shell)" in run_text,
        f"{TEST}/run.sh only references meter_shell in the stale-key cleanup",
    )
    check(
        run_text.count('"metershell": "send_meter_discovery.sh') == 2,
        f"{TEST}/run.sh default config sets metershell twice (first run + reset)",
    )
    check(
        ".conf.metershell" in run_text and run_text.count(".conf.meter_shell") == 1,
        f"{TEST}/run.sh backfill reads and writes the metershell key",
    )
    default_cfgs = re.findall(r"^    echo '(\{.*\})' \| jq \. > \$\{CONFIG_PATH\}$", run_text, re.M)
    check(len(default_cfgs) == 2, f"{TEST}/run.sh has two default config literals (got {len(default_cfgs)})")
    for raw in default_cfgs:
        cfg = json.loads(raw)
        hook = cfg.get("conf", {}).get("metershell", "")
        check(
            hook == 'send_meter_discovery.sh "$METER_JSON" "$METER_DRIVER"',
            f"{TEST}/run.sh default metershell passes METER_JSON and METER_DRIVER (got {hook!r})",
        )
        check("meter_shell" not in cfg.get("conf", {}), f"{TEST}/run.sh default config has no meter_shell key")
    hook = (ROOT / TEST / "send_meter_discovery.sh").read_text()
    check("meter_shell" not in hook, f"{TEST}/send_meter_discovery.sh documents the metershell key")
    check(
        "transform" in hook and "to-ha-discovery.xslq" in hook,
        f"{TEST}/send_meter_discovery.sh renders discovery via the xmq transform",
    )
    dockerfile = (ROOT / TEST / "Dockerfile").read_text()
    runtime = dockerfile.split("AS runtime", 1)[1]
    check(
        re.search(r"COPY --from=build \S*bin/xmq /usr/local/bin/xmq", runtime) is not None,
        f"{TEST}/Dockerfile copies the xmq binary into the runtime image",
    )
    check(
        re.search(r"^    libxslt( \\)?$", runtime, re.M) is not None,
        f"{TEST}/Dockerfile installs libxslt in the runtime image",
    )
    check(
        "COPY send_meter_discovery.sh" in runtime and "COPY to-ha-discovery.xslq" in runtime,
        f"{TEST}/Dockerfile ships the hook and its transform",
    )


def test_data_path_migration(tmp):
    """f21a2e3a mapped homeassistant_config instead of config, which moves the
    HA config dir mount from /config to /homeassistant. A data_path under
    /config then points at an empty ephemeral directory, so run.sh must
    default to /homeassistant/wmbusmeters and migrate an existing
    /config/* data_path on start: check the mount, back up
    options_custom.json, rescue files at the old location, log each step."""
    for addon in ADDONS:
        run_text = (ROOT / addon / "run.sh").read_text()
        if not check(
            run_text.count("# BEGIN data_path migration") == 1
            and run_text.count("# END data_path migration") == 1,
            f"{addon}/run.sh marks the data_path migration block",
        ):
            continue
        check(
            "/config/wmbusmeters" not in run_text,
            f"{addon}/run.sh no longer defaults data_path to /config/wmbusmeters",
        )
        defaults = [
            json.loads(m)
            for m in re.findall(
                r"^    echo '(\{.*\})' \| jq \. > \$\{CONFIG_PATH\}$", run_text, re.M
            )
        ]
        check(len(defaults) >= 1, f"{addon}/run.sh default config literals parse")
        for cfg in defaults:
            check(
                cfg.get("data_path") == "/homeassistant/wmbusmeters",
                f"{addon}/run.sh defaults data_path to /homeassistant/wmbusmeters",
            )
        block = run_text.split("# BEGIN data_path migration", 1)[1].split(
            "# END data_path migration", 1
        )[0]
        # Redirect the in-container paths into the sandbox.
        sim_block = (
            block.replace("/homeassistant", "$SIM_ROOT/homeassistant")
            .replace("/config", "$SIM_ROOT/config")
        )
        cases = [
            ("old default", "/config/wmbusmeters", "/homeassistant/wmbusmeters", True),
            ("custom path", "/config/mycustom", "/homeassistant/mycustom", True),
            ("other path", "/data/custom", "/data/custom", True),
            ("not mounted", "/config/wmbusmeters", "/config/wmbusmeters", False),
        ]
        for label, old, expected, mounted in cases:
            ws = Path(tmp) / f"mig_{addon}_{label.replace(' ', '_')}"
            ws.mkdir(parents=True)
            # The sandbox redirects the in-container paths, so the initial
            # data_path value and the expectation follow the same rewrite.
            sim_old = old.replace("/config", str(ws / "config"))
            sim_expected = expected.replace("/config", str(ws / "config")).replace(
                "/homeassistant", str(ws / "homeassistant")
            )
            (ws / "options_custom.json").write_text(
                json.dumps({"data_path": sim_old, "conf": {}, "meters": [], "mqtt": {}})
            )
            if old.startswith("/config"):
                old_dir = ws / "config" / old[len("/config/") :].strip("/")
                old_dir.mkdir(parents=True)
                (old_dir / "custom_discovery.json").write_text('{"kept": true}')
                new_dir = ws / "homeassistant" / old[len("/config/") :].strip("/")
                if expected != old:
                    new_dir.mkdir(parents=True)
                    (new_dir / "existing.json").write_text("newer\n")
            sim = (
                "grep() { if [ \"$3\" = \"/proc/mounts\" ]; then [ -n \"$HA_MOUNTED\" ]; return; fi; command grep \"$@\"; }\n"
                'bashio::log.info() { echo "INFO: $*"; }\n'
                'bashio::log.warning() { echo "WARNING: $*"; }\n'
                f"SIM_ROOT={ws}\nHA_MOUNTED={'1' if mounted else ''}\nCONFIG_PATH={ws}/options_custom.json\n"
                f"CONFIG_DATA_PATH='{sim_old}'\n"
                f"{sim_block}\n"
                'echo "RESULT_DATA_PATH=$CONFIG_DATA_PATH"\n'
            )
            proc = subprocess.run(
                ["bash", "-c", sim], capture_output=True, text=True, timeout=30
            )
            check(
                proc.returncode == 0,
                f"{addon} migration sim '{label}' exits 0 ({proc.stderr.strip()[:200]})",
            )
            opts = json.loads((ws / "options_custom.json").read_text())
            check(
                opts.get("data_path") == sim_expected,
                f"{addon} sim '{label}': data_path becomes {sim_expected} (got {opts.get('data_path')!r})",
            )
            check(
                f"RESULT_DATA_PATH={sim_expected}" in proc.stdout,
                f"{addon} sim '{label}': CONFIG_DATA_PATH variable follows",
            )
            if expected != old:
                check(
                    (ws / "options_custom.json.bak").exists()
                    and sim_old in (ws / "options_custom.json.bak").read_text(),
                    f"{addon} sim '{label}': backup of the original options exists",
                )
                check(
                    (ws / "homeassistant" / old[len("/config/") :].strip("/") / "custom_discovery.json").exists(),
                    f"{addon} sim '{label}': files at the old location are rescued",
                )
                check(
                    (ws / "homeassistant" / old[len("/config/") :].strip("/") / "existing.json").read_text()
                    == "newer\n",
                    f"{addon} sim '{label}': rescue copy does not overwrite existing files",
                )
                check(
                    "Migrated data_path" in proc.stdout,
                    f"{addon} sim '{label}': migration is logged",
                )
            else:
                check(
                    not (ws / "options_custom.json.bak").exists(),
                    f"{addon} sim '{label}': no backup written without a migration",
                )
                if old.startswith("/config"):
                    # Only a /config/* path that cannot be migrated falls back
                    # with a warning; an unrelated path is untouched silently.
                    check(
                        "WARNING" in proc.stdout,
                        f"{addon} sim '{label}': fallback is logged as a warning",
                    )


def test_conf_path_migration(tmp):
    """The homeassistant_config mapping also breaks paths in conf: a logfile or
    meterfiles under /config cannot be written and wmbusmeters exits with
    status 14 (wmbusmeters#2140). run.sh must migrate every conf value under
    /config to /homeassistant when it is mounted, create the directories,
    back up options_custom.json and log each key; other values stay."""
    for addon in ADDONS:
        run_text = (ROOT / addon / "run.sh").read_text()
        if not check(
            run_text.count("# BEGIN conf path migration") == 1
            and run_text.count("# END conf path migration") == 1,
            f"{addon}/run.sh marks the conf path migration block",
        ):
            continue
        check(
            run_text.index("# END conf path migration") < run_text.index("CONFIG_CONF=$(bashio::jq"),
            f"{addon}/run.sh migrates the conf paths before reading conf",
        )
        block = run_text.split("# BEGIN conf path migration", 1)[1].split(
            "# END conf path migration", 1
        )[0]
        cases = [
            ("mounted", True),
            ("not mounted", False),
            ("nothing to migrate", True),
        ]
        for label, mounted in cases:
            ws = Path(tmp) / f"confmig_{addon}_{label.replace(' ', '_')}"
            ws.mkdir(parents=True)
            old, new = f"{ws}/config/", f"{ws}/homeassistant/"
            sim_block = block.replace(
                'CONF_OLD_PREFIX="/config/"', f'CONF_OLD_PREFIX="{old}"'
            ).replace('CONF_NEW_PREFIX="/homeassistant/"', f'CONF_NEW_PREFIX="{new}"')
            conf = {
                "logfile": "/dev/stdout" if label == "nothing to migrate" else old + "wmbusmeters/logs/logfile.txt",
                "meterfiles": "/data/readings" if label == "nothing to migrate" else old + "wmbusmeters/logs/meter_readings",
                "shell": '/wmbusmeters/mosquitto_pub.sh "wmbusmeters/$METER_NAME" "$METER_JSON"',
                "loglevel": "normal",
            }
            (ws / "options_custom.json").write_text(
                json.dumps({"data_path": "/data/x", "conf": conf, "meters": [], "mqtt": {}})
            )
            sim = (
                "config_dir_mounted() { [ -n \"$HA_MOUNTED\" ]; }\n"
                'bashio::log.info() { echo "INFO: $*"; }\n'
                'bashio::log.warning() { echo "WARNING: $*"; }\n'
                f"HA_MOUNTED={'1' if mounted else ''}\nCONFIG_PATH={ws}/options_custom.json\n"
                f"{sim_block}\n"
            )
            proc = subprocess.run(["bash", "-c", sim], capture_output=True, text=True, timeout=30)
            check(
                proc.returncode == 0,
                f"{addon} conf migration sim '{label}' exits 0 ({proc.stderr.strip()[:200]})",
            )
            got = json.loads((ws / "options_custom.json").read_text())["conf"]
            backup = ws / "options_custom.json.conf_paths.bak"
            if label == "mounted":
                check(
                    got["logfile"] == new + "wmbusmeters/logs/logfile.txt"
                    and got["meterfiles"] == new + "wmbusmeters/logs/meter_readings",
                    f"{addon} conf sim '{label}': logfile and meterfiles move to /homeassistant (got {got['logfile']!r}, {got['meterfiles']!r})",
                )
                check(
                    got["shell"] == conf["shell"] and got["loglevel"] == "normal",
                    f"{addon} conf sim '{label}': other conf values are untouched",
                )
                check(
                    (ws / "homeassistant/wmbusmeters/logs/meter_readings").is_dir(),
                    f"{addon} conf sim '{label}': the meterfiles directory is created",
                )
                check(
                    backup.exists() and old in backup.read_text(),
                    f"{addon} conf sim '{label}': backup of the original options exists",
                )
                check(
                    proc.stdout.count("Migrated ") == 2,
                    f"{addon} conf sim '{label}': each migrated key is logged",
                )
            else:
                check(got == conf, f"{addon} conf sim '{label}': conf is unchanged")
                check(not backup.exists(), f"{addon} conf sim '{label}': no backup without a migration")
                check(
                    ("WARNING" in proc.stdout) == (label == "not mounted"),
                    f"{addon} conf sim '{label}': a warning only when /config paths stay",
                )


def test_test_conf_split(tmp, TEST=TEST):
    """run.sh splits a config value on ";" into several key= lines (several
    devices), but a ";" inside parentheses belongs to the value, e.g. the
    shell command in CMD(...), and the key ends at the first "="."""
    run_text = (ROOT / TEST / "run.sh").read_text()
    if not check(
        run_text.count("# BEGIN conf split") == 1 and run_text.count("# END conf split") == 1,
        f"{TEST}/run.sh marks the conf split block",
    ):
        return
    block = run_text.split("# BEGIN conf split", 1)[1].split("# END conf split", 1)[0]
    ws = Path(tmp) / "conf_split"
    (ws / "etc").mkdir(parents=True)
    conf_in = [
        "loglevel=normal",
        "device=auto:t1;rtlwmbus",
        "device=rtlwmbus:CMD(mosquitto_sub -t a/b | sed -u 's/^/T1;1;1;;-50;;;0x/')",
        "device=rtlwmbus:CMD(echo a=b;c);auto:c1",
        'shell=/wmbusmeters/mosquitto_pub.sh "wmbusmeters/$METER_NAME" "$METER_JSON"',
    ]
    expected = [
        "loglevel=normal",
        "device=auto:t1",
        "device=rtlwmbus",
        "device=rtlwmbus:CMD(mosquitto_sub -t a/b | sed -u 's/^/T1;1;1;;-50;;;0x/')",
        "device=rtlwmbus:CMD(echo a=b;c)",
        "device=auto:c1",
        'shell=/wmbusmeters/mosquitto_pub.sh "wmbusmeters/$METER_NAME" "$METER_JSON"',
    ]
    (ws / "etc" / "wmbusmeters.conf").write_text("\n".join(conf_in) + "\n")
    proc = subprocess.run(
        ["bash", "-c", f"CONFIG_DATA_PATH={ws}\n{block}"],
        capture_output=True, text=True, timeout=30,
    )
    check(proc.returncode == 0, f"conf split exits 0 ({proc.stderr.strip()[:200]})")
    got = (ws / "etc" / "wmbusmeters.conf").read_text().splitlines()
    check(got == expected, f"conf split keeps ';' inside CMD(...) and splits outside it (got {got!r})")


def test_test_discovery_cleanup(tmp, TEST=TEST):
    """After publishing the discovery of a meter, send_meter_discovery.sh removes the
    retained discovery of the same meter that was not published now (renamed or
    dropped fields), and leaves other meters alone."""
    run_text = (ROOT / TEST / "run.sh").read_text()
    check(
        "--retained-only" in run_text and "-r -t \"\\$2\" -n" in run_text,
        f"{TEST}/run.sh generates the retained list/clear helper",
    )
    send_text = (ROOT / TEST / "send_meter_discovery.sh").read_text()
    if not check(
        send_text.count("# BEGIN discovery cleanup") == 1 and send_text.count("# END discovery cleanup") == 1,
        f"{TEST}/send_meter_discovery.sh marks the discovery cleanup block",
    ):
        return
    block = send_text.split("# BEGIN discovery cleanup", 1)[1].split("# END discovery cleanup", 1)[0]
    ws = Path(tmp) / "discovery_cleanup"
    ws.mkdir(parents=True)
    keep = "homeassistant/sensor/wmbusmeters/04913581_total_m3/config"
    stale = "homeassistant/binary_sensor/wmbusmeters/04913581_status_LOW_BATTERY/config"
    similar_id = "homeassistant/sensor/wmbusmeters/049135810_total_m3/config"
    other_meter = "homeassistant/sensor/wmbusmeters/12345678_status_LOW_BATTERY/config"
    helper = ws / "retained.sh"
    helper.write_text(
        "#!/bin/bash\n"
        f'if [ "$1" = list ]; then printf "%s\\n" {keep} {stale} {similar_id} {other_meter}; fi\n'
        f'if [ "$1" = clear ]; then echo "$2" >> {ws}/cleared; fi\n'
    )
    helper.chmod(0o755)
    sim = (
        f"ID=04913581\nPUBLISHED=' {keep} homeassistant/binary_sensor/wmbusmeters/04913581_status/config'\n"
        + block.replace("/wmbusmeters/mosquitto_retained.sh", str(helper))
    )
    proc = subprocess.run(["bash", "-c", sim], capture_output=True, text=True, timeout=30)
    check(proc.returncode == 0, f"discovery cleanup exits 0 ({proc.stderr.strip()[:200]})")
    cleared = (ws / "cleared").read_text().split() if (ws / "cleared").exists() else []
    check(
        cleared == [stale],
        f"discovery cleanup removes only the stale topic of this meter (got {cleared!r})",
    )


def _mode_migration_block(run_text, addon):
    """The real "MQTT discovery" mode migration block of run.sh, or None."""
    if not (
        run_text.count("# BEGIN mqtt discovery mode migration") == 1
        and run_text.count("# END mqtt discovery mode migration") == 1
    ):
        check(False, f"{addon}/run.sh marks the mqtt discovery mode migration block")
        return None
    check(True, f"{addon}/run.sh marks the mqtt discovery mode migration block")
    return run_text.split("# BEGIN mqtt discovery mode migration", 1)[1].split(
        "# END mqtt discovery mode migration", 1
    )[0]


def _run_mode_migration(tmp, addon, run_text, label, config, expected_gone=("enable_mqtt_discovery",)):
    """Run the mode migration of run.sh on a sandboxed options_custom.json."""
    block = _mode_migration_block(run_text, addon)
    if block is None:
        return None
    ws = Path(tmp) / f"mode_{addon.replace('wmbusmeters-ha-addon-', '')}_{label.replace(' ', '_')}"
    (ws / "data").mkdir(parents=True)
    cfg = ws / "data" / "options_custom.json"
    cfg.write_text(json.dumps(config, indent=True) + "\n")
    sim = (
        'bashio::log.info() { echo "INFO: $*"; }\n'
        f"CONFIG_PATH={cfg}\n"
        + block.replace("/data/", f"{ws}/data/")
    )
    proc = subprocess.run(["bash", "-c", sim], capture_output=True, text=True, timeout=30)
    check(
        proc.returncode == 0,
        f"{addon} mode sim '{label}' exits 0 ({proc.stderr.strip()[:200]})",
    )
    return json.loads(cfg.read_text())


def _check_mode_wiring(addon, default_mode):
    """Both discovery pipelines must honour the mode, and the manual one must
    actually work at runtime: the script, its templates and the panel choice."""
    send_text = (ROOT / addon / "send_meter_discovery.sh").read_text()
    run_text = (ROOT / addon / "run.sh").read_text()

    mode_check = send_text.find(".mqtt_discovery // empty")
    check(
        0 < mode_check < send_text.find("PUB=/wmbusmeters/mosquitto_pub.sh"),
        f"{addon}/send_meter_discovery.sh checks the mqtt_discovery mode before publishing",
    )
    check(
        '!= "auto"' in send_text[mode_check : mode_check + 200],
        f"{addon}/send_meter_discovery.sh publishes the generated discovery in the auto mode only",
    )
    check(
        ".enable_mqtt_discovery" not in send_text,
        f"{addon}/send_meter_discovery.sh no longer reads the legacy flag",
    )

    defaults = [
        json.loads(m)
        for m in re.findall(r"^    echo '(\{.*\})' \| jq \. > \$\{CONFIG_PATH\}$", run_text, re.M)
    ]
    check(
        len(defaults) == 2 and all(c.get("mqtt_discovery") == default_mode for c in defaults),
        f"{addon}/run.sh default configs use mqtt_discovery={default_mode!r}",
    )
    check(
        all("enable_mqtt_discovery" not in c for c in defaults),
        f"{addon}/run.sh default configs have no legacy discovery flag",
    )

    manual_call = run_text.find("/mqtt_discovery.sh")
    if check(manual_call > 0, f"{addon}/run.sh calls mqtt_discovery.sh (manual mode)"):
        check(
            '= "manual"' in run_text[max(0, manual_call - 300) : manual_call],
            f"{addon}/run.sh calls mqtt_discovery.sh in the manual mode only",
        )

    script = (ROOT / addon / "mqtt_discovery.sh").read_text()
    check(
        '!= "manual"' in script and ".mqtt_discovery" in script,
        f"{addon}/mqtt_discovery.sh publishes only in the manual mode",
    )
    check(
        "cp -n /mqtt_discovery/*" in script,
        f"{addon}/mqtt_discovery.sh never overwrites a template the user edited",
    )

    templates = sorted(p.name for p in (ROOT / addon / "mqtt_discovery").glob("*.json"))
    check(
        len(templates) > 30 and "hydrus.json" in templates,
        f"{addon}/mqtt_discovery holds the templates of the pre-3.1 add-on (got {len(templates)})",
    )
    dockerfile = (ROOT / addon / "Dockerfile").read_text()
    runtime = dockerfile.split("AS runtime", 1)[1]
    check(
        "COPY mqtt_discovery/ /mqtt_discovery/" in runtime and "COPY mqtt_discovery.sh /" in runtime,
        f"{addon}/Dockerfile ships the manual pipeline",
    )
    docs = (ROOT / addon / "DOCS.md").read_text()
    check(
        all(word in docs for word in ("Disable", "Automatic", "Manual")),
        f"{addon}/DOCS.md documents the three MQTT discovery modes",
    )


def test_test_discovery_mode(tmp):
    """[test] honours the three-way "MQTT discovery" (disable/auto/manual):
    the generated hook publishes in auto only, manual templates are published
    by run.sh in manual only, and the old flag becomes a mode once."""
    _check_mode_wiring(TEST, "auto")
    run_text = (ROOT / TEST / "run.sh").read_text()

    cases = [
        # (label, config, expected mode)
        ("old default false becomes auto",
         {"enable_mqtt_discovery": "false", "conf": {}}, "auto"),
        ("old true becomes auto",
         {"enable_mqtt_discovery": True, "conf": {}}, "auto"),
        ("new mode survives",
         {"mqtt_discovery": "manual", "conf": {}}, "manual"),
        ("new mode wins over the old flag",
         {"mqtt_discovery": "disable", "enable_mqtt_discovery": True}, "disable"),
    ]
    for label, config, expected in cases:
        opts = _run_mode_migration(tmp, TEST, run_text, label, config)
        if opts is None:
            return
        check(
            opts.get("mqtt_discovery") == expected,
            f"{TEST} mode sim '{label}': mqtt_discovery becomes {expected!r} (got {opts.get('mqtt_discovery')!r})",
        )
        check(
            "enable_mqtt_discovery" not in opts,
            f"{TEST} mode sim '{label}': the legacy key is dropped",
        )


def test_edge_discovery_mode(tmp):
    """Edge honours the three-way "MQTT discovery" like [test], but keeps the
    generated discovery off unless the user asks for it (no one-time switch),
    and translates the old boolean instead of forcing auto."""
    _check_mode_wiring(EDGE, "disable")
    run_text = (ROOT / EDGE / "run.sh").read_text()

    cases = [
        # (label, config, expected mode, old key dropped)
        ("chosen false becomes disable",
         {"enable_mqtt_discovery": "false", "conf": {}}, "disable", True),
        ("true becomes auto",
         {"enable_mqtt_discovery": "true", "conf": {}}, "auto", True),
        ("legacy true becomes auto",
         {"enable_mqtt_discovery": True, "conf": {}}, "auto", True),
        ("new mode survives",
         {"mqtt_discovery": "manual", "conf": {}}, "manual", False),
        ("new mode wins over the old flag",
         {"mqtt_discovery": "auto", "enable_mqtt_discovery": "false"}, "auto", True),
        ("no discovery keys at all stays untouched",
         {"conf": {}}, None, False),
    ]
    for label, config, expected, legacy_gone in cases:
        opts = _run_mode_migration(tmp, EDGE, run_text, label, config)
        if opts is None:
            return
        if expected is None:
            check(
                "mqtt_discovery" not in opts,
                f"{EDGE} mode sim '{label}': no mode is invented for a config without any setting",
            )
        else:
            check(
                opts.get("mqtt_discovery") == expected,
                f"{EDGE} mode sim '{label}': mqtt_discovery becomes {expected!r} (got {opts.get('mqtt_discovery')!r})",
            )
        if legacy_gone:
            check(
                "enable_mqtt_discovery" not in opts,
                f"{EDGE} mode sim '{label}': the legacy key is dropped",
            )


def test_panel_dom_ids(tmp):
    """The panel script must only look up elements the template provides: a
    checkbox that was removed while main.js kept listening on it throws at load
    time and takes the whole panel (including Save) down with it."""
    for addon in (EDGE, TEST):
        js = (ROOT / addon / "rootfs/flask/static/main.js").read_text()
        html = (ROOT / addon / "rootfs/flask/templates/index.html").read_text()
        html_ids = set(re.findall(r'id="([^"]+)"', html))
        # created by renderMqtt()/renderSection() at runtime, not in the template
        runtime_ids = {"mqtt_input"}
        looked_up = set(re.findall(r"getElementById\('([^']+)'\)", js))
        missing = sorted(looked_up - html_ids - runtime_ids)
        check(
            not missing,
            f"{addon} main.js only looks up elements of index.html (missing: {missing})",
        )
        check(
            "mqtt-status" not in js and "mqtt-status" not in html,
            f"{addon} panel no longer references the removed discovery checkbox",
        )
        check(
            js.count("{") == js.count("}"),
            f"{addon} main.js has balanced braces",
        )


def test_channels_share_the_manual_pipeline(tmp):
    """weetmuts asked for edge and test at the same time (#2138): the manual
    pipeline and the panel must be the same in both channels, only the default
    mode and the migration differ."""
    for rel in ("mqtt_discovery.sh", "rootfs/flask/templates/index.html",
                "rootfs/flask/static/main.js"):
        edge = (ROOT / EDGE / rel).read_text()
        test = (ROOT / TEST / rel).read_text()
        check(
            edge == test,
            f"{rel} is identical in edge and test",
        )
    edge_templates = sorted(p.name for p in (ROOT / EDGE / "mqtt_discovery").glob("*.json"))
    test_templates = sorted(p.name for p in (ROOT / TEST / "mqtt_discovery").glob("*.json"))
    check(
        edge_templates == test_templates and edge_templates,
        f"edge and test ship the same {len(edge_templates)} discovery templates",
    )
    for addon in (EDGE, TEST):
        html = (ROOT / addon / "rootfs/flask/templates/index.html").read_text()
        check(
            'id="mqtt-discovery"' in html and 'value="manual"' in html and "mqtt-status" not in html,
            f"{addon} panel offers the three-way MQTT discovery option",
        )
        js = (ROOT / addon / "rootfs/flask/static/main.js").read_text()
        check(
            "'mqtt_discovery': mqtt_discovery" in js and "getElementById('mqtt-discovery')" in js,
            f"{addon} panel saves the mqtt_discovery mode",
        )


def test_no_deprecated_bashio_names(tmp):
    # bashio 0.18.0 renamed the addon.* namespace to app.*; the old names are
    # deprecated aliases that log a warning on every call (issue #2131).
    for addon in ADDONS:
        for path in sorted((ROOT / addon).rglob("*.sh")):
            check(
                "bashio::addon." not in path.read_text(),
                f"{addon}/{path.relative_to(ROOT / addon)} does not use the deprecated bashio::addon.* names",
            )
    check(
        "bashio::app.ingress_entry" in (ROOT / TEST / "rootfs/etc/cont-init.d/nginx.sh").read_text(),
        f"{TEST}/rootfs/etc/cont-init.d/nginx.sh uses bashio::app.ingress_entry",
    )


def main():
    tests = [
        test_workflows_parse_and_wiring,
        test_addon_configs,
        test_edge_version_step,
        test_edge_version_step_exact_tag_passthrough,
        test_test_version_step,
        test_test_breaking_notice,
        test_test_update_repo,
        test_push_dispatches_builds,
        test_version_never_reused,
        test_stable_version_step,
        test_dockerhub_matrix,
        test_lint_path,
        test_ci_runs_the_harness,
        test_test_discovery_hook,
        test_data_path_migration,
        test_conf_path_migration,
        test_test_conf_split,
        test_test_discovery_cleanup,
        test_test_discovery_mode,
        lambda tmp: test_test_breaking_notice(f"{tmp}/edge", EDGE, "build_ha_addon_edge.yml"),
        lambda tmp: test_test_discovery_hook(f"{tmp}/edge", EDGE),
        lambda tmp: test_test_conf_split(f"{tmp}/edge", EDGE),
        lambda tmp: test_test_discovery_cleanup(f"{tmp}/edge", EDGE),
        test_edge_discovery_mode,
        test_panel_dom_ids,
        test_channels_share_the_manual_pipeline,
        test_no_deprecated_bashio_names,
    ]
    with tempfile.TemporaryDirectory() as tmp:
        for test in tests:
            try:
                test(tmp)
            except Exception as exc:
                FAILURES.append(f"{test.__name__} raised {exc!r}")
                print(f"FAIL {test.__name__} raised {exc!r}")
    if FAILURES:
        print(f"ERROR! {len(FAILURES)} check(s) failed")
        return 1
    print("OK   all workflow/config checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())