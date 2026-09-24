# Channel architecture

Three sibling add-on directories, their workflows and publish targets,
decision 0002.

```mermaid
flowchart TD
    WM["wmbusmeters/wmbusmeters<br/>.github/workflows/trigger_ha_addon.yml"] -- "repository_dispatch<br/>build_ha_edge / build_ha_test / build_ha_stable" --> E["build_ha_addon_edge.yml"]
    WM --> T["build_ha_addon_test.yml"]
    WM --> S["build_ha_addon_stable.yml"]
    ONPR["build_ha_addon_on_pr.yml<br/>push to main"] --> E
    E --> EDGE["wmbusmeters-ha-addon-edge/"]
    T --> TEST["wmbusmeters-ha-addon-test/"]
    S --> STABLE["wmbusmeters-ha-addon/"]
    EDGE -- "auto-push - [no ci]" --> REPO["this repository<br/>HA store repository"]
    STABLE -- "auto-push - [no ci]" --> REPO
    TEST -- "auto-push - [no ci]" --> REPO
    EDGE --> DH["Docker Hub<br/>image per channel + arch"]
    TEST --> DH
    STABLE --> DH
    LINT["lint.yml"] -- "lints edge only" --> EDGE
    HAR["Tests workflow<br/>(PR #92)"] -.-> E
    HAR -.-> T
    HAR -.-> S
```

The supervisor clones the store repository anonymously; for all three
channels that repository is this one (decision 0002).