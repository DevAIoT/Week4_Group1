# Arduino Sensor Integration Guide

## Overview

This implementation integrates real-time Arduino Nano 33 Sense Rev2 sensor data into the 4-agent MQTT home automation system. The system can read live temperature and humidity data from the Arduino hardware while maintaining automatic fallback to CSV mode if the Arduino is not connected.

## Features

- **Live Hardware Sensors**: Real-time temperature and humidity from Arduino Nano 33 Sense Rev2
- **Visual Feedback**: Arduino's RGB LED changes color based on environmental conditions
- **Automatic Fallback**: Seamlessly switches to CSV mode if Arduino is unavailable
- **Hybrid Architecture**: Single connection point in SensorAgent (no serial port conflicts)
- **Minimal Changes**: Only 2 files modified (sensor_agent1.py, requirements.txt)

## Prerequisites

### Hardware
- Arduino Nano 33 Sense Rev2 board
- USB cable
- Flashed with `Week-3-Connecting-LMs-with-IoT/Arduino/nano33_sense_rev2_all_fw/nano33_sense_rev2_all_fw.ino`

### Software
- Python 3.8+
- MQTT broker running (e.g., Mosquitto)
- All dependencies from requirements.txt

## Installation

1. **Install Dependencies**

```bash
cd Week-4-Agentic-AIoT
pip install -r requirements.txt
```

This will install `pyserial==3.5` along with other required packages.

2. **Find Your Arduino Port**

**Windows:**
- Open Device Manager → Ports (COM & LPT)
- Look for "Arduino" or "USB Serial Device"
- Note the COM port (e.g., COM3, COM4)

**macOS:**
```bash
ls /dev/cu.usbmodem*
```

**Linux:**
```bash
ls /dev/ttyACM* /dev/ttyUSB*
```

3. **Configure Arduino Port**

Edit `agents/sensor_agent1.py` around line 27:

```python
ARDUINO_PORT = "COM3"  # Change to your actual port
```

4. **Test Arduino Connection**

```bash
python test_arduino.py
```

Expected output:
```
============================================================
Arduino Nano 33 Sense Rev2 Connection Test
============================================================

[1/4] Connecting to Arduino on COM3...
✓ Connection successful!

[2/4] Reading sensor data...
✓ Sensor data received:
   Temperature: 24.5°C
   Humidity: 55.2%
   Pressure: 101.3 kPa
   Proximity: 0

[3/4] Testing LED control...
   Red LED... ✓
   Yellow LED... ✓
   Green LED... ✓
   Turning off... ✓

[4/4] Closing connection...
✓ Connection closed

============================================================
✓ ALL TESTS PASSED!
============================================================
```

## Usage

### Running the Full System

```bash
python orchestrator.py
```

Expected output with Arduino connected:
```
Connecting to Arduino on COM3...
✓ Arduino connected successfully!
SensorAgent subscribed!

SensorAgent analyzing...
📡 Arduino: T=24.5°C, H=55.2%
 arduino_room: 24.5°C (55.2%) → green
💡 Arduino LED → green
MQTT → LightController: {'arduino_room': 'green'}
```

### Running SensorAgent Standalone

```bash
cd agents
python sensor_agent1.py
```

### Using CSV Mode Only

Set `USE_ARDUINO = False` in `agents/sensor_agent1.py` line 26:

```python
USE_ARDUINO = False  # Disable Arduino, use CSV only
```

## Decision Rules & LED Behavior

The Arduino LED changes color based on environmental conditions:

| Condition | Temperature | Humidity | LED Color | Rule |
|-----------|-------------|----------|-----------|------|
| Safe | 15-30°C | ≤80% | **Green** | Normal range |
| High Humidity | Any | >80% | **Yellow** | Warning |
| Too Cold | <15°C | Any | **Red** | Alert |
| Too Hot | >30°C | Any | **Red** | Alert |

**Test scenarios:**
- Breathe on sensor → increases temp & humidity → may turn yellow/red
- Cover with hand → increases temp → may turn red
- Normal room conditions → green

## Architecture

### Data Flow

```
Arduino Hardware
    ↓ (serial USB)
SensorAgent (reads + controls LED)
    ↓ (MQTT: home/agents/light-commands)
LightController
    ↓ (MQTT: home/agents/actuator-commands)
ActuatorAgent
    ↓ (MQTT: home/agents/actuator/status)
LLMSupervisor (validates with AI)
    ↓ (MQTT: home/agents/supervisor/feedback)
ActuatorAgent (executes)
    ↓ (MQTT: home/arduino_room/light/control)
Final Control Message
```

### Modified Files

1. **agents/sensor_agent1.py**
   - Added Arduino support classes (SensorPacket, Vec3, ApdsColor, Nano33SenseRev2)
   - Added Arduino connection logic in `__init__()`
   - Split `read_sensors()` into `read_arduino_sensors()` and `read_csv_sensors()`
   - Added LED control after `decide_lights()`
   - Added cleanup in `finally` block

2. **requirements.txt**
   - Added `pyserial==3.5`

### Unchanged Files

All other files work without modification:
- `orchestrator.py` - No changes needed
- `light_controller_agent.py` - Works with any room names
- `actuator_agent1.py` - Works with any room names
- `llm_supervisor_agent.py` - Works with any room names
- `mqtt_base.py` - No changes needed
- `base/` directory - No changes needed

## Troubleshooting

### Arduino Connection Failed

**Error:** `Arduino connection failed: [Errno 2] could not open port`

**Solutions:**
1. Verify Arduino is connected via USB
2. Check ARDUINO_PORT matches your system (Device Manager on Windows)
3. Close Arduino IDE Serial Monitor if open
4. Try different ports: COM4, COM5 (Windows) or /dev/ttyACM0 (Linux)
5. Check USB cable is data-capable (not power-only)
6. System will automatically fallback to CSV mode

### No Sensor Data (Timeout)

**Error:** `⚠️  No Arduino data available (timeout)`

**Solutions:**
1. Verify Arduino firmware is uploaded and running
2. Check USB cable connection
3. Restart the orchestrator
4. LED should blink briefly on startup if firmware is running

### LED Control Error

**Error:** `✗ LED control error: [exception]`

**Solutions:**
1. Arduino may have disconnected mid-operation
2. Sensor reading continues, but LED control fails
3. Reconnect Arduino and restart system
4. Check USB connection

### Port Already in Use

**Error:** `PermissionError: [Errno 13] Access denied`

**Solutions:**
1. Close Arduino IDE Serial Monitor
2. Close other serial terminal programs
3. Only one program can access the serial port at a time
4. Restart the orchestrator

### Import Error for pyserial

**Error:** `ModuleNotFoundError: No module named 'serial'`

**Solution:**
```bash
pip install pyserial==3.5
```

## Configuration Options

### agents/sensor_agent1.py (lines 25-28)

```python
USE_ARDUINO = True  # Enable/disable Arduino integration
ARDUINO_PORT = "COM3"  # Your Arduino's serial port
ARDUINO_ROOM_NAME = "arduino_room"  # Room name in MQTT messages
```

### Changing Sensor Reading Interval

Edit line 268 in `sensor_agent1.py`:

```python
time.sleep(15)  # Change to desired seconds (e.g., 5, 10, 30)
```

### Changing Decision Rules

Edit `decide_lights()` method (lines 217-233):

```python
if temp < 15 or temp > 30:  # Modify temperature thresholds
    color = "red"
elif humid > 80:  # Modify humidity threshold
    color = "yellow"
else:
    color = "green"
```

## Testing Scenarios

### Test 1: Normal Operation
- **Condition**: Room temperature, normal humidity
- **Expected**: Green LED, continuous operation
- **Verify**: MQTT messages include `arduino_room`

### Test 2: High Humidity
- **Action**: Breathe on sensor
- **Expected**: Yellow LED, humidity >80%
- **Verify**: LED changes within 15 seconds

### Test 3: High Temperature
- **Action**: Cover sensor with hand
- **Expected**: Red LED, temperature >30°C
- **Verify**: LED changes within 15 seconds

### Test 4: Arduino Disconnect
- **Action**: Unplug Arduino during operation
- **Expected**: Error message, automatic fallback to CSV mode
- **Verify**: System continues without Arduino

### Test 5: CSV Fallback Mode
- **Action**: Set `USE_ARDUINO = False`
- **Expected**: CSV data used, no Arduino messages
- **Verify**: Original CSV rooms (living_room, bedroom, etc.)

## System Verification Checklist

- [ ] Arduino connects on startup
- [ ] Temperature and humidity read correctly
- [ ] LED responds to decision rules (red/yellow/green)
- [ ] MQTT messages include `arduino_room`
- [ ] LightController receives and forwards commands
- [ ] ActuatorAgent processes `arduino_room`
- [ ] LLMSupervisor validates decisions
- [ ] System runs continuously without crashes
- [ ] Fallback to CSV works when Arduino disconnected

## Future Enhancements

### Short-term
- [ ] Automatic reconnection on mid-operation disconnect
- [ ] Support multiple Arduinos (different ports/rooms)
- [ ] Configuration file for easy port changes
- [ ] Web-based health monitoring dashboard

### Medium-term
- [ ] WiFi-enabled Arduino (ESP32) for wireless operation
- [ ] Historical data logging to database
- [ ] Web interface for configuration
- [ ] Alert notifications (email/SMS) on anomalies

### Long-term
- [ ] MQTT-native Arduinos (no serial bridge)
- [ ] Machine learning for predictive control
- [ ] Cloud integration for remote monitoring
- [ ] Multi-sensor fusion (Arduino + other IoT devices)

## Support

For issues or questions:
1. Check this guide's Troubleshooting section
2. Run `python test_arduino.py` for diagnostics
3. Verify Arduino firmware is correct
4. Check MQTT broker is running
5. Review orchestrator logs for error messages

## Summary

This implementation provides a robust Arduino integration with:
- ✅ Simple architecture (no new agents, single serial connection)
- ✅ Robust fallback (automatic CSV mode on Arduino failure)
- ✅ Visual feedback (Arduino LED reflects decisions)
- ✅ Minimal changes (only 2 files modified)
- ✅ Backward compatible (can run with or without Arduino)
- ✅ Extensible (easy to add more sensors or multiple Arduinos)

The system maintains the existing 4-agent MQTT architecture while replacing synthetic CSV data with live hardware sensors, creating a real-world IoT home automation system with AI-based validation.
