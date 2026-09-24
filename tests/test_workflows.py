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
        (step.get("env") or {}).get("RAW_VER") == "${{ github.event.client_payload.ver }}",
        "edge version step reads RAW_VER from the client payload",
    )
    ws = sandbox(tmp, "edge")
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
        (step.get("env") or {}).get("RAW_VER") == "${{ github.event.client_payload.ver }}",
        "test version step reads RAW_VER from the client payload",
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


def test_on_pr_increment(tmp):
    wf = load_workflow("build_ha_addon_on_pr.yml")
    step = get_step(wf, "prepare", step_id="version")
    if not check(step is not None, "on_pr workflow has an id: version step"):
        return
    cases = [
        ("3.0.0.135", "3.0.0.136"),
        ("3.0.0-134-3", "3.0.0-134-4"),
        ("3.0.0-134", "3.0.0-134-1"),
    ]
    for seed, expected in cases:
        ws = sandbox(tmp, f"onpr_{seed.replace('.', '_')}")
        seed_version(ws / EDGE, seed)
        proc, outputs = run_shell(step["run"], ws)
        check(proc.returncode == 0, f"on_pr increment of {seed} exits 0")
        check(
            outputs.get("version") == expected,
            f"on_pr increments {seed} to {expected} (got {outputs.get('version')!r})",
        )
        check(
            config_version(ws, EDGE) == expected,
            f"on_pr writes {expected} into the edge config",
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


def test_test_discovery_hook(tmp):
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


def main():
    tests = [
        test_workflows_parse_and_wiring,
        test_addon_configs,
        test_edge_version_step,
        test_edge_version_step_exact_tag_passthrough,
        test_test_version_step,
        test_test_update_repo,
        test_on_pr_increment,
        test_stable_version_step,
        test_dockerhub_matrix,
        test_lint_path,
        test_ci_runs_the_harness,
        test_test_discovery_hook,
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