# Arduino Integration Architecture

## System Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                    Arduino Nano 33 Sense Rev2                   │
│  ┌──────────────────┐  ┌──────────────┐  ┌──────────────────┐  │
│  │   Temperature    │  │   Humidity   │  │    RGB LED       │  │
│  │   (hs3003_t_c)   │  │(hs3003_h_rh) │  │  (Visual Feed)   │  │
│  └────────┬─────────┘  └──────┬───────┘  └────────▲─────────┘  │
│           │                   │                    │             │
│           └───────────┬───────┘                    │             │
│                       │                            │             │
└───────────────────────┼────────────────────────────┼─────────────┘
                        │ USB Serial                 │
                        │ (JSON packets)             │ RGB Commands
                        ▼                            │
┌─────────────────────────────────────────────────────────────────┐
│                         SensorAgent                             │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │ Nano33SenseRev2 Class (Thread-based Serial Reader)       │   │
│  │  • Reads sensor data in background thread                │   │
│  │  • Parses JSON packets into SensorPacket objects         │   │
│  │  • Provides get_state() for latest readings              │   │
│  │  • Controls LED via rgb(), red_LED(), yellow_LED(), etc. │   │
│  └──────────────────────────────────────────────────────────┘   │
│                                                                  │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │ Decision Logic (decide_lights)                           │   │
│  │  • temp < 15°C or temp > 30°C  → RED (Alert)             │   │
│  │  • humidity > 80%              → YELLOW (Warning)        │   │
│  │  • Normal conditions           → GREEN (Safe)            │   │
│  └──────────────────────────────────────────────────────────┘   │
│                                                                  │
│  [Arduino Mode]               [CSV Fallback Mode]               │
│  read_arduino_sensors() ←──→ read_csv_sensors()                 │
│  (Primary)                   (Automatic fallback)               │
└──────────────────────────┬───────────────────────────────────────┘
                           │
                           │ MQTT: home/agents/light-commands
                           │ {
                           │   "from": "sensor",
                           │   "light_commands": {"arduino_room": "green"},
                           │   "sensors": {"temps": {...}, "humids": {...}}
                           │ }
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│                      LightController                            │
│  • Receives light commands from SensorAgent                     │
│  • Logs decision                                                │
│  • Forwards to ActuatorAgent                                    │
└──────────────────────────┬───────────────────────────────────────┘
                           │
                           │ MQTT: home/agents/actuator-commands
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│                       ActuatorAgent                             │
│  • Receives actuator commands                                   │
│  • Creates request_id for tracking                              │
│  • Publishes to supervisor for validation                       │
│  • Waits for approval (30s timeout)                             │
└──────────────────────────┬───────────────────────────────────────┘
                           │
                           │ MQTT: home/agents/actuator/status
                           │ (pending validation)
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│                      LLMSupervisor                              │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │ AI Validation Engine                                     │   │
│  │  • Checks decision against rules                         │   │
│  │  • Uses LLM (HuggingFace model) for validation           │   │
│  │  • Provides reasoning for approval/rejection             │   │
│  └──────────────────────────────────────────────────────────┘   │
└──────────────────────────┬───────────────────────────────────────┘
                           │
                           │ MQTT: home/agents/supervisor/feedback
                           │ {"approved": true/false, "reasoning": "..."}
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│                    ActuatorAgent (Execute)                      │
│  • Receives supervisor approval                                 │
│  • Executes approved command                                    │
│  • Publishes final control message                              │
└──────────────────────────┬───────────────────────────────────────┘
                           │
                           │ MQTT: home/arduino_room/light/control
                           │ {"color": "green", "room": "arduino_room"}
                           ▼
                    [Final Control Message]
```

## Data Flow Sequence

### 1. Sensor Reading Phase (Every 15 seconds)

```
Arduino Hardware
    │
    ├─ Temperature: 24.5°C
    ├─ Humidity: 55.2%
    └─ (Other sensors available but not used)
    │
    ▼ USB Serial @ 115200 baud
SensorAgent.read_arduino_sensors()
    │
    ├─ Calls: arduino.get_state()
    ├─ Gets: SensorPacket(hs3003_t_c=24.5, hs3003_h_rh=55.2)
    └─ Returns: temps={'arduino_room': 24.5}, humids={'arduino_room': 55.2}
```

### 2. Decision Phase

```
SensorAgent.decide_lights(temps, humids)
    │
    ├─ Room: arduino_room
    ├─ Temp: 24.5°C (within 15-30°C range)
    ├─ Humid: 55.2% (within ≤80% range)
    └─ Decision: GREEN (normal conditions)
```

### 3. LED Control Phase (Immediate)

```
SensorAgent (if arduino connected)
    │
    ├─ Decision: "green"
    ├─ Calls: arduino.green_LED()
    ├─ Arduino receives: RGB=0,255,0\n
    └─ LED turns GREEN ✓
```

### 4. MQTT Publishing Phase

```
SensorAgent.run()
    │
    ├─ Creates JSON payload
    ├─ Publishes to: home/agents/light-commands
    └─ Message:
        {
          "from": "sensor",
          "timestamp": 1738684800.0,
          "light_commands": {"arduino_room": "green"},
          "sensors": {
            "temps": {"arduino_room": 24.5},
            "humids": {"arduino_room": 55.2}
          }
        }
```

### 5. Multi-Agent Processing

```
LightController
    ├─ Receives message
    ├─ Logs: "arduino_room → green"
    └─ Forwards to: home/agents/actuator-commands

ActuatorAgent
    ├─ Receives command
    ├─ Creates request_id
    └─ Sends for validation: home/agents/actuator/status

LLMSupervisor
    ├─ Validates decision with AI
    ├─ Reasoning: "Normal temp & humidity, green is appropriate"
    └─ Approves: home/agents/supervisor/feedback

ActuatorAgent
    ├─ Receives approval
    ├─ Executes command
    └─ Publishes: home/arduino_room/light/control
```

## Hybrid Architecture: Arduino + CSV Fallback

```
┌─────────────────────────────────────────────────────────────┐
│                     SensorAgent.__init__()                  │
│                                                             │
│  if USE_ARDUINO:                                            │
│      try:                                                   │
│          self.arduino = Nano33SenseRev2(ARDUINO_PORT) ✓     │
│      except:                                                │
│          self.arduino = None → CSV Fallback                 │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│              SensorAgent.read_sensors()                     │
│                                                             │
│  if self.arduino and USE_ARDUINO:                           │
│      return read_arduino_sensors() ──┐                      │
│  else:                                │                     │
│      return read_csv_sensors() ───────┼──────┐              │
└───────────────────────────────────────┼──────┼──────────────┘
                                        │      │
                    ┌───────────────────┘      └─────────────┐
                    ▼                                        ▼
    ┌────────────────────────────┐          ┌────────────────────────────┐
    │  read_arduino_sensors()    │          │   read_csv_sensors()       │
    │  • Real-time hardware      │          │   • Fallback mode          │
    │  • Single room             │          │   • Multiple rooms         │
    │  • arduino_room            │          │   • living_room, bedroom   │
    │  • Direct from Arduino     │          │   • From CSV file          │
    └────────────────────────────┘          └────────────────────────────┘
```

## Class Hierarchy

```
MQTTBaseAgent (base/mqtt_base.py)
    │
    ├─ client: MQTT client
    ├─ connect(): Establish MQTT connection
    ├─ disconnect(): Close MQTT connection
    └─ subscribe_to_topics(): Override in subclass
         │
         ▼
    SensorAgent (agents/sensor_agent1.py)
         │
         ├─ arduino: Nano33SenseRev2 instance (or None)
         │
         ├─ __init__():
         │   └─ Attempt Arduino connection with fallback
         │
         ├─ subscribe_to_topics():
         │   └─ Connect to MQTT broker
         │
         ├─ read_sensors():
         │   └─ Route to Arduino or CSV
         │
         ├─ read_arduino_sensors():
         │   └─ Get data from Arduino hardware
         │
         ├─ read_csv_sensors():
         │   └─ Get data from CSV file
         │
         ├─ decide_lights(temps, humids):
         │   └─ Apply decision rules
         │
         └─ run():
             ├─ Loop every 15s
             ├─ Read sensors
             ├─ Decide colors
             ├─ Control LED (if Arduino)
             ├─ Publish MQTT
             └─ Cleanup on exit

    Nano33SenseRev2
         │
         ├─ ser: Serial port connection
         ├─ _thread: Background reader thread
         ├─ _latest_pkt: Queue for latest packet
         │
         ├─ __init__(port, baud):
         │   └─ Start background reading
         │
         ├─ get_state() → SensorPacket:
         │   └─ Get latest sensor reading
         │
         ├─ rgb(r, g, b):
         │   └─ Set LED color
         │
         ├─ red_LED(), yellow_LED(), green_LED(), off():
         │   └─ Preset colors
         │
         ├─ _read_loop():
         │   └─ Background thread reading serial data
         │
         └─ close():
             └─ Cleanup serial connection
```

## Configuration Points

```
agents/sensor_agent1.py
    │
    ├─ Line 26: USE_ARDUINO = True
    │            ↓ Set to False to force CSV mode
    │
    ├─ Line 27: ARDUINO_PORT = "COM3"
    │            ↓ Change to your Arduino's serial port
    │
    ├─ Line 28: ARDUINO_ROOM_NAME = "arduino_room"
    │            ↓ Change room name in MQTT messages
    │
    ├─ Lines 223-228: Decision rules
    │                 ↓ Modify thresholds
    │                 if temp < 15 or temp > 30: red
    │                 elif humid > 80: yellow
    │                 else: green
    │
    └─ Line 268: time.sleep(15)
                 ↓ Change reading interval (seconds)
```

## Error Handling Flow

```
┌─────────────────────────────────────────────────────────────┐
│              Connection Error Handling                      │
└─────────────────────────────────────────────────────────────┘

SensorAgent.__init__()
    │
    ├─ try: Nano33SenseRev2(ARDUINO_PORT)
    │   └─ Success → self.arduino = [connected]
    │
    └─ except: Connection failed
        ├─ Print: "✗ Arduino connection failed: [error]"
        ├─ Print: "  Falling back to CSV mode"
        └─ self.arduino = None → Automatic CSV mode

┌─────────────────────────────────────────────────────────────┐
│              Runtime Error Handling                         │
└─────────────────────────────────────────────────────────────┘

read_arduino_sensors()
    │
    ├─ try: packet = arduino.get_state()
    │   ├─ Success → Extract temp & humidity
    │   └─ Timeout → Print: "⚠️  No Arduino data available"
    │
    └─ except: Read error
        └─ Print: "✗ Arduino read error: [error]"
        └─ Return empty dicts (handled gracefully)

LED Control
    │
    ├─ try: arduino.red_LED() / yellow_LED() / green_LED()
    │   └─ Success → Print: "💡 Arduino LED → [color]"
    │
    └─ except: LED error
        └─ Print: "✗ LED control error: [error]"
        └─ Sensor reading continues (non-blocking)

Cleanup (finally block)
    │
    ├─ if self.arduino:
    │   ├─ arduino.off() → Turn off LED
    │   └─ arduino.close() → Close serial port
    │
    └─ self.disconnect() → Close MQTT connection
```

## Thread Safety

```
Main Thread                    Background Thread
     │                               │
     │ SensorAgent.__init__()        │
     ├──────────────────────────────►│ Nano33SenseRev2.__init__()
     │                               ├─ Start _read_loop() thread
     │                               │      │
     │                               │      ├─ while _running:
     │                               │      │   ├─ readline()
     │                               │      │   ├─ parse_packet()
     │                               │      │   └─ _set_latest_package()
     │                               │      │       └─ queue.put(pkt)
     │                               │      │
     │ SensorAgent.run()             │      │
     │   ├─ read_arduino_sensors()   │      │
     │   │   └─ arduino.get_state()  │      │
     │   │       └─ queue.get() ◄────┼──────┘
     │   │           (thread-safe)   │
     │   │                           │
     │   ├─ LED control              │
     │   │   └─ arduino.red_LED()    │
     │   │       └─ ser.write() ──────────►
     │   │           (thread-safe)   │
     │   │                           │
     │   └─ sleep(15)                │
     │                               │
     │ finally:                      │
     │   └─ arduino.close()          │
     │       ├─ _running = False     │
     │       └─ ser.close() ─────────┼────► Thread exits
     │                               │
```

## Summary

**Key Architectural Decisions:**

1. ✅ **Single Connection Point**: Arduino only in SensorAgent
2. ✅ **Hybrid Mode**: Arduino primary, CSV fallback
3. ✅ **Direct LED Control**: No MQTT delays for visual feedback
4. ✅ **Thread-based Reading**: Non-blocking serial communication
5. ✅ **Graceful Degradation**: Automatic fallback on errors
6. ✅ **Minimal Changes**: Only SensorAgent modified
7. ✅ **Backward Compatible**: Works with or without Arduino
8. ✅ **Standard Protocols**: MQTT for agent communication, Serial for Arduino

This architecture maintains the existing 4-agent MQTT system while seamlessly integrating real-time hardware sensors with robust error handling and automatic fallback capability.
