# Discovery pipeline

MQTT discovery generated from the driver sources, decision 0004; the
three modes select which pipeline publishes, decision 0006.

```mermaid
flowchart LR
    M{"mqtt_discovery"}
    M -- "auto" --> MS["meter_shell<br/>(METER_DRIVER env var)"]
    MS --> SH["send_meter_discovery.sh"]
    M -- "manual" --> MD["mqtt_discovery.sh<br/>(run.sh start-up)"]
    T["driver xmq<br/>(to-ha-discovery.xslq)"] -.-> SH
    U["user templates<br/>etc/mqtt_discovery/*.json"] -.-> MD
    SH --> HA["Home Assistant<br/>discovery entities"]
    MD --> HA
    M -- "disable" --> N["nothing published"]
```

The generator is driver driven: no per-driver json is maintained any
more, the hand written templates are only published in the `manual`
mode. Status flag shaping is being negotiated in wmbusmeters#2092;
the former standalone discussion was issue/PR #927.