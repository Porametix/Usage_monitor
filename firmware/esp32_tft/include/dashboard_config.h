#pragma once

#define SERIAL_BAUD 115200
#define MAX_FRAME_BYTES 4096
#define MAX_PROVIDERS 16
#define STALE_AFTER_MS 300000UL
#define PAGE_ROTATE_MS 12000UL
#define FRAME_DOC_CAPACITY 8192

// Classic ESP32 DevKit example pins. Confirm the exact module before wiring.
#define TFT_PIN_SCLK 18
#define TFT_PIN_MISO 19
#define TFT_PIN_MOSI 23
#define TFT_PIN_CS 21
#define TFT_PIN_DC 22
#define TFT_PIN_RST 4
