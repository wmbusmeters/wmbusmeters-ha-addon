# Version lifecycle

From the upstream tag to the ordered version inside Home Assistant,
decision 0003.

```mermaid
sequenceDiagram
    participant W as wmbusmeters repo<br/>trigger_ha_addon.yml
    participant B as build workflow<br/>(edge/test)
    participant C as config.json + CHANGELOG.md
    participant S as HA supervisor
    participant H as HA core update entity<br/>(awesomeversion)
    W->>B: repository_dispatch, ver = 3.0.0-N
    B->>B: sed -E 's/^([0-9.]+)-([0-9]+)$/\1.\2/'
    B->>C: write 3.0.0.N
    B->>S: build and publish add-on
    S->>H: installed 3.0.0.N vs latest 3.0.0.N
    H->>H: 3.0.0.(N) > 3.0.0.(M) orders correctly
```

Continuous edge builds increment the dotted number on every push to
`main` (`build_ha_addon_on_pr.yml`). Exact tags such as `3.0.0-RC1` are
passed through unchanged. The auto-push commit message keeps the raw
dispatched version; only `config.json` and `CHANGELOG.md` carry the
normalized form. Legacy `3.0.0-N` installs migrate because the first
dotted version orders above every legacy form.