# Discovery pipeline

MQTT discovery generated from the driver sources, decision 0004.

```mermaid
flowchart LR
    T["wmbusmeters<br/>telegram details"] --> MS["meter_shell<br/>(METER_DRIVER env var)"]
    MS --> SH["send_meter_discovery.sh"]
    SH --> X["to-ha-discovery.xslq"]
    X --> J["discovery json<br/>meter names embedded"]
    J -- "retained MQTT, on first telegram" --> HA["Home Assistant<br/>discovery entities"]
    D["driver xmq<br/>(mqtt_discovery templates retired)"] -.-> X
```

The generator is driver driven: no per-driver json is maintained any
more. Status flag shaping is being negotiated in wmbusmeters#2092;
the former standalone discussion was issue/PR #927.