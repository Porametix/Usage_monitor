# Troubleshooting

## Collector cannot find a COM port

Use Device Manager > Ports (COM & LPT) while the board is connected. Close serial monitors and other processes; Windows permits only one active owner for a serial device. Run the demo with the exact COM port, for example COM3. A disconnected port is retried on the next interval.

## ESP32 says waiting or stale

The collector must remain running, the notebook must stay awake, and the selected COM port must belong to the USB cable connected to the ESP32. A received snapshot becomes stale five minutes after the last accepted unique snapshot.

## OpenAI reports unavailable/forbidden

The normal project API key is not sufficient for the organization Usage/Costs endpoints. This adapter requires an organization Admin API key. Check current provider documentation, scope and organization access, then store a key in Windows Credential Manager. A 401/403 is not retried. Never paste a key into an issue or log.

## Display is blank or has wrong colors

Check power and ground first. Verify the exact ESP32 variant, controller marking, pin map, TFT_eSPI setup, and backlight circuit. Try a low SPI clock only after verifying the display controller. The default ILI9341 driver is a documented assumption, not a hardware test result.

## Invalid frame counter increases

Use the shipped collector so the frame has a trailing LF and matches schema version 1. The maximum serialized frame is 4096 bytes. Firmware rejects unknown keys and does not refresh its last-good-data timer for bad frames.
