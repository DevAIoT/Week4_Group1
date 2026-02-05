# Quick Start Guide - Arduino Integration

## 5-Minute Setup

### Step 1: Install Dependencies (1 min)

```bash
cd Week-4-Agentic-AIoT
pip install -r requirements.txt
```

### Step 2: Find Your Arduino Port (1 min)

**Windows:**
- Device Manager → Ports (COM & LPT)
- Look for Arduino → Note COM number (e.g., COM3)

**macOS:**
```bash
ls /dev/cu.usbmodem*
```

**Linux:**
```bash
ls /dev/ttyACM*
```

### Step 3: Configure Port (30 sec)

Edit `agents/sensor_agent1.py` line 27:

```python
ARDUINO_PORT = "COM3"  # Change to your port
```

### Step 4: Test Arduino (1 min)

```bash
python test_arduino.py
```

**Expected:** ✓ ALL TESTS PASSED!

If failed, see troubleshooting in ARDUINO_INTEGRATION.md

### Step 5: Run System (30 sec)

```bash
python orchestrator.py
```

**Expected output:**
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

## LED Color Meanings

- 🟢 **Green**: Normal conditions (15-30°C, humidity ≤80%)
- 🟡 **Yellow**: High humidity (>80%)
- 🔴 **Red**: Temperature alert (<15°C or >30°C)

## Quick Test

**Breathe on the sensor** → Temp & humidity increase → LED should change to yellow or red

## Troubleshooting

### Arduino Not Found

1. Check USB cable connected
2. Verify port in Device Manager
3. Close Arduino IDE Serial Monitor
4. Try different port (COM4, COM5, etc.)

**System will automatically use CSV fallback if Arduino unavailable**

### No LED Changes

1. Verify firmware uploaded to Arduino
2. Check USB cable (data-capable, not power-only)
3. Restart system

### Still Having Issues?

See detailed guide: `ARDUINO_INTEGRATION.md`

## Running Without Arduino

Set `USE_ARDUINO = False` in `agents/sensor_agent1.py` line 26:

```python
USE_ARDUINO = False
```

System will use CSV data from `Synthetic_sensor_data.csv`

## Next Steps

- Read `ARDUINO_INTEGRATION.md` for detailed documentation
- Read `IMPLEMENTATION_SUMMARY.md` for technical details
- Experiment with environmental changes (breathe on sensor, cover with hand)
- Monitor MQTT messages
- Test decision rules

## Files Modified

- ✅ `agents/sensor_agent1.py` - Arduino integration
- ✅ `requirements.txt` - Added pyserial

## Files Unchanged

- ✅ `orchestrator.py`
- ✅ `light_controller_agent.py`
- ✅ `actuator_agent1.py`
- ✅ `llm_supervisor_agent.py`
- ✅ All base classes

**Zero breaking changes to existing functionality!**
