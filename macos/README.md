# macOS bench bridge

Full guide: **[docs/MACOS.md](../docs/MACOS.md)** · Visuals first: **[docs/GETTING_STARTED.md](../docs/GETTING_STARTED.md)**

```bash
make macos-setup
obd-bridge-mac find-device
obd-bridge-mac start
obd-bridge-mac doctor
```

For gauges without hardware: `make simulate` (Bluetooth is not available inside Docker on Mac).
