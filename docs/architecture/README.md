# Architecture views

Each file is one mermaid view of how the add-on plumbing works. The
views show the how; the why lives in
[docs/adr/](../adr/0001-architecture-decision-records.md). `README.md`
stays the canonical source for installation and usage.

| View | File | Shows | Records behind it |
|------|------|-------|-------------------|
| Channel architecture | [channel-architecture.md](channel-architecture.md) | Three channels, workflows, store repos, Docker Hub | 0002 |
| Version lifecycle | [version-lifecycle.md](version-lifecycle.md) | Tag -> dispatch -> normalize -> auto-push -> HA ordering | 0003 |
| Discovery pipeline | [discovery-pipeline.md](discovery-pipeline.md) | telegramdetails -> meter_shell -> xslq -> MQTT | 0004 |