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
    retained discovery of the same meter for fields that the driver does not define
    any more (renamed or dropped fields), and leaves other meters alone. A field that
    the driver defines but this telegram does not carry stays: a meter can send
    several telegram formats (wmbusmeters#2161, wmbusmeters#2163)."""
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

    def topic(attribute, component="sensor", meter="04913581"):
        return f"homeassistant/{component}/wmbusmeters/{meter}_{attribute}/config"

    # What "wmbusmeters --listfields=<driver>" prints: the name, then the description.
    fields = [
        "id", "name", "media", "meter", "timestamp", "timestamp_ut", "timestamp_lt",
        "timestamp_utc", "device", "rssi_dbm", "total_m3", "status",
        "current_consumption_hca", "set_date_{storage_counter}",
        "consumption_at_set_date_{storage_counter}_hca", "device_datetime",
    ]
    published = [topic("total_m3"), topic("status", "binary_sensor")]
    cases = [
        # label, listed fields, retained topics, expected cleared
        (
            "stale flag of the old edge",
            fields,
            published + [
                topic("status_LOW_BATTERY", "binary_sensor"),
                topic("total_m3", meter="049135810"),
                topic("status_LOW_BATTERY", "binary_sensor", meter="12345678"),
            ],
            [topic("status_LOW_BATTERY", "binary_sensor")],
        ),
        (
            "another telegram format",
            fields,
            published + [
                topic("current_consumption_hca"),
                topic("consumption_at_set_date_8_hca"),
                topic("set_date_8"),
                topic("status_text"),
                topic("status_low_battery", "binary_sensor"),
            ],
            [],
        ),
        (
            "renamed field",
            fields,
            published + [topic("device_date_time"), topic("total_volume_m3")],
            [topic("device_date_time"), topic("total_volume_m3")],
        ),
        (
            "unknown driver",
            [],
            published + [topic("device_date_time")],
            [],
        ),
    ]
    for label, listed, retained, expected in cases:
        ws = Path(tmp) / f"discovery_cleanup_{TEST}_{label.replace(' ', '_')}"
        ws.mkdir(parents=True)
        helper = ws / "retained.sh"
        helper.write_text(
            "#!/bin/bash\n"
            f'if [ "$1" = list ]; then printf "%s\\n" {" ".join(retained)}; fi\n'
            f'if [ "$1" = clear ]; then echo "$2" >> {ws}/cleared; fi\n'
        )
        helper.chmod(0o755)
        lister = ws / "wmbusmeters"
        lister.write_text(
            "#!/bin/bash\n"
            f'[ "$1" = "--listfields=qcaloric" ] || exit 1\n'
            + "".join(f'printf "%40s  %s\\n" "{f}" "Description of {f}."\n' for f in listed)
        )
        lister.chmod(0o755)
        sim = (
            _hook_log_block(TEST)
            + f"ID=04913581\nNAME=HCA\nDRIVER=qcaloric\nPUBLISHED=' {' '.join(published)}'\n"
            + block.replace("/wmbusmeters/mosquitto_retained.sh", str(helper)).replace(
                "/wmbusmeters/wmbusmeters", str(lister)
            )
        )
        proc = subprocess.run(["bash", "-c", sim], capture_output=True, text=True, timeout=30)
        check(proc.returncode == 0, f"{TEST} discovery cleanup '{label}' exits 0 ({proc.stderr.strip()[:200]})")
        cleared = (ws / "cleared").read_text().split() if (ws / "cleared").exists() else []
        check(
            sorted(cleared) == sorted(expected),
            f"{TEST} discovery cleanup '{label}' removes {expected!r} (got {cleared!r})",
        )
        if label == "unknown driver":
            check(
                "keeping all discovery" in proc.stderr,
                f"{TEST} discovery cleanup '{label}' logs that nothing is removed",
            )


def _hook_log_block(addon):
    """The log_info helper of send_meter_discovery.sh, for simulations of its blocks."""
    text = (ROOT / addon / "send_meter_discovery.sh").read_text()
    return text.split("# BEGIN log", 1)[1].split("# END log", 1)[0]


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
    actually work at runtime: the script, the applied configurations and the
    panel choice."""
    send_text = (ROOT / addon / "send_meter_discovery.sh").read_text()
    run_text = (ROOT / addon / "run.sh").read_text()

    mode_check = send_text.find(".mqtt_discovery // empty")
    check(
        0 < mode_check < send_text.find("PUB=/wmbusmeters/mosquitto_pub.sh"),
        f"{addon}/send_meter_discovery.sh checks the mqtt_discovery mode before publishing",
    )
    mode_block = send_text.find("# BEGIN discovery mode")
    check(
        mode_block > 0 and '!= "auto"' in send_text[mode_block : mode_block + 900],
        f"{addon}/send_meter_discovery.sh publishes the generated discovery in the auto mode only",
    )
    check(
        re.search(r"\.meters\[\]\?.*\.mqtt_discovery", send_text) is not None,
        f"{addon}/send_meter_discovery.sh reads the meter's own mqtt_discovery key",
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
            f"{addon}/run.sh calls mqtt_discovery.sh for the manual mode (add-on setting or a meter)",
        )

    script = (ROOT / addon / "mqtt_discovery.sh").read_text()
    check(
        '!= "manual"' in script and ".mqtt_discovery" in script and "effective_mode" in script,
        f"{addon}/mqtt_discovery.sh publishes only for the meters whose mode is manual",
    )
    check(
        'applied/${aryKV[\'id\']}.json' in script and "/mqtt_discovery/" not in script,
        f"{addon}/mqtt_discovery.sh publishes the configuration applied for the meter, no templates",
    )
    check(
        not (ROOT / addon / "mqtt_discovery").exists(),
        f"{addon} ships no per-driver discovery templates any more",
    )
    dockerfile = (ROOT / addon / "Dockerfile").read_text()
    runtime = dockerfile.split("AS runtime", 1)[1]
    check(
        "COPY mqtt_discovery.sh /" in runtime and "COPY mqtt_discovery/" not in runtime,
        f"{addon}/Dockerfile ships the manual pipeline without templates",
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
    for rel in ("mqtt_discovery.sh", "send_meter_discovery.sh",
                "rootfs/flask/templates/index.html",
                "rootfs/flask/static/main.js",
                "rootfs/flask/app.py",
                "rootfs/flask/discovery_files.py",
                "rootfs/etc/nginx/nginx.conf"):
        edge = (ROOT / EDGE / rel).read_text()
        test = (ROOT / TEST / rel).read_text()
        check(
            edge == test,
            f"{rel} is identical in edge and test",
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


def _marked_block(addon, rel, begin, end):
    """The code of a script between its begin/end markers, or None."""
    text = (ROOT / addon / rel).read_text()
    if not check(
        text.count(begin) == 1 and text.count(end) == 1,
        f"{addon}/{rel} marks {begin!r}",
    ):
        return None
    return text.split(begin, 1)[1].split(end, 1)[0]


def test_meter_mode_is_not_handed_to_wmbusmeters(tmp):
    """A meter's own "mqtt_discovery" key is the add-on's, not wmbusmeters':
    run.sh drops it when it writes the wmbusmeters meter file (wmbusmeters only
    warns about a key it does not know, but the key is not a meter setting)."""
    meters = [
        {"name": "MainWater", "driver": "hydrus", "id": "04913581", "key": "0" * 32},
        {"name": "Gas", "driver": "amiplus", "id": "12345678", "mqtt_discovery": "manual"},
    ]
    for addon in (EDGE, TEST):
        block = _marked_block(addon, "run.sh", "# BEGIN register meters", "# END register meters")
        if block is None:
            return
        ws = Path(tmp) / f"meter_key_{addon.replace('wmbusmeters-ha-addon-', '')}"
        (ws / "data" / "etc" / "wmbusmeters.d").mkdir(parents=True)
        cfg = ws / "data" / "options_custom.json"
        cfg.write_text(json.dumps({"mqtt_discovery": "auto", "meters": meters}, indent=True) + "\n")
        sim = (
            'bashio::log.info() { echo "INFO: $*"; }\n'
            f"CONFIG_PATH={cfg}\n"
            f"CONFIG_DATA_PATH={ws}/data\n"
            + block
        )
        proc = subprocess.run(["bash", "-c", sim], capture_output=True, text=True, timeout=30)
        if not check(proc.returncode == 0, f"{addon} register meters exits 0 ({proc.stderr.strip()[:200]})"):
            continue
        files = sorted((ws / "data" / "etc" / "wmbusmeters.d").glob("meter-*"))
        if not check(len(files) == len(meters), f"{addon} register meters writes one file per meter (got {len(files)})"):
            continue
        written = "\n".join(f.read_text() for f in files)
        check(
            "mqtt_discovery" not in written,
            f"{addon} register meters keeps the add-on key out of the wmbusmeters meter files",
        )
        check(
            "name=MainWater" in written and "driver=amiplus" in written and "driver=hydrus" in written,
            f"{addon} register meters writes the name and driver of every meter",
        )


def test_meter_modes_are_logged(tmp):
    """The start-up log shows the effective mode of every meter: the meters that
    deviate from the add-on setting are listed, the others and unknown values
    are not."""
    for addon in (EDGE, TEST):
        block = _marked_block(addon, "run.sh", "# BEGIN mqtt discovery meters", "# END mqtt discovery meters")
        if block is None:
            return
        ws = Path(tmp) / f"meter_log_{addon.replace('wmbusmeters-ha-addon-', '')}"
        ws.mkdir(parents=True)
        cfg = ws / "options_custom.json"
        cfg.write_text(json.dumps({"mqtt_discovery": "auto", "meters": [
            {"name": "MainWater", "driver": "hydrus", "id": "04913581"},
            {"name": "Gas", "driver": "amiplus", "id": "12345678", "mqtt_discovery": "manual"},
            {"name": "Heat", "driver": "hydrus", "id": "87654321", "mqtt_discovery": "disable"},
            {"name": "Elec", "driver": "amiplus", "id": "11112222", "mqtt_discovery": "Disabled"},
        ]}, indent=True) + "\n")
        sim = (
            'bashio::log.info() { echo "INFO: $*"; }\n'
            "MQTT_DISCOVERY_MODE=auto\n"
            f"CONFIG_PATH={cfg}\n"
            + block
        )
        proc = subprocess.run(["bash", "-c", sim], capture_output=True, text=True, timeout=30)
        if not check(proc.returncode == 0, f"{addon} meter mode log exits 0 ({proc.stderr.strip()[:200]})"):
            continue
        out = proc.stdout.strip()
        check(
            'meter "Gas" uses manual' in out and 'meter "Heat" uses disable' in out,
            f"{addon} logs the meters that deviate from the add-on setting (got {out!r})",
        )
        check(
            "MainWater" not in out and "Elec" not in out,
            f"{addon} does not log meters that use the add-on setting or an unknown mode (got {out!r})",
        )
        check(
            "add-on default: auto" in out,
            f"{addon} names the add-on setting in the per-meter log line (got {out!r})",
        )


def test_manual_pipeline_is_called_for_a_meter(tmp):
    """run.sh starts the manual pipeline when the add-on setting is manual or a
    meter has its own "manual" mode, and leaves it alone otherwise."""
    cases = [
        ("add-on auto, no meter mode", "auto", [{"name": "A"}], False),
        ("add-on auto, one manual meter", "auto", [{"name": "A"}, {"name": "B", "mqtt_discovery": "manual"}], True),
        ("add-on disable, one manual meter", "disable", [{"name": "A", "mqtt_discovery": "manual"}], True),
        ("add-on disable, every meter disabled", "disable", [{"name": "A", "mqtt_discovery": "disable"}], False),
        ("add-on manual, no meter mode", "manual", [{"name": "A"}], True),
        ("add-on manual, meter generates its own", "manual", [{"name": "A", "mqtt_discovery": "auto"}], True),
    ]
    for addon in (EDGE, TEST):
        block = _marked_block(addon, "run.sh", "# BEGIN manual discovery call", "# END manual discovery call")
        if block is None:
            return
        for label, mode, meters, expected in cases:
            ws = Path(tmp) / f"manual_call_{addon.replace('wmbusmeters-ha-addon-', '')}_{label.replace(' ', '_')}"
            (ws / "data").mkdir(parents=True)
            cfg = ws / "options_custom.json"
            cfg.write_text(json.dumps({"mqtt_discovery": mode, "meters": meters}, indent=True) + "\n")
            stub = ws / "mqtt_discovery.sh"
            stub.write_text(f'#!/bin/bash\necho called > {ws}/called\n')
            stub.chmod(0o755)
            sim = (
                f"MQTT_DISCOVERY_MODE={mode}\n"
                f"CONFIG_PATH={cfg}\n"
                f"CONFIG_DATA_PATH={ws}/data\n"
                "pub_args=()\n"
                + block.replace("/mqtt_discovery.sh", str(stub))
            )
            proc = subprocess.run(["bash", "-c", sim], capture_output=True, text=True, timeout=30)
            check(proc.returncode == 0, f"{addon} manual call '{label}' exits 0 ({proc.stderr.strip()[:200]})")
            called = (ws / "called").exists()
            check(
                called == expected,
                f"{addon} manual call '{label}': {'called' if expected else 'not called'} (got {called})",
            )


def test_hook_honours_the_meter_mode(tmp):
    """send_meter_discovery.sh publishes the generated discovery for the meters
    whose mode is auto; the meter's own key wins over the add-on setting and an
    unknown value falls back to it."""
    cases = [
        # label, add-on setting, meter key, expected message, expected source
        ("meter uses the add-on auto", "auto", None, None, None),
        ("meter auto next to an add-on disable", "disable", "auto", None, None),
        ("meter manual", "auto", "manual", "'manual'", "the setting of the meter"),
        ("meter disable", "auto", "disable", "'disable'", "the setting of the meter"),
        ("meter auto wins over an add-on manual", "manual", "auto", None, None),
        ("unknown value falls back to the add-on auto", "auto", "Disabled", None, None),
        ("unknown value falls back to an add-on disable", "disable", "Disabled", "'disable'", "the add-on setting"),
    ]
    for addon in (EDGE, TEST):
        block = _marked_block(addon, "send_meter_discovery.sh", "# BEGIN discovery mode", "# END discovery mode")
        if block is None:
            return
        for label, default, own, message, source in cases:
            ws = Path(tmp) / f"hook_mode_{addon.replace('wmbusmeters-ha-addon-', '')}_{label.replace(' ', '_')}"
            (ws / "data").mkdir(parents=True)
            meter = {"name": "Gas", "driver": "amiplus", "id": "12345678"}
            if own is not None:
                meter["mqtt_discovery"] = own
            cfg = ws / "data" / "options_custom.json"
            cfg.write_text(json.dumps({"mqtt_discovery": default, "meters": [meter]}, indent=True) + "\n")
            sim = (
                _hook_log_block(addon)
                + "NAME=Gas\nID=12345678\n"
                + block.replace("/data/options_custom.json", str(cfg))
            )
            proc = subprocess.run(["bash", "-c", sim], capture_output=True, text=True, timeout=30)
            check(proc.returncode == 0, f"{addon} hook mode '{label}' exits 0 ({proc.stderr.strip()[:200]})")
            if message is None:
                check(
                    "metershell:" not in proc.stderr,
                    f"{addon} hook mode '{label}' publishes without a mode message (got {proc.stderr.strip()!r})",
                )
            else:
                check(
                    message in proc.stderr and source in proc.stderr,
                    f"{addon} hook mode '{label}' logs {message} from {source!r} (got {proc.stderr.strip()!r})",
                )


def _manual_pipeline_case(tmp, addon, label, config, applied, retained):
    """Run the real mqtt_discovery.sh with stubbed broker binaries, the applied
    configuration of some meters (by id) and a fixed list of retained topics."""
    script = (ROOT / addon / "mqtt_discovery.sh").read_text()
    ws = Path(tmp) / f"pipeline_{addon.replace('wmbusmeters-ha-addon-', '')}_{label.replace(' ', '_')}"
    (ws / "data" / "etc").mkdir(parents=True)
    (ws / "discovery" / "applied").mkdir(parents=True)
    for meter_id, body in applied.items():
        (ws / "discovery" / "applied" / f"{meter_id}.json").write_text(json.dumps(body))
    cfg = ws / "options_custom.json"
    cfg.write_text(json.dumps(config, indent=True) + "\n")
    log = ws / "broker.log"
    pub = ws / "mosquitto_pub"
    pub.write_text(f'#!/bin/bash\necho "PUB $*" >> {log}\n')
    sub = ws / "mosquitto_sub"
    sub.write_text("#!/bin/bash\n" + "".join(f'echo "{topic}"\n' for topic in retained))
    for binary in (pub, sub):
        binary.chmod(0o755)
    runner = ws / "mqtt_discovery.sh"
    runner.write_text(
        'bashio::log.info() { echo "INFO: $*"; }\n'
        'bashio::log.warning() { echo "WARN: $*"; }\n'
        'bashio::log.error() { echo "ERROR: $*"; }\n'
        "bashio::services.available() { return 1; }\n"
        "bashio::services() { echo null; }\n"
        + script.replace("/usr/bin/mosquitto_pub", str(pub))
                .replace("/usr/bin/mosquitto_sub", str(sub))
                .replace("-p /dev/shm/", "")
    )
    proc = subprocess.run(
        ["bash", str(runner), "-c", str(cfg), "-w", str(ws / "data")],
        capture_output=True, text=True, timeout=60,
        env=dict(os.environ, WMBUSMETERS_DISCOVERY_DIR=str(ws / "discovery")),
    )
    published, removed = set(), set()
    if log.exists():
        for line in log.read_text().splitlines():
            args = line.split()
            if not args or args[0] != "PUB":
                continue
            topic = args[args.index("-t") + 1]
            (removed if "-n" in args else published).add(topic)
    return proc, published, removed


def test_manual_pipeline_publishes_for_manual_meters_only(tmp):
    """With a per-meter mode the manual pipeline publishes the applied
    configuration of the meters whose mode is manual only, and it removes only
    their retained discovery plus what a meter that is gone left behind: what an
    "auto" meter generates, what a "disable"d meter has and what a manual meter
    without an applied configuration has must survive."""
    template = {
        "total_m3": {
            "component": "sensor",
            "discovery_payload": {
                "name": "{name} total",
                "state_topic": "wmbusmeters/{name}",
                "unique_id": "{id}_total_m3",
            },
        },
    }
    applied = {"12345678": template, "22222222": template}
    cases = [
        (
            "one manual meter next to auto and disable meters",
            {
                "mqtt_discovery": "auto",
                "meters": [
                    {"name": "MainWater", "driver": "hydrus", "id": "04913581"},
                    {"name": "Gas", "driver": "amiplus", "id": "12345678", "mqtt_discovery": "manual"},
                    {"name": "Heat", "driver": "hydrus", "id": "87654321", "mqtt_discovery": "disable"},
                    # manual, but nothing applied yet
                    {"name": "Elec", "driver": "lansen", "id": "11112222", "mqtt_discovery": "manual"},
                ],
            },
            [
                "homeassistant/sensor/wmbusmeters/12345678_total_m3/config",
                "homeassistant/sensor/wmbusmeters/12345678_status_GONE/config",
                "homeassistant/sensor/wmbusmeters/04913581_total_m3/config",
                "homeassistant/sensor/wmbusmeters/87654321_total_m3/config",
                "homeassistant/sensor/wmbusmeters/11112222_total_m3/config",
                # a meter that is not in the configuration any more
                "homeassistant/sensor/wmbusmeters/99999999_total_m3/config",
            ],
            {"homeassistant/sensor/wmbusmeters/12345678_total_m3/config"},
            {
                "homeassistant/sensor/wmbusmeters/12345678_status_GONE/config",
                "homeassistant/sensor/wmbusmeters/99999999_total_m3/config",
            },
            ["Skipping meter MainWater", "Skipping meter Heat", "No discovery applied for meter Elec yet"],
        ),
        (
            "the add-on setting is manual, one meter generates its own",
            {
                "mqtt_discovery": "manual",
                "meters": [
                    {"name": "A", "driver": "hydrus", "id": "11111111", "mqtt_discovery": "auto"},
                    {"name": "B", "driver": "hydrus", "id": "22222222"},
                ],
            },
            [
                "homeassistant/sensor/wmbusmeters/11111111_total_m3/config",
                "homeassistant/sensor/wmbusmeters/22222222_total_m3/config",
                "homeassistant/sensor/wmbusmeters/22222222_status_GONE/config",
            ],
            {"homeassistant/sensor/wmbusmeters/22222222_total_m3/config"},
            {"homeassistant/sensor/wmbusmeters/22222222_status_GONE/config"},
            ["Skipping meter A"],
        ),
    ]
    for addon in (EDGE, TEST):
        for label, config, retained, expected_published, expected_removed, expected_log in cases:
            proc, published, removed = _manual_pipeline_case(tmp, addon, label, config, applied, retained)
            if not check(
                proc.returncode == 0,
                f"{addon} manual pipeline '{label}' exits 0 ({proc.stderr.strip()[:200]})",
            ):
                continue
            check(
                published == expected_published,
                f"{addon} manual pipeline '{label}' publishes for the manual meters only (got {sorted(published)})",
            )
            check(
                removed == expected_removed,
                f"{addon} manual pipeline '{label}' removes only the retained discovery of the manual meters (got {sorted(removed)})",
            )
            for line in expected_log:
                check(
                    line in proc.stdout,
                    f"{addon} manual pipeline '{label}' logs {line!r} (got {proc.stdout.strip()!r})",
                )


def _discovery_files(addon):
    """The real rootfs/flask/discovery_files.py of the add-on, imported."""
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        f"discovery_files_{addon.replace('-', '_')}", ROOT / addon / "rootfs/flask/discovery_files.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_discovery_files(tmp):
    """The manual configuration of a meter: drafts and applied files per meter id,
    validation, the published topics and the preview of an apply."""
    for addon in (EDGE, TEST):
        df = _discovery_files(addon)
        os.environ["WMBUSMETERS_DISCOVERY_DIR"] = str(Path(tmp) / f"files_{addon}")
        try:
            check(df.valid_meter_id("04913581") and not df.valid_meter_id("0491358*")
                  and not df.valid_meter_id("../etc") and not df.valid_meter_id(""),
                  f"{addon} discovery files: only a concrete meter id has files")
            entry = {"component": "sensor",
                     "discovery_payload": {"name": "{name} total", "unique_id": "wmbusmeters_{id}_{attribute}",
                                           "state_topic": "wmbusmeters/{name}", "force_update": True}}
            draft = {"total_m3": entry, "status": {"component": "binary_sensor", "discovery_payload": {"name": "x"}}}
            check(df.validate(draft) == [], f"{addon} discovery files: a generated-style file is valid")
            check(df.validate([]) and df.validate({}) and df.validate({"a b": entry})
                  and df.validate({"x": {"component": "Sensor!", "discovery_payload": {}}})
                  and df.validate({"x": {"component": "sensor", "discovery_payload": "no"}}),
                  f"{addon} discovery files: invalid files are refused")
            df.save("drafts", "04913581", draft)
            check(df.load("drafts", "04913581") == draft and df.load("applied", "04913581") is None,
                  f"{addon} discovery files: drafts and applied files are separate")
            topics = df.topics(draft, "04913581", "Water", "apatorna1")
            payload = json.loads(topics["homeassistant/sensor/wmbusmeters/04913581_total_m3/config"])
            check(payload["unique_id"] == "wmbusmeters_04913581_total_m3" and payload["name"] == "Water total"
                  and payload["force_update"] is True,
                  f"{addon} discovery files: placeholders are replaced, own settings kept ({payload})")
            old = {"total_m3": {"component": "sensor", "discovery_payload": {"name": "old"}},
                   "temp_c": {"component": "sensor", "discovery_payload": {"name": "t"}}}
            retained = [
                "homeassistant/sensor/wmbusmeters/04913581_total_m3/config",
                "homeassistant/sensor/wmbusmeters/04913581_temp_c/config",
                "homeassistant/sensor/wmbusmeters/049135810_total_m3/config",
                "homeassistant/sensor/wmbusmeters/12345678_temp_c/config",
            ]
            pv = df.preview(draft, old, retained, "04913581", "Water", "apatorna1")
            check(pv == {"added": ["homeassistant/binary_sensor/wmbusmeters/04913581_status/config"],
                         "changed": ["homeassistant/sensor/wmbusmeters/04913581_total_m3/config"],
                         "unchanged": [],
                         "removed": ["homeassistant/sensor/wmbusmeters/04913581_temp_c/config"]},
                  f"{addon} discovery files: the preview lists added, changed and removed of this meter only ({pv})")
            cfg = {"meters": [{"name": "Water", "id": "04913581", "driver": "apatorna1:t1"}]}
            meter = df.find_meter(cfg, "04913581")
            check(meter is not None and df.driver_name(meter) == "apatorna1" and df.find_meter(cfg, "1") is None,
                  f"{addon} discovery files: the meter and its driver are found by id")
        finally:
            del os.environ["WMBUSMETERS_DISCOVERY_DIR"]


def test_discovery_cache(tmp):
    """send_meter_discovery.sh keeps the generated discovery of every meter, in
    every mode, before it looks at the mode: the panel makes a draft from it."""
    for addon in (EDGE, TEST):
        send_text = (ROOT / addon / "send_meter_discovery.sh").read_text()
        if not check(
            send_text.count("# BEGIN discovery cache") == 1 and send_text.count("# END discovery cache") == 1,
            f"{addon}/send_meter_discovery.sh marks the discovery cache block",
        ):
            continue
        check(
            send_text.index("# END discovery cache") < send_text.index("# BEGIN discovery mode"),
            f"{addon}/send_meter_discovery.sh keeps the generated discovery before the mode check",
        )
        block = send_text.split("# BEGIN discovery cache", 1)[1].split("# END discovery cache", 1)[0]
        for label, meter_id, kept in (("meter id", "04913581", True), ("wildcard", "0491*", False)):
            ws = Path(tmp) / f"cache_{addon}_{label.replace(' ', '_')}"
            ws.mkdir(parents=True)
            disc = ws / "discovery.json"
            disc.write_text('{"total_m3": {"component": "sensor", "discovery_payload": {}}}\n')
            sim = f"ID='{meter_id}'\nDISCOVERY_FILE={disc}\nWMBUSMETERS_DISCOVERY_DIR={ws}/d\n{block}\n"
            proc = subprocess.run(["bash", "-c", sim], capture_output=True, text=True, timeout=30)
            check(proc.returncode == 0, f"{addon} discovery cache '{label}' exits 0 ({proc.stderr.strip()[:200]})")
            target = ws / "d" / "generated" / f"{meter_id}.json"
            check(target.exists() == kept and (not kept or json.loads(target.read_text()) == json.loads(disc.read_text())),
                  f"{addon} discovery cache '{label}': {'kept' if kept else 'no file'}")
            if not kept:
                continue
            # A restart and another telegram format: the kept entities stay, a
            # generated-again attribute replaces the old one.
            disc.write_text('{"set_date_8": {"component": "sensor", "discovery_payload": {}},'
                            ' "total_m3": {"component": "sensor", "discovery_payload": {"new": 1}}}\n')
            proc = subprocess.run(["bash", "-c", sim], capture_output=True, text=True, timeout=30)
            merged = json.loads(target.read_text())
            check(sorted(merged) == ["set_date_8", "total_m3"] and merged["total_m3"]["discovery_payload"] == {"new": 1},
                  f"{addon} discovery cache merges another format and replaces what is generated again ({merged})")


def test_batch_helper(tmp):
    """run.sh writes mosquitto_batch.sh, which the panel uses to publish a manual
    configuration in one start: every "<topic><TAB><payload>" line published
    retained, every topic of a clear file removed; a failure stops the publish."""
    for addon in (EDGE, TEST):
        run_text = (ROOT / addon / "run.sh").read_text()
        start = run_text.find("    cat > /wmbusmeters/mosquitto_batch.sh << EOL\n")
        if not check(start > 0, f"{addon}/run.sh writes the batch helper"):
            continue
        end = run_text.index("\nEOL\n", start) + len("\nEOL\n")
        ws = Path(tmp) / f"batch_{addon}"
        ws.mkdir(parents=True)
        log = ws / "pub.log"
        pub = ws / "mosquitto_pub"
        pub.write_text(f'#!/bin/bash\nprintf "%s|" "$@" >> {log}; echo >> {log}\n'
                       'for a in "$@"; do [ "$a" = "fail/topic" ] && exit 3; done\nexit 0\n')
        pub.chmod(0o755)
        helper = ws / "mosquitto_batch.sh"
        gen = (
            "pub_args_quoted=('-h' \"'core-mosquitto'\" '-u' \"'user'\")\n"
            + run_text[start:end].replace("/wmbusmeters/mosquitto_batch.sh", str(helper))
        )
        proc = subprocess.run(["bash", "-c", gen], capture_output=True, text=True, timeout=30)
        check(proc.returncode == 0 and helper.exists(), f"{addon} batch helper is generated ({proc.stderr.strip()[:200]})")
        body = helper.read_text().replace("#!/usr/bin/with-contenv bashio", "#!/bin/bash").replace("/usr/bin/mosquitto_pub", str(pub))
        helper.write_text(body)
        helper.chmod(0o755)
        payload = '{"name":"Water total","unique_id":"wmbusmeters_04913581_total_m3"}'
        (ws / "pub.txt").write_text(f"homeassistant/sensor/wmbusmeters/04913581_total_m3/config\t{payload}\n"
                                    "homeassistant/sensor/wmbusmeters/04913581_x/config\t{\"a b\":1}\n")
        proc = subprocess.run([str(helper), "publish", str(ws / "pub.txt")], capture_output=True, text=True, timeout=30)
        lines = log.read_text().splitlines() if log.exists() else []
        check(proc.returncode == 0 and len(lines) == 2
              and lines[0] == f"-h|core-mosquitto|-u|user|-r|-t|homeassistant/sensor/wmbusmeters/04913581_total_m3/config|-m|{payload}|"
              and lines[1].endswith('-m|{"a b":1}|'),
              f"{addon} batch helper publishes every line retained, payloads intact (got {lines})")
        log.unlink()
        (ws / "clear.txt").write_text("homeassistant/sensor/wmbusmeters/04913581_old/config\n")
        proc = subprocess.run([str(helper), "clear", str(ws / "clear.txt")], capture_output=True, text=True, timeout=30)
        lines = log.read_text().splitlines() if log.exists() else []
        check(lines == ["-h|core-mosquitto|-u|user|-r|-t|homeassistant/sensor/wmbusmeters/04913581_old/config|-n|"],
              f"{addon} batch helper clears every listed topic (got {lines})")
        log.unlink()
        (ws / "fail.txt").write_text("fail/topic\tx\nnext/topic\ty\n")
        proc = subprocess.run([str(helper), "publish", str(ws / "fail.txt")], capture_output=True, text=True, timeout=30)
        lines = log.read_text().splitlines() if log.exists() else []
        check(proc.returncode != 0 and len(lines) == 1, f"{addon} batch helper stops at the first failed publish")


def test_panel_manual_discovery(tmp):
    """The panel offers generate/download/upload/apply under every meter, the
    back end has the matching routes and ingress rewrites their paths."""
    for addon in (EDGE, TEST):
        js = (ROOT / addon / "rootfs/flask/static/main.js").read_text()
        app = (ROOT / addon / "rootfs/flask/app.py").read_text()
        nginx = (ROOT / addon / "rootfs/etc/nginx/nginx.conf").read_text()
        html = (ROOT / addon / "rootfs/flask/templates/index.html").read_text()
        for cls in ("discovery-generate", "discovery-download", "discovery-upload", "discovery-apply"):
            check(cls in js, f"{addon} panel has the {cls} button")
        for route in ("/status')", "/generate'", "/file')", "/draft'", "/preview')", "/apply'"):
            check(f"@app.route('/discovery_api/<meter_id>{route}" in app, f"{addon} app.py serves /discovery_api/<id>{route}")
        check('sub_filter "/discovery_api/" "$http_x_ingress_path/discovery_api/";' in nginx,
              f"{addon} ingress rewrites the /discovery_api/ paths")
        check("import discovery_files" in app, f"{addon} app.py uses discovery_files.py")
        for what in ("generated:", "uploaded:", "refused:", "applied:", "failed, nothing changed", "uses the manual MQTT discovery mode now"):
            check(what in app, f"{addon} app.py logs the panel action '{what}'")
        check("def panel_log" in app and "flush=True" in app.split("def panel_log", 1)[1][:400],
              f"{addon} app.py writes the panel lines to the add-on log at once")
        check("function showBusy" in js and "spinner-border" in js and js.count("showBusy(") >= 6,
              f"{addon} panel shows a busy indicator for every discovery action")
        check("function showConfirm" in js and re.search(r"(?<![A-Za-z.])confirm\(", js) is None,
              f"{addon} panel asks in its own style, not with the browser's confirm()")
        check("MQTT_BATCH, 'publish'" in app and "MQTT_BATCH, 'clear'" in app,
              f"{addon} apply publishes and removes with one start of the batch helper")
        check("templates in etc/mqtt_discovery" not in js + html,
              f"{addon} panel no longer mentions the templates")
        apply_src = app.split("def discovery_apply", 1)[1]
        check(apply_src.index("MQTT_BATCH, 'publish'") < apply_src.index("MQTT_BATCH, 'clear'")
              < apply_src.index("save('applied'"),
              f"{addon} apply publishes first, then removes, then stores the applied configuration")


def test_panel_offers_the_meter_mode(tmp):
    """Every meter row of the panel has its own MQTT discovery choice; the
    "Default" choice keeps the meter key out of the saved configuration."""
    for addon in (EDGE, TEST):
        js = (ROOT / addon / "rootfs/flask/static/main.js").read_text()
        check(
            "renderDiscoverySelect" in js and "meter-discovery" in js,
            f"{addon} panel renders a per-meter MQTT discovery choice",
        )
        check(
            "sectionData['mqtt_discovery'] = sectionMode.value" in js,
            f"{addon} panel saves the per-meter mode",
        )
        check(
            "delete sectionData['mqtt_discovery']" in js,
            f"{addon} panel drops the meter key when the choice is 'Default'",
        )
        check(
            "keys[i] === 'mqtt_discovery'" in js,
            f"{addon} panel shows the meter mode once, not as a key/value pair",
        )
        check(
            "dataForParse[key][i].mqtt_discovery || ''" in js,
            f"{addon} panel shows the saved per-meter mode",
        )
        row = js.split('class="meter-discovery-row', 1)[-1].split("</div>", 1)[0]
        check(
            "MQTT discovery for this meter" in row and "json-pair" not in row
            and "section-key" not in row and "delete-pair" not in row,
            f"{addon} panel shows the meter mode as a row aligned with the meter fields, not saved as a pair",
        )
        check(
            "Add-on default (${" in js and "addEventListener('change', updateMeterDefaultLabels)" in js,
            f"{addon} panel names the add-on mode in the meter's default choice and follows its changes",
        )
        check(
            "orderMeterKeys(Object.keys(" in js and "['name', 'driver', 'id', 'key']" in js,
            f"{addon} panel shows a saved meter in the order of a new one",
        )
        html = (ROOT / addon / "rootfs/flask/templates/index.html").read_text()
        check(
            "MQTT discovery (default for all meters)" in html,
            f"{addon} panel says that the add-on mode is the default of every meter",
        )
        docs = (ROOT / addon / "DOCS.md").read_text()
        check(
            "Every meter can choose its own mode" in docs and "Add-on default" in docs,
            f"{addon}/DOCS.md documents the per-meter MQTT discovery mode",
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


def test_hook_log_lines(tmp):
    """The lines of send_meter_discovery.sh look like the add-on's own log
    (time stamp, INFO, green) and name every topic it publishes."""
    for addon in (EDGE, TEST):
        send_text = (ROOT / addon / "send_meter_discovery.sh").read_text()
        check(
            'echo "metershell:' not in send_text and send_text.count("# BEGIN log") == 1,
            f"{addon}/send_meter_discovery.sh logs every line through log_info",
        )
        check(
            'log_info "  Add/update topic: $topic"' in send_text,
            f"{addon}/send_meter_discovery.sh logs every topic it publishes",
        )
        proc = subprocess.run(
            ["bash", "-c", _hook_log_block(addon) + 'log_info "metershell: hello"'],
            capture_output=True, text=True, timeout=30,
        )
        check(
            re.fullmatch(r"\x1b\[32m\[\d\d:\d\d:\d\d\] INFO: metershell: hello\x1b\[0m\n", proc.stderr) is not None,
            f"{addon} log_info prints a green, time stamped INFO line (got {proc.stderr!r})",
        )


def test_panel_meter_cards(tmp):
    """Every meter is a card with its name in the title, and the first column of
    a meter has one width, so the "=" of every row is in the same place."""
    for addon in (EDGE, TEST):
        js = (ROOT / addon / "rootfs/flask/static/main.js").read_text()
        html = (ROOT / addon / "rootfs/flask/templates/index.html").read_text()
        check(
            '<div class="meter-title"></div>' in js and "updateMeterTitle(newSection)" in js
            and "document.addEventListener('input'" in js,
            f"{addon} panel gives every meter a title that follows its name",
        )
        check(
            ".json-section {" in html and ".json-section .input-group > :first-child" in html,
            f"{addon} panel draws every meter as a card with one width for the name column",
        )
        check(
            '<fieldset class="meter-discovery-tools">' in js and "<legend>Manual MQTT discovery (Home Assistant entities)</legend>" in js
            and ".meter-discovery-tools legend" in html,
            f"{addon} panel frames the draft buttons as the manual MQTT discovery of the meter",
        )
        check(
            html.count('class="mqtt-label input-group-text"') == 2 and ".mqtt-label {" in html,
            f"{addon} panel gives both MQTT rows one label width",
        )


def test_telegramdetails_migration(tmp):
    """wmbusmeters master renamed addtelegramdetails=first to onchange.
    [edge] and [test] are built from master: their defaults use onchange and
    a saved "first" becomes "onchange" once at start. The stable add-on is
    built from a release that does not know onchange yet and keeps first."""
    for addon in (EDGE, TEST):
        run_text = (ROOT / addon / "run.sh").read_text()
        defaults = [
            json.loads(m)
            for m in re.findall(r"^    echo '(\{.*\})' \| jq \. > \$\{CONFIG_PATH\}$", run_text, re.M)
        ]
        check(
            len(defaults) == 2 and all(c["conf"].get("addtelegramdetails") == "onchange" for c in defaults),
            f"{addon}/run.sh default configs use addtelegramdetails=onchange",
        )
        block = _marked_block(addon, "run.sh", "# BEGIN addtelegramdetails migration", "# END addtelegramdetails migration")
        if block is None:
            continue
        cases = [
            ("first", "onchange", True),
            ("onchange", "onchange", False),
            ("never", "never", False),
            (None, None, False),
        ]
        for before, after, logged in cases:
            label = f"{addon.replace('wmbusmeters-ha-addon-', '')}_{before}"
            ws = Path(tmp) / f"telegramdetails_{label}"
            ws.mkdir(parents=True)
            cfg = ws / "options_custom.json"
            conf = {"loglevel": "normal"}
            if before is not None:
                conf["addtelegramdetails"] = before
            cfg.write_text(json.dumps({"conf": conf, "meters": []}) + "\n")
            sim = 'bashio::log.info() { echo "INFO: $*"; }\n' f"CONFIG_PATH={cfg}\n" + block
            proc = subprocess.run(["bash", "-c", sim], capture_output=True, text=True, timeout=30)
            got = json.loads(cfg.read_text())
            check(
                proc.returncode == 0 and got["conf"].get("addtelegramdetails") == after
                and got["conf"]["loglevel"] == "normal",
                f"{addon} addtelegramdetails {before!r} becomes {after!r}, the rest is kept",
            )
            check(
                ("Renaming addtelegramdetails" in proc.stdout) == logged,
                f"{addon} addtelegramdetails {before!r}: migration {'is' if logged else 'is not'} logged",
            )
    stable = (ROOT / STABLE / "run.sh").read_text()
    check(
        '"addtelegramdetails":"first"' in stable and "addtelegramdetails migration" not in stable,
        f"{STABLE}/run.sh keeps addtelegramdetails=first for the released wmbusmeters",
    )


def test_test_debug_build_ships_libasan(tmp):
    """A DEBUG build of wmbusmeters is linked against libasan.so.8. The runtime
    stage has no gcc, so the library must be copied from the build stage, or
    wmbusmeters exits with 127 ("Error loading shared library libasan.so.8")."""
    dockerfile = (ROOT / TEST / "Dockerfile").read_text()
    build, runtime = dockerfile.split("AS runtime", 1)
    if "DEBUG=true" not in build:
        check(True, f"{TEST}/Dockerfile builds no DEBUG wmbusmeters")
        return
    check(
        re.search(r"^COPY --from=build /usr/lib/libasan\.so\.8\S* /usr/lib/$", runtime, re.M) is not None,
        f"{TEST}/Dockerfile copies libasan.so.8 into the runtime image for the DEBUG build",
    )


def main():
    tests = [
        test_test_debug_build_ships_libasan,
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
        test_discovery_files,
        test_discovery_cache,
        test_panel_manual_discovery,
        test_batch_helper,
        test_test_discovery_mode,
        lambda tmp: test_test_breaking_notice(f"{tmp}/edge", EDGE, "build_ha_addon_edge.yml"),
        lambda tmp: test_test_discovery_hook(f"{tmp}/edge", EDGE),
        lambda tmp: test_test_conf_split(f"{tmp}/edge", EDGE),
        lambda tmp: test_test_discovery_cleanup(f"{tmp}/edge", EDGE),
        test_edge_discovery_mode,
        test_panel_dom_ids,
        test_channels_share_the_manual_pipeline,
        test_meter_mode_is_not_handed_to_wmbusmeters,
        test_meter_modes_are_logged,
        test_manual_pipeline_is_called_for_a_meter,
        test_hook_honours_the_meter_mode,
        test_manual_pipeline_publishes_for_manual_meters_only,
        test_panel_offers_the_meter_mode,
        test_no_deprecated_bashio_names,
        test_telegramdetails_migration,
        test_hook_log_lines,
        test_panel_meter_cards,
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