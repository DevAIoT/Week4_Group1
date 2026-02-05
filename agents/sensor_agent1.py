from base.mqtt_base import MQTTBaseAgent
import csv
from pathlib import Path
import time
import json
from dataclasses import dataclass
from datetime import datetime, timezone
import serial
import threading
import queue
from typing import Optional, Callable
'''
A sensor agent periodically reads synthetic sensor data from a CSV file,
decides light colors for each room based on temperature and humidity,
and publishes these decisions as JSON messages over MQTT to a light controller agent.
This creates an MQTT-based processing loop where the agent derives
room-level environmental status from CSV data and regularly publishes both decisions and
raw measurements to a predefined topic.
'''

# CSV configuration
CSV_PATH = Path(r"Synthetic_sensor_data.csv")
LIGHT_COMMANDS_TOPIC = "home/agents/light-commands"

# Arduino configuration
USE_ARDUINO = True  # Set to False to use CSV mode only
ARDUINO_PORT = "COM3"  # Windows: COM3, Mac: /dev/cu.usbmodem21201, Linux: /dev/ttyACM0
ARDUINO_ROOM_NAME = "arduino_room"

# Dataclasses for Arduino sensor data
@dataclass(frozen=True)
class Vec3:
    x: float
    y: float
    z: float

@dataclass(frozen=True)
class ApdsColor:
    r: int
    g: int
    b: int
    c: int

@dataclass(frozen=True)
class SensorPacket:
    timestamp: datetime
    hs3003_t_c: Optional[float] = None
    hs3003_h_rh: Optional[float] = None
    lps22hb_p_kpa: Optional[float] = None
    lps22hb_t_c: Optional[float] = None
    apds_prox: Optional[int] = None
    apds_color: Optional[ApdsColor] = None
    apds_gesture: Optional[int] = None
    acc_g: Optional[Vec3] = None
    gyro_dps: Optional[Vec3] = None
    mag_uT: Optional[Vec3] = None

def parse_packet(line: str) -> Optional[SensorPacket]:
    import json
    try:
        obj = json.loads(line)
    except Exception:
        return None

    return SensorPacket(
        timestamp=datetime.now(timezone.utc),
        hs3003_t_c=obj.get("hs3003_t_c"),
        hs3003_h_rh=obj.get("hs3003_h_rh"),
        lps22hb_p_kpa=obj.get("lps22hb_p_kpa"),
        lps22hb_t_c=obj.get("lps22hb_t_c"),
        apds_prox=obj.get("apds_prox"),
        apds_color=obj.get("apds_color"),
        apds_gesture=obj.get("apds_gesture"),
        acc_g=obj.get("acc_g"),
        gyro_dps=obj.get("gyro_dps"),
        mag_uT=obj.get("mag_uT"),
    )

def clear_queue(q: queue.Queue):
    while True:
        try:
            q.get_nowait()
            q.task_done()
        except queue.Empty:
            break

class Nano33SenseRev2:
    def __init__(self, port: str, baud: int = 115200,
                 on_packet: Optional[Callable[[SensorPacket], None]] = None,
                 debug_nonjson: bool = False):
        self.ser = serial.Serial(port, baud, timeout=1)
        self.on_packet = on_packet
        self.debug_nonjson = debug_nonjson
        self._running = True
        self._latest_pkt = queue.Queue(maxsize=1)
        self._thread = threading.Thread(target=self._read_loop, daemon=True)
        self._thread.start()

    # LED control methods
    def rgb(self, r: int, g: int, b: int) -> None:
        r = max(0, min(255, int(r)))
        g = max(0, min(255, int(g)))
        b = max(0, min(255, int(b)))
        self._send("RGB={},{},{}".format(r, g, b))

    def red_LED(self) -> None:
        self.rgb(255, 0, 0)

    def yellow_LED(self) -> None:
        self.rgb(255, 255, 0)

    def green_LED(self) -> None:
        self.rgb(0, 255, 0)

    def off(self) -> None:
        self.rgb(0, 0, 0)

    def get_state(self) -> Optional[SensorPacket]:
        try:
            value = self._latest_pkt.get(timeout=2)
            self._latest_pkt.task_done()
            return value
        except queue.Empty:
            return None

    def _send(self, msg: str) -> None:
        if not msg.endswith("\n"):
            msg += "\n"
        self.ser.write(msg.encode("utf-8"))

    def _set_latest_package(self, pkt: SensorPacket) -> None:
        clear_queue(self._latest_pkt)
        self._latest_pkt.put(pkt, block=False)

    def _read_loop(self) -> None:
        while self._running:
            raw = self.ser.readline()
            if not raw:
                continue
            line = raw.decode(errors="replace").strip()
            pkt = parse_packet(line)
            if pkt is not None:
                if self.on_packet:
                    self.on_packet(pkt)
                self._set_latest_package(pkt)

    def close(self) -> None:
        self._running = False
        time.sleep(0.1)
        try:
            self.ser.close()
        except Exception:
            pass

class SensorAgent(MQTTBaseAgent):
    def __init__(self):
        super().__init__("sensor")
        self.arduino = None

        # Try to connect to Arduino if enabled
        if USE_ARDUINO:
            try:
                print(f"Connecting to Arduino on {ARDUINO_PORT}...")
                self.arduino = Nano33SenseRev2(ARDUINO_PORT, baud=115200)
                time.sleep(2)  # Wait for Arduino initialization
                print("✓ Arduino connected successfully!")
            except Exception as e:
                print(f"✗ Arduino connection failed: {e}")
                print("  Falling back to CSV mode")
                self.arduino = None
    
    def subscribe_to_topics(self):
        self.connect()
        print("SensorAgent subscribed!")
    
    def read_sensors(self):
        """Read from Arduino if available, otherwise fallback to CSV"""
        if self.arduino and USE_ARDUINO:
            return self.read_arduino_sensors()
        else:
            return self.read_csv_sensors()

    def read_arduino_sensors(self):
        """Read real-time data from Arduino hardware"""
        temps = {}
        humids = {}
        try:
            packet = self.arduino.get_state()
            if packet:
                if packet.hs3003_t_c is not None:
                    temps[ARDUINO_ROOM_NAME] = packet.hs3003_t_c
                if packet.hs3003_h_rh is not None:
                    humids[ARDUINO_ROOM_NAME] = packet.hs3003_h_rh
                print(f"📡 Arduino: T={packet.hs3003_t_c:.1f}°C, H={packet.hs3003_h_rh:.1f}%")
            else:
                print("⚠️  No Arduino data available (timeout)")
        except Exception as e:
            print(f"✗ Arduino read error: {e}")
        return temps, humids

    def read_csv_sensors(self):
        """Original CSV reading (fallback mode)"""
        temps = {}
        humids = {}
        try:
            with CSV_PATH.open("r") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    if row["sensor_name"] == "temperature":
                        temps[row["room"]] = float(row["value"])
                    elif row["sensor_name"] == "humidity":
                        humids[row["room"]] = float(row["value"])
        except Exception as e:
            print(f"CSV error: {e}")
        return temps, humids
    
    def decide_lights(self, temps, humids): 
        decisions = {}
        for room in temps:  
            temp = temps[room]
            humid = humids.get(room, 0) 
            #Based on the context of your assignment you can set the rule here
            if temp < 15 or temp > 30:
                color = "red"      
            elif humid > 80:
                color = "yellow"   
            else:
                color = "green"   
            
            # Show both values in log
            print(f" {room}: {temp:.1f}°C ({humid:.1f}%) → {color}")
            decisions[room] = color
        return decisions
    
    def run(self):
        try:
            while True:
                print("\n SensorAgent analyzing...")
                temps, humids = self.read_sensors()
                decisions = self.decide_lights(temps, humids)

                # Control Arduino LED if available
                if self.arduino and ARDUINO_ROOM_NAME in decisions:
                    color = decisions[ARDUINO_ROOM_NAME]
                    try:
                        if color == "red":
                            self.arduino.red_LED()
                        elif color == "yellow":
                            self.arduino.yellow_LED()
                        elif color == "green":
                            self.arduino.green_LED()
                        else:
                            self.arduino.off()
                        print(f"💡 Arduino LED → {color}")
                    except Exception as e:
                        print(f"✗ LED control error: {e}")

                payload = json.dumps({
                    "from": "sensor",
                    "timestamp": time.time(),
                    "light_commands": decisions,
                    "sensors": {"temps": temps, "humids": humids}
                })

                self.client.publish(LIGHT_COMMANDS_TOPIC, payload, qos=1)
                print(f" MQTT → LightController: {decisions}")

                time.sleep(15)
        except KeyboardInterrupt:
            print("\n SensorAgent stopped")
        finally:
            # Cleanup Arduino connection
            if self.arduino:
                print("Closing Arduino connection...")
                try:
                    self.arduino.off()  # Turn off LED
                    self.arduino.close()
                except:
                    pass
            self.disconnect()
