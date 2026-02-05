# Arduino Integration Verification Checklist

Use this checklist to verify that the Arduino integration is working correctly.

## Pre-Flight Checks

### Hardware Setup
- [ ] Arduino Nano 33 Sense Rev2 is physically connected via USB
- [ ] USB cable is data-capable (not power-only)
- [ ] Arduino has correct firmware uploaded (`nano33_sense_rev2_all_fw.ino`)
- [ ] Arduino LED blinks briefly on power-up (firmware running)

### Software Setup
- [ ] Python 3.8+ installed
- [ ] MQTT broker (Mosquitto) running
- [ ] Dependencies installed (`pip install -r requirements.txt`)
- [ ] pyserial==3.5 installed (check with `pip show pyserial`)

### Configuration
- [ ] Arduino port identified (Device Manager / `ls /dev/cu.usbmodem*` / `ls /dev/ttyACM*`)
- [ ] `ARDUINO_PORT` configured in `agents/sensor_agent1.py` line 27
- [ ] `USE_ARDUINO = True` in `agents/sensor_agent1.py` line 26
- [ ] Arduino IDE Serial Monitor is CLOSED (prevents port conflicts)

## Phase 1: Arduino Connection Test

Run: `python test_arduino.py`

- [ ] **[1/4] Connection**: "✓ Connection successful!" displayed
- [ ] **[2/4] Sensor Data**: Temperature and humidity values displayed
  - [ ] Temperature is reasonable (10-40°C range)
  - [ ] Humidity is reasonable (20-90% range)
- [ ] **[3/4] LED Tests**: All LEDs work correctly
  - [ ] Red LED turns on
  - [ ] Yellow LED turns on
  - [ ] Green LED turns on
  - [ ] LED turns off
- [ ] **[4/4] Cleanup**: Connection closes without errors
- [ ] **Final Message**: "✓ ALL TESTS PASSED!" displayed

**If any test fails, STOP and troubleshoot before proceeding.**

## Phase 2: SensorAgent Standalone Test

Run: `cd agents && python sensor_agent1.py`

### Startup Checks
- [ ] "Connecting to Arduino on [PORT]..." displayed
- [ ] "✓ Arduino connected successfully!" displayed
- [ ] "SensorAgent subscribed!" displayed
- [ ] No connection error messages

### Operation Checks (Wait for first reading cycle)
- [ ] "SensorAgent analyzing..." displayed
- [ ] "📡 Arduino: T=[temp]°C, H=[humidity]%" displayed
- [ ] " arduino_room: [temp]°C ([humidity]%) → [color]" displayed
- [ ] "💡 Arduino LED → [color]" displayed
- [ ] "MQTT → LightController: {'arduino_room': '[color]'}" displayed
- [ ] Arduino LED physically changes to correct color
- [ ] Cycle repeats every 15 seconds

### Decision Rule Checks
Run these scenarios while sensor agent is running:

**Normal Conditions:**
- [ ] Room temperature (15-30°C) → Green LED
- [ ] Low humidity (≤80%) → Green LED

**High Humidity Test:**
- [ ] Breathe on sensor for 5 seconds
- [ ] Humidity increases above 80%
- [ ] LED changes to Yellow within 15 seconds
- [ ] Message shows "→ yellow"

**High Temperature Test:**
- [ ] Cover sensor with hand for 10 seconds
- [ ] Temperature increases above 30°C
- [ ] LED changes to Red within 15 seconds
- [ ] Message shows "→ red"

**Low Temperature Test (if possible):**
- [ ] Use cold pack near sensor (or ice in bag)
- [ ] Temperature drops below 15°C
- [ ] LED changes to Red within 15 seconds
- [ ] Message shows "→ red"

**Recovery Test:**
- [ ] Remove stimulus (hand, breath, cold)
- [ ] Wait for conditions to normalize
- [ ] LED returns to Green within 30 seconds

### Cleanup Checks
- [ ] Press Ctrl+C to stop
- [ ] "SensorAgent stopped" displayed
- [ ] "Closing Arduino connection..." displayed
- [ ] LED turns off
- [ ] No error messages during shutdown

## Phase 3: Full System Integration Test

Run: `python orchestrator.py`

### All Agents Start
- [ ] SensorAgent starts and connects to Arduino
- [ ] LightController starts
- [ ] ActuatorAgent starts
- [ ] LLMSupervisor starts
- [ ] All agents show "subscribed" messages
- [ ] No startup errors

### Message Flow Verification
Watch for this sequence every 15 seconds:

1. **SensorAgent:**
   - [ ] "SensorAgent analyzing..." appears
   - [ ] "📡 Arduino: T=[temp]°C, H=[humidity]%" appears
   - [ ] " arduino_room: [temp]°C ([humidity]%) → [color]" appears
   - [ ] "💡 Arduino LED → [color]" appears
   - [ ] "MQTT → LightController: {'arduino_room': '[color]'}" appears

2. **LightController:**
   - [ ] Receives message from SensorAgent
   - [ ] Logs decision for arduino_room
   - [ ] Forwards to ActuatorAgent

3. **ActuatorAgent:**
   - [ ] Receives command for arduino_room
   - [ ] Creates request_id
   - [ ] Publishes to supervisor for validation
   - [ ] Shows "Waiting for supervisor approval..."

4. **LLMSupervisor:**
   - [ ] Receives validation request
   - [ ] Processes with AI (may take 10-100s first time)
   - [ ] Returns approval/rejection
   - [ ] Provides reasoning

5. **ActuatorAgent (after approval):**
   - [ ] Receives supervisor approval
   - [ ] Executes command
   - [ ] Publishes to `home/arduino_room/light/control`
   - [ ] Shows success message

### End-to-End Checks
- [ ] Full cycle completes without errors
- [ ] Arduino LED reflects current decision
- [ ] LLM Supervisor validates arduino_room
- [ ] System runs continuously (monitor for 5 minutes)
- [ ] No memory leaks or performance degradation
- [ ] All agents remain responsive

### Multi-Room Compatibility (if CSV fallback tested)
- [ ] arduino_room processes correctly
- [ ] Other rooms (if CSV used) also process
- [ ] No conflicts between Arduino and CSV rooms

## Phase 4: Fallback and Error Handling Tests

### Test 1: Automatic CSV Fallback (Arduino Disconnect Before Start)
- [ ] Disconnect Arduino USB cable
- [ ] Run: `python orchestrator.py`
- [ ] "✗ Arduino connection failed: [error]" displayed
- [ ] "  Falling back to CSV mode" displayed
- [ ] System continues with CSV data
- [ ] living_room, bedroom, etc. appear (CSV rooms)
- [ ] No crashes or errors
- [ ] System operates normally with CSV data

### Test 2: Manual CSV Mode
- [ ] Set `USE_ARDUINO = False` in sensor_agent1.py
- [ ] Run: `python orchestrator.py`
- [ ] No Arduino connection attempt
- [ ] CSV data used immediately
- [ ] living_room, bedroom, etc. appear
- [ ] System operates normally

### Test 3: Mid-Operation Disconnect
- [ ] Start system with Arduino connected
- [ ] Verify arduino_room is working
- [ ] Disconnect Arduino USB cable while running
- [ ] Next read cycle shows error
- [ ] System continues (may show timeouts)
- [ ] No crashes

**Note:** Current implementation doesn't auto-reconnect mid-operation. This is a future enhancement.

### Test 4: Port Already in Use
- [ ] Open Arduino IDE Serial Monitor
- [ ] Try to run: `python test_arduino.py`
- [ ] Should fail with "Port already in use" or similar
- [ ] Close Serial Monitor
- [ ] Retry - should work
- [ ] System handles port conflicts gracefully

### Test 5: Wrong Port Configuration
- [ ] Set `ARDUINO_PORT = "COM99"` (non-existent port)
- [ ] Run: `python test_arduino.py`
- [ ] Should fail with "could not open port"
- [ ] Change back to correct port
- [ ] Retry - should work
- [ ] Error messages are clear and helpful

## Phase 5: Performance and Stability Tests

### Continuous Operation Test
- [ ] Run system for 30 minutes
- [ ] Arduino connection remains stable
- [ ] LED continues to update correctly
- [ ] No memory leaks (check Task Manager)
- [ ] No error accumulation
- [ ] All agents remain responsive

### Rapid Environmental Change Test
- [ ] Alternate between breathing on sensor and removing
- [ ] LED should change colors appropriately
- [ ] System keeps up with changes (within 15s)
- [ ] No missed readings
- [ ] No errors or crashes

### MQTT Message Validation
Use MQTT Explorer or `mosquitto_sub` to verify:

```bash
mosquitto_sub -h localhost -t "home/#" -v
```

- [ ] `home/agents/light-commands` contains arduino_room
- [ ] `home/agents/actuator-commands` contains arduino_room
- [ ] `home/agents/actuator/status` shows pending validation
- [ ] `home/agents/supervisor/feedback` shows approval
- [ ] `home/arduino_room/light/control` shows final command
- [ ] All messages are valid JSON
- [ ] Timestamps are reasonable

## Phase 6: Code Quality Checks

### Syntax and Import Checks
```bash
python -m py_compile agents/sensor_agent1.py
```
- [ ] No syntax errors

### Dependency Verification
```bash
pip show pyserial
```
- [ ] pyserial 3.5 is installed
- [ ] No version conflicts

### File Modifications
- [ ] Only `sensor_agent1.py` modified (no other agent files)
- [ ] Only `requirements.txt` modified (dependencies)
- [ ] No changes to `orchestrator.py`
- [ ] No changes to other agents
- [ ] No changes to base classes

## Final Verification

### Documentation Complete
- [ ] `QUICKSTART.md` available
- [ ] `ARDUINO_INTEGRATION.md` available
- [ ] `ARCHITECTURE.md` available
- [ ] `IMPLEMENTATION_SUMMARY.md` available
- [ ] `test_arduino.py` available
- [ ] All documentation is accurate

### System Ready for Production
- [ ] All phases completed successfully
- [ ] No unresolved errors
- [ ] Arduino integration working
- [ ] Fallback mechanism verified
- [ ] LED control functional
- [ ] MQTT integration confirmed
- [ ] Multi-agent flow validated
- [ ] Documentation reviewed

## Troubleshooting Reference

If any check fails, refer to:

1. **Connection Issues** → `ARDUINO_INTEGRATION.md` - Troubleshooting section
2. **LED Not Working** → `QUICKSTART.md` - Quick Test section
3. **MQTT Issues** → Check MQTT broker is running
4. **Import Errors** → Run `pip install -r requirements.txt`
5. **Port Conflicts** → Close Arduino IDE Serial Monitor
6. **Firmware Issues** → Re-upload Arduino firmware

## Sign-Off

Once all checks pass:

- [ ] System is ready for use
- [ ] Arduino integration is fully functional
- [ ] Documentation is complete
- [ ] No critical issues remain

**Verified by:** ________________  **Date:** ________________

**Notes:**
_____________________________________________________________
_____________________________________________________________
_____________________________________________________________

---

## Quick Status Summary

**Total Checks:** ~100+
**Phases:** 6
**Estimated Time:** 30-45 minutes for complete verification

**Status Indicators:**
- ✅ Check passed
- ⚠️ Warning (non-critical)
- ❌ Failed (needs attention)

**Priority Levels:**
- 🔴 Critical: Must pass (Phases 1-3)
- 🟡 Important: Should pass (Phase 4)
- 🟢 Optional: Nice to have (Phases 5-6)
