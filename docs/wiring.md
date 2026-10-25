# Wiring (provisional; not hardware-verified)

Known from the project brief only: 2.8-inch SPI TFT, 240x320, hardware revision V1.2. The ESP32 variant, display controller, voltage regulator/backlight circuit, and touch controller are unknown. This table is a configurable example for a classic ESP32 DevKit using its common SPI pins. Confirm the silkscreen, board datasheet, and module pin labels before applying power. It is not a final wiring sign-off.

| TFT pin | Example ESP32 pin | Notes |
|---|---:|---|
| VCC | 3V3 | Treat the TFT logic as 3.3 V until the module documentation says otherwise. Do not feed 5 V to logic pins. |
| GND | GND | Common ground required. |
| SCK / CLK | GPIO18 | Classic ESP32 VSPI SCLK example. |
| MOSI / SDI | GPIO23 | Classic ESP32 VSPI MOSI example. |
| MISO / SDO | GPIO19 | Connect only if the display exposes/needs MISO. |
| CS | GPIO21 | Configurable; not a classic ESP32 strapping pin. |
| DC / RS | GPIO22 | Configurable. |
| RESET / RST | GPIO4 | Configurable. |
| LED / BL | 3V3 only after checking current and onboard resistor | Backlight drive varies by module. A transistor may be required; do not assume a GPIO can supply it. |
| T_CLK / T_DIN / T_DO / T_CS / T_IRQ | Not connected | Touch is intentionally out of the first milestone. If present, identify its controller before wiring. |

### Controller and board uncertainty

ILI9341 is a plausible/common controller for 240x320 SPI modules, but “2.8 inch / V1.2” alone does not prove it. The project defaults to ILI9341 in platformio.ini for a configurable first build; change the TFT_eSPI driver macro if the chip marking or reliable module documentation shows ST7789 or another controller. XPT2046 touch is not assumed.

GPIO18/19/23 are common SPI pins on the classic ESP32. This mapping does not apply automatically to ESP32-S2/S3/C3/C6 boards. GPIO34-39 on classic ESP32 are input-only and cannot drive CS/DC/reset. Classic ESP32 boot strapping pins include GPIO0, 2, 5, 12, and 15; avoid using them for display control where possible. GPIO21/22 are shared with common I2C defaults; this project does not use I2C. The ESP32 dev board's USB port commonly connects through a USB-UART bridge to Serial/UART0; the exact port and serial implementation depend on board revision.

### Required before final wiring

Read the ESP32 module/board marking and the TFT controller chip marking, confirm whether touch IC is fitted, and check whether the module accepts 3.3 V or includes a regulator/level shifter. Then update the pin map and platformio.ini and test a simple display fill before running the serial dashboard. No hardware inspection or physical test was available during this implementation.
