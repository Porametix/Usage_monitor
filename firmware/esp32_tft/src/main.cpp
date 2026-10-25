#include <Arduino.h>
#include <SPI.h>
#include <TFT_eSPI.h>
#include <ArduinoJson.h>
#include <math.h>
#include <string.h>

#include "dashboard_config.h"

TFT_eSPI tft = TFT_eSPI();
StaticJsonDocument<FRAME_DOC_CAPACITY> frameDoc;
char rxBuffer[MAX_FRAME_BYTES + 1];
size_t rxLength = 0;
bool discardingFrame = false;
bool hasSnapshot = false;
bool stale = true;
uint64_t lastSnapshotId = 0;
uint32_t lastReceivedMs = 0;
uint32_t lastPageChangeMs = 0;
uint32_t lastDrawMs = 0;
uint32_t invalidFrames = 0;
uint8_t currentPage = 0;

const char *const PAGE_NAMES[] = {"OVERVIEW", "SUBSCRIPTIONS", "API DETAILS"};

bool validUtf8(const uint8_t *data, size_t length) {
  size_t i = 0;
  while (i < length) {
    uint8_t a = data[i];
    if (a == 0) return false;
    if (a <= 0x7F) { ++i; continue; }
    if (a >= 0xC2 && a <= 0xDF) {
      if (i + 1 >= length || (data[i + 1] & 0xC0) != 0x80) return false;
      i += 2; continue;
    }
    if (a >= 0xE0 && a <= 0xEF) {
      if (i + 2 >= length) return false;
      uint8_t b = data[i + 1], c = data[i + 2];
      if ((b & 0xC0) != 0x80 || (c & 0xC0) != 0x80) return false;
      if (a == 0xE0 && b < 0xA0) return false;
      if (a == 0xED && b >= 0xA0) return false;
      i += 3; continue;
    }
    if (a >= 0xF0 && a <= 0xF4) {
      if (i + 3 >= length) return false;
      uint8_t b = data[i + 1], c = data[i + 2], d = data[i + 3];
      if ((b & 0xC0) != 0x80 || (c & 0xC0) != 0x80 || (d & 0xC0) != 0x80) return false;
      if (a == 0xF0 && b < 0x90) return false;
      if (a == 0xF4 && b >= 0x90) return false;
      i += 4; continue;
    }
    return false;
  }
  return true;
}

bool isOneOf(const char *value, const char *const *choices, size_t count) {
  if (value == nullptr) return false;
  for (size_t i = 0; i < count; ++i) if (strcmp(value, choices[i]) == 0) return true;
  return false;
}

bool exactKeys(JsonObjectConst object, const char *const *allowed, size_t allowedCount) {
  for (JsonPairConst pair : object) {
    bool found = false;
    for (size_t i = 0; i < allowedCount; ++i) {
      if (strcmp(pair.key().c_str(), allowed[i]) == 0) { found = true; break; }
    }
    if (!found) return false;
  }
  return true;
}

bool hasKeys(JsonObjectConst object, const char *const *required, size_t requiredCount) {
  for (size_t i = 0; i < requiredCount; ++i) if (!object.containsKey(required[i])) return false;
  return true;
}

bool stringValue(JsonVariantConst value, size_t maxLength, const char **out = nullptr) {
  if (!value.is<const char *>()) return false;
  JsonString jsonText = value.as<JsonString>();
  const char *text = jsonText.c_str();
  size_t length = jsonText.size();
  if (text == nullptr || length == 0 || length > maxLength) return false;
  for (size_t i = 0; i < length; ++i) if (static_cast<uint8_t>(text[i]) < 0x20) return false;
  if (out != nullptr) *out = text;
  return true;
}

bool validTimestamp(JsonVariantConst value) {
  const char *text = nullptr;
  if (!stringValue(value, 40, &text)) return false;
  size_t n = strlen(text);
  if (n < 20 || text[4] != '-' || text[7] != '-' || text[10] != 'T' || text[13] != ':' || text[16] != ':') return false;
  if (text[n - 1] == 'Z') return true;
  return n >= 25 && (text[n - 6] == '+' || text[n - 6] == '-') && text[n - 3] == ':';
}

bool optionalUInt(JsonVariantConst value, uint64_t *out = nullptr) {
  if (value.isNull()) return true;
  if (value.is<bool>() || !value.is<uint64_t>()) return false;
  uint64_t number = value.as<uint64_t>();
  if (number > 9007199254740991ULL) return false;
  if (out != nullptr) *out = number;
  return true;
}

bool optionalNumber(JsonVariantConst value, double minimum, double maximum, double *out = nullptr) {
  if (value.isNull()) return true;
  if (value.is<bool>() || (!value.is<double>() && !value.is<int64_t>() && !value.is<uint64_t>())) return false;
  double number = value.as<double>();
  if (!isfinite(number) || number < minimum || number > maximum) return false;
  if (out != nullptr) *out = number;
  return true;
}

bool validProvider(JsonObjectConst p, JsonArrayConst previous, size_t index) {
  static const char *const allowed[] = {"id", "name", "status", "source", "input_tokens", "output_tokens", "total_tokens", "actual_cost_usd", "estimated_cost_usd", "budget_usd", "quota_remaining_percent", "last_updated", "reset_at", "message"};
  static const char *const required[] = {"id", "name", "status", "source", "last_updated"};
  static const char *const statuses[] = {"ok", "unsupported", "manual", "unavailable", "error", "stale"};
  static const char *const sources[] = {"provider_reported", "locally_tracked", "estimated", "manual", "demo"};
  const char *id = nullptr, *name = nullptr, *status = nullptr, *source = nullptr;
  if (!exactKeys(p, allowed, sizeof(allowed) / sizeof(allowed[0])) || !hasKeys(p, required, sizeof(required) / sizeof(required[0]))) return false;
  if (!stringValue(p["id"], 32, &id) || !stringValue(p["name"], 32, &name)) return false;
  for (const char *c = id; *c; ++c) if (!( (*c >= 'a' && *c <= 'z') || (*c >= '0' && *c <= '9') || *c == '_' )) return false;
  if (!stringValue(p["status"], 16, &status) || !isOneOf(status, statuses, sizeof(statuses) / sizeof(statuses[0]))) return false;
  if (!stringValue(p["source"], 24, &source) || !isOneOf(source, sources, sizeof(sources) / sizeof(sources[0]))) return false;
  if (!validTimestamp(p["last_updated"])) return false;
  if (p.containsKey("reset_at") && !p["reset_at"].isNull() && !validTimestamp(p["reset_at"])) return false;
  if (p.containsKey("message") && !p["message"].isNull() && !stringValue(p["message"], 120)) return false;
  if (!optionalUInt(p["input_tokens"]) || !optionalUInt(p["output_tokens"]) || !optionalUInt(p["total_tokens"])) return false;
  if (!optionalNumber(p["actual_cost_usd"], 0, 1000000000.0) || !optionalNumber(p["estimated_cost_usd"], 0, 1000000000.0) || !optionalNumber(p["budget_usd"], 0, 1000000000.0) || !optionalNumber(p["quota_remaining_percent"], 0, 100)) return false;
  uint64_t input = 0, output = 0, total = 0;
  bool hasInput = p.containsKey("input_tokens") && !p["input_tokens"].isNull();
  bool hasOutput = p.containsKey("output_tokens") && !p["output_tokens"].isNull();
  bool hasTotal = p.containsKey("total_tokens") && !p["total_tokens"].isNull();
  if (hasInput) input = p["input_tokens"].as<uint64_t>();
  if (hasOutput) output = p["output_tokens"].as<uint64_t>();
  if (hasTotal) total = p["total_tokens"].as<uint64_t>();
  if (hasInput && hasOutput && hasTotal && total != input + output) return false;
  for (size_t i = 0; i < index; ++i) {
    const char *previousId = previous[i]["id"].as<const char *>();
    if (previousId != nullptr && strcmp(previousId, id) == 0) return false;
  }
  return true;
}

bool validateSnapshot(char *frame, size_t length, uint64_t *snapshotId) {
  if (length == 0 || length > MAX_FRAME_BYTES || !validUtf8(reinterpret_cast<uint8_t *>(frame), length)) return false;
  frame[length] = '\0';
  frameDoc.clear();
  DeserializationError error = deserializeJson(frameDoc, frame, length, DeserializationOption::NestingLimit(6));
  if (error || !frameDoc.is<JsonObject>()) return false;
  JsonObjectConst root = frameDoc.as<JsonObjectConst>();
  static const char *const topAllowed[] = {"schema_version", "type", "snapshot_id", "generated_at", "budget_usd", "providers"};
  static const char *const topRequired[] = {"schema_version", "type", "snapshot_id", "generated_at", "providers"};
  if (!exactKeys(root, topAllowed, sizeof(topAllowed) / sizeof(topAllowed[0])) || !hasKeys(root, topRequired, sizeof(topRequired) / sizeof(topRequired[0]))) return false;
  if (root["schema_version"].is<bool>() || !root["schema_version"].is<int>() || root["schema_version"].as<int>() != 1) return false;
  const char *type = nullptr;
  if (!stringValue(root["type"], 24, &type) || strcmp(type, "usage_snapshot") != 0) return false;
  if (!optionalUInt(root["snapshot_id"], snapshotId) || !validTimestamp(root["generated_at"])) return false;
  if (root.containsKey("budget_usd") && !optionalNumber(root["budget_usd"], 0, 1000000000.0)) return false;
  JsonArrayConst providers = root["providers"].as<JsonArrayConst>();
  if (!root["providers"].is<JsonArray>() || providers.size() > MAX_PROVIDERS) return false;
  for (size_t i = 0; i < providers.size(); ++i) {
    JsonObjectConst item = providers[i].as<JsonObjectConst>();
    if (!providers[i].is<JsonObject>() || !validProvider(item, providers, i)) return false;
  }
  return true;
}

String formatUInt64(uint64_t value) {
  char buffer[24];
  snprintf(buffer, sizeof(buffer), "%llu", static_cast<unsigned long long>(value));
  return String(buffer);
}

String metric(uint64_t value, bool present) {
  return present ? formatUInt64(value) : String("--");
}

String moneyValue(double value) {
  char buffer[24];
  snprintf(buffer, sizeof(buffer), "$%.2f", value);
  return String(buffer);
}

String money(JsonVariantConst value) {
  return value.isNull() ? String("--") : moneyValue(value.as<double>());
}

String statusText(JsonObjectConst provider) {
  const char *status = provider["status"] | "unavailable";
  if (strcmp(status, "ok") == 0 && strcmp(provider["source"] | "", "demo") == 0) return "DEMO";
  if (strcmp(status, "ok") == 0) return "OK";
  if (strcmp(status, "unsupported") == 0) return "UNSUPPORTED";
  if (strcmp(status, "manual") == 0) return "MANUAL";
  if (strcmp(status, "stale") == 0) return "STALE";
  if (strcmp(status, "error") == 0) return "ERROR";
  return "UNAVAILABLE";
}

uint64_t sumMetric(const char *key) {
  uint64_t sum = 0;
  JsonArrayConst providers = frameDoc["providers"].as<JsonArrayConst>();
  for (JsonObjectConst p : providers) {
    if (strcmp(p["status"] | "", "ok") != 0 || p[key].isNull()) continue;
    sum += p[key].as<uint64_t>();
  }
  return sum;
}

uint64_t sumTotalTokens() {
  uint64_t total = 0;
  for (JsonObjectConst p : frameDoc["providers"].as<JsonArrayConst>()) {
    if (strcmp(p["status"] | "", "ok") != 0) continue;
    if (!p["total_tokens"].isNull()) total += p["total_tokens"].as<uint64_t>();
    else total += (p["input_tokens"].isNull() ? 0 : p["input_tokens"].as<uint64_t>()) + (p["output_tokens"].isNull() ? 0 : p["output_tokens"].as<uint64_t>());
  }
  return total;
}

uint8_t countHealthy() {
  uint8_t total = 0;
  for (JsonObjectConst p : frameDoc["providers"].as<JsonArrayConst>()) if (strcmp(p["status"] | "", "ok") == 0) ++total;
  return total;
}

void header(const char *title) {
  tft.fillScreen(TFT_BLACK);
  tft.fillRect(0, 0, 240, 34, TFT_NAVY);
  tft.setTextColor(TFT_WHITE, TFT_NAVY);
  tft.drawString(title, 8, 9, 2);
  tft.setTextColor(TFT_CYAN, TFT_NAVY);
  tft.drawRightString("USB", 231, 10, 2);
  tft.drawFastHLine(0, 34, 240, TFT_DARKGREY);
}

void labelValue(const char *label, const String &value, int y, uint16_t color = TFT_WHITE) {
  tft.setTextColor(TFT_LIGHTGREY, TFT_BLACK);
  tft.drawString(label, 10, y, 2);
  tft.setTextColor(color, TFT_BLACK);
  tft.drawRightString(value, 230, y, 2);
}

void drawWaiting() {
  tft.fillScreen(TFT_BLACK);
  tft.fillRect(0, 0, 240, 36, TFT_NAVY);
  tft.setTextColor(TFT_WHITE, TFT_NAVY);
  tft.drawCentreString("USAGE MONITOR", 120, 10, 2);
  tft.setTextColor(TFT_YELLOW, TFT_BLACK);
  tft.drawCentreString("WAITING FOR NOTEBOOK", 120, 104, 2);
  tft.setTextColor(TFT_LIGHTGREY, TFT_BLACK);
  tft.drawCentreString("USB SERIAL ONLY", 120, 138, 2);
  tft.drawCentreString("No provider keys stored", 120, 168, 1);
  tft.drawCentreString("Pages rotate automatically", 120, 194, 1);
  tft.setTextColor(TFT_DARKGREY, TFT_BLACK);
  tft.drawCentreString("Check COM port and cable", 120, 285, 1);
}

void drawOverview() {
  header("OVERVIEW");
  uint32_t ageSeconds = (millis() - lastReceivedMs) / 1000;
  labelValue("Collector", stale ? "STALE" : "CONNECTED", 47, stale ? TFT_ORANGE : TFT_GREEN);
  labelValue("Last update", String(ageSeconds) + "s ago", 72);
  labelValue("Providers", String(countHealthy()), 102);
  labelValue("API tokens", formatUInt64(sumTotalTokens()), 132, TFT_CYAN);
  double actual = 0.0, estimate = 0.0;
  bool hasActual = false, hasEstimate = false;
  for (JsonObjectConst p : frameDoc["providers"].as<JsonArrayConst>()) {
    if (!p["actual_cost_usd"].isNull()) { actual += p["actual_cost_usd"].as<double>(); hasActual = true; }
    if (!p["estimated_cost_usd"].isNull()) { estimate += p["estimated_cost_usd"].as<double>(); hasEstimate = true; }
  }
  labelValue("Reported cost", hasActual ? moneyValue(actual) : String("--"), 162, TFT_WHITE);
  if (hasEstimate) {
    char estimateText[24]; snprintf(estimateText, sizeof(estimateText), "$%.2f EST", estimate);
    labelValue("Estimated", String(estimateText), 188, TFT_YELLOW);
  } else labelValue("Estimated", "--", 188);
  labelValue("Budget", money(frameDoc["budget_usd"]), 218);
  double spent = (hasActual ? actual : 0.0) + (hasEstimate ? estimate : 0.0);
  if (!frameDoc["budget_usd"].isNull()) {
    char remaining[24]; snprintf(remaining, sizeof(remaining), "$%.2f", fmax(0.0, frameDoc["budget_usd"].as<double>() - spent));
    labelValue("Remaining", String(remaining), 244, TFT_GREEN);
  } else labelValue("Remaining", "--", 244);
  tft.setTextColor(TFT_DARKGREY, TFT_BLACK);
  tft.drawString("COSTS MAY BE DELAYED", 10, 285, 1);
  tft.drawRightString(String("BAD FRAMES ") + invalidFrames, 230, 285, 1);
}

void drawSubscriptions() {
  header("SUBSCRIPTIONS");
  JsonArrayConst providers = frameDoc["providers"].as<JsonArrayConst>();
  int y = 43;
  uint8_t shown = 0;
  for (JsonObjectConst p : providers) {
    const char *id = p["id"] | "provider";
    if (strstr(id, "subscription") == nullptr && strstr(id, "plan") == nullptr) continue;
    if (shown++ >= 4) break;
    tft.fillRoundRect(7, y, 226, 60, 5, TFT_DARKGREY);
    tft.setTextColor(TFT_WHITE, TFT_DARKGREY);
    tft.drawString(p["name"] | "Provider", 14, y + 6, 2);
    tft.setTextColor(TFT_YELLOW, TFT_DARKGREY);
    tft.drawRightString(statusText(p), 226, y + 8, 1);
    tft.setTextColor(TFT_LIGHTGREY, TFT_DARKGREY);
    String quotaLine;
    if (!p["quota_remaining_percent"].isNull()) {
      char quota[24]; snprintf(quota, sizeof(quota), "Remaining %.1f%%", p["quota_remaining_percent"].as<double>());
      quotaLine = quota;
    } else if (strcmp(p["status"] | "", "unsupported") == 0) quotaLine = "Usage / reset: unsupported";
    else if (strcmp(p["status"] | "", "manual") == 0) quotaLine = "User-provided entry";
    else quotaLine = "No verified quota reported";
    tft.setTextColor(TFT_LIGHTGREY, TFT_DARKGREY);
    tft.drawString(quotaLine, 14, y + 22, 1);
    if (!p["reset_at"].isNull()) {
      String reset = String("Reset ") + String(p["reset_at"].as<const char *>()).substring(0, 19);
      tft.drawString(reset, 14, y + 33, 1);
    }
    String updated = String(p["last_updated"].as<const char *>());
    String source = String(p["source"] | "unknown");
    String sourceLabel = source == "provider_reported" ? "Provider" : (source == "estimated" ? "Estimate" : (source == "locally_tracked" ? "Local" : source));
    tft.setTextColor(TFT_LIGHTGREY, TFT_DARKGREY);
    tft.drawString(sourceLabel + "  Updated " + updated.substring(11, 16) + " UTC", 14, y + 45, 1);
    y += 63;
  }
  if (shown == 0) {
    tft.setTextColor(TFT_LIGHTGREY, TFT_BLACK);
    tft.drawCentreString("No subscription records", 120, 120, 2);
  }
  tft.setTextColor(TFT_DARKGREY, TFT_BLACK);
  tft.drawString("Only verified quota/reset data is shown", 8, 294, 1);
}

void drawApiDetails() {
  header("API DETAILS");
  JsonArrayConst providers = frameDoc["providers"].as<JsonArrayConst>();
  tft.setTextColor(TFT_LIGHTGREY, TFT_BLACK);
  tft.drawString(String("Last update ") + String((millis() - lastReceivedMs) / 1000) + "s ago", 8, 35, 1);
  int y = 43;
  uint8_t shown = 0;
  for (JsonObjectConst p : providers) {
    const char *id = p["id"] | "provider";
    if (strstr(id, "subscription") != nullptr || strstr(id, "plan") != nullptr) continue;
    if (shown++ >= 4) break;
    tft.fillRoundRect(7, y, 226, 60, 5, TFT_DARKGREY);
    tft.setTextColor(TFT_WHITE, TFT_DARKGREY);
    tft.drawString(p["name"] | "Provider", 13, y + 5, 2);
    tft.setTextColor(TFT_YELLOW, TFT_DARKGREY);
    tft.drawRightString(statusText(p), 226, y + 7, 1);
    bool hasInput = !p["input_tokens"].isNull();
    bool hasOutput = !p["output_tokens"].isNull();
    bool hasTotal = !p["total_tokens"].isNull();
    uint64_t inputValue = hasInput ? p["input_tokens"].as<uint64_t>() : 0;
    uint64_t outputValue = hasOutput ? p["output_tokens"].as<uint64_t>() : 0;
    uint64_t totalValue = hasTotal ? p["total_tokens"].as<uint64_t>() : 0;
    String line = "In " + metric(inputValue, hasInput) + " Out " + metric(outputValue, hasOutput);
    tft.setTextColor(TFT_LIGHTGREY, TFT_DARKGREY);
    tft.drawString(line, 13, y + 22, 1);
    String cost = !p["actual_cost_usd"].isNull() ? "Actual " + money(p["actual_cost_usd"]) : (!p["estimated_cost_usd"].isNull() ? "Est " + money(p["estimated_cost_usd"]) : "Cost --");
    tft.drawString(cost + "  Total " + metric(totalValue, hasTotal), 13, y + 34, 1);
    if (!p["message"].isNull()) {
      String detail = String(p["message"].as<const char *>());
      if (detail.length() > 34) detail = detail.substring(0, 34);
      tft.setTextColor(TFT_YELLOW, TFT_DARKGREY);
      tft.drawString(detail, 13, y + 46, 1);
    }
    y += 62;
  }
  tft.setTextColor(TFT_DARKGREY, TFT_BLACK);
  tft.drawString("Completion tokens; org-wide costs", 8, 294, 1);
}

void renderDashboard() {
  if (!hasSnapshot) { drawWaiting(); return; }
  if (stale) {
    // Keep provider values visible but make the connection state prominent.
  }
  if (currentPage == 0) drawOverview();
  else if (currentPage == 1) drawSubscriptions();
  else drawApiDetails();
}

void processFrame(size_t length) {
  uint64_t snapshotId = 0;
  if (!validateSnapshot(rxBuffer, length, &snapshotId)) { ++invalidFrames; return; }
  if (hasSnapshot && snapshotId == lastSnapshotId) { ++invalidFrames; return; }
  lastSnapshotId = snapshotId;
  lastReceivedMs = millis();
  hasSnapshot = true;
  stale = false;
  renderDashboard();
}

void readSerialFrames() {
  while (Serial.available() > 0) {
    int value = Serial.read();
    if (value < 0) return;
    char ch = static_cast<char>(value);
    if (discardingFrame) {
      if (ch == '\n') { discardingFrame = false; rxLength = 0; }
      continue;
    }
    if (ch == '\n') {
      if (rxLength > 0) processFrame(rxLength);
      rxLength = 0;
      continue;
    }
    if (rxLength >= MAX_FRAME_BYTES) {
      ++invalidFrames;
      rxLength = 0;
      discardingFrame = true;
      continue;
    }
    rxBuffer[rxLength++] = ch;
  }
}

void setup() {
  Serial.begin(SERIAL_BAUD);
  Serial.setTimeout(1);
  SPI.begin(TFT_PIN_SCLK, TFT_PIN_MISO, TFT_PIN_MOSI, TFT_PIN_CS);
  tft.init();
  tft.setRotation(0);
  drawWaiting();
  lastPageChangeMs = millis();
}

void loop() {
  readSerialFrames();
  uint32_t now = millis();
  if (hasSnapshot && !stale && now - lastReceivedMs >= STALE_AFTER_MS) {
    stale = true;
    renderDashboard();
  }
  if (now - lastPageChangeMs >= PAGE_ROTATE_MS) {
    currentPage = static_cast<uint8_t>((currentPage + 1) % 3);
    lastPageChangeMs = now;
    renderDashboard();
  }
}
