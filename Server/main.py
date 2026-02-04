from fastmcp import FastMCP  # This is the MCP Library

from dataclasses import dataclass, asdict
from datetime import datetime, timezone
import json
import serial
import threading
import time
import queue
import logging
import csv
import os

from typing import Optional, Callable, Any, Dict, List

logger = logging.getLogger("devaiot-mcp")
logger.setLevel(logging.DEBUG)


PORT = "COM3"  # Change to your COM port


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

    # HS3003
    hs3003_t_c: Optional[float] = None
    hs3003_h_rh: Optional[float] = None

    # LPS22HB
    lps22hb_p_kpa: Optional[float] = None
    lps22hb_t_c: Optional[float] = None

    # APDS9960
    apds_prox: Optional[int] = None
    apds_color: Optional[ApdsColor] = None
    apds_gesture: Optional[int] = None  # raw code

    # IMU
    acc_g: Optional[Vec3] = None
    gyro_dps: Optional[Vec3] = None
    mag_uT: Optional[Vec3] = None


@dataclass(frozen=True)
class LTESignalRecord:
    """Single CSV record from CRAWDAD Salzburg dataset"""

    timestamp: int  # Unix timestamp
    rsrp: int
    rsrq: int
    rssi: int
    sinr: int


@dataclass
class ProcessedRecord:
    """Single processed CSV record from Arduino"""

    received_at: datetime  # When Python received it
    timestamp: int  # Original CSV timestamp (Unix)
    latitude: float  # GPS latitude (degrees)
    longitude: float  # GPS longitude (degrees)
    elevation: float  # Altitude above sea level (meters)
    pci: int  # Physical Cell Identity (0-503)
    cell_id: int  # Cell Tower ID
    rsrp: int
    rsrq: int
    rssi: int
    sinr: int
    is_anomaly: bool
    record_num: int  # Sequential number from Arduino
    rssi_is_calculated: bool = False  # Flag if RSSI was calculated by Arduino


def parse_packet(line: str) -> Optional[SensorPacket]:
    try:
        obj = json.loads(line)  # type: Dict[str, Any]
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


def parse_processed_record(line: str) -> Optional[ProcessedRecord]:
    """Parse individual processed record from Arduino"""
    try:
        obj = json.loads(line)  # type: Dict[str, Any]
        if obj.get("type") != "PROCESSED":
            return None

        return ProcessedRecord(
            received_at=datetime.now(timezone.utc),
            timestamp=obj["timestamp"],
            latitude=obj["latitude"],
            longitude=obj["longitude"],
            elevation=obj["elevation"],
            pci=obj["pci"],
            cell_id=obj["cell_id"],
            rsrp=obj["rsrp"],
            rsrq=obj["rsrq"],
            rssi=obj["rssi"],
            sinr=obj["sinr"],
            is_anomaly=obj["is_anomaly"],
            record_num=obj["record_num"],
            rssi_is_calculated=obj.get("rssi_is_calculated", False),
        )
    except Exception:
        return None


def clear_queue(q: queue.Queue):
    while True:
        try:
            q.get_nowait()
            q.task_done()
        except queue.Empty:
            break


class Nano33SenseRev2:
    def __init__(
        self,
        port: str,
        baud: int = 115200,
        on_packet: Optional[Callable[[SensorPacket], None]] = None,
        on_processed_record: Optional[Callable[[ProcessedRecord], None]] = None,
        debug_nonjson: bool = False,
    ):
        self.ser = serial.Serial(port, baud, timeout=1)
        self.on_packet = on_packet
        self.on_processed_record = on_processed_record
        self.debug_nonjson = debug_nonjson
        self._running = True

        self._latest_pkt = queue.Queue(maxsize=1)

        self._thread = threading.Thread(target=self._read_loop, daemon=True)
        self._thread.start()

    # ----- commands -----
    def led_on(self) -> None:
        self._send("LED=ON")

    def led_off(self) -> None:
        self._send("LED=OFF")

    def rgb(self, r: int, g: int, b: int) -> None:
        r = max(0, min(255, int(r)))
        g = max(0, min(255, int(g)))
        b = max(0, min(255, int(b)))
        self._send("RGB={},{},{}".format(r, g, b))

    def red_LED(self) -> None:
        self.rgb(255, 0, 0)

    # TODO: Implement blue led
    def blue_LED(self) -> None:
        self.rgb(0, 0, 255)

    def yellow_LED(self) -> None:
        self.rgb(255, 255, 0)

    def off(self) -> None:
        self.rgb(0, 0, 0)

    def get_state(self) -> Optional[SensorPacket]:
        try:
            value = self._latest_pkt.get(timeout=2)
            self._latest_pkt.task_done()
            return value
        except queue.Empty:
            return None

    # ----- internals -----
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

            # Try parsing as processed record first
            processed = parse_processed_record(line)
            if processed is not None:
                if self.on_processed_record:
                    self.on_processed_record(processed)
                continue

            # Try parsing as sensor packet
            pkt = parse_packet(line)
            if pkt is not None:
                if self.on_packet:
                    self.on_packet(pkt)
                self._set_latest_package(pkt)

            else:
                if self.debug_nonjson:
                    logging.info("NONJSON: " + str(line))
                    pass

    def close(self) -> None:
        self._running = False
        time.sleep(0.1)
        try:
            self.ser.close()
        except Exception:
            pass


class StreamController:
    """Controls CSV data streaming to Arduino and manages processed records"""

    def __init__(self, board: Nano33SenseRev2, csv_path: str):
        self.board = board
        self.csv_path = csv_path
        self.streaming = False
        self.stream_thread = None
        self.processed_records: List[ProcessedRecord] = []
        self._stop_event = threading.Event()
        self._lock = threading.Lock()
        self._records_sent = 0
        self._rate_limit = 20

        # Register callback for processed records
        self.board.on_processed_record = self._on_processed_record

    def _on_processed_record(self, record: ProcessedRecord):
        """Callback when processed record is received from Arduino"""
        with self._lock:
            self.processed_records.append(record)
            # Keep only last 10000 records (circular buffer)
            if len(self.processed_records) > 10000:
                self.processed_records.pop(0)
            logger.info(
                f"Received processed record #{record.record_num}: RSRP={record.rsrp}, SINR={record.sinr}, anomaly={record.is_anomaly}"
            )

    def _parse_timestamp(self, time_str: str) -> int:
        """Convert timestamp string to Unix timestamp"""
        try:
            dt = datetime.strptime(time_str, "%Y-%m-%d %H:%M:%S")
            return int(dt.timestamp())
        except Exception as e:
            logger.warning(f"Failed to parse timestamp '{time_str}': {e}")
            return 0

    def _stream_worker(self):
        """Background thread that streams CSV data to Arduino"""
        try:
            if not os.path.exists(self.csv_path):
                logger.error(f"CSV file not found: {self.csv_path}")
                return

            with open(self.csv_path, "r") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    if self._stop_event.is_set():
                        break

                    try:
                        # Parse CSV row - extract all fields
                        timestamp = self._parse_timestamp(row["Time"])

                        # Geographic fields (NEW)
                        latitude = float(row["Latitude"]) if row["Latitude"] else 0.0
                        longitude = float(row["Longitude"]) if row["Longitude"] else 0.0
                        elevation = float(row["Elevation"]) if row["Elevation"] else 0.0
                        pci = int(float(row["PCI"])) if row["PCI"] else 0
                        cell_id = int(float(row["Cell_Id"])) if row["Cell_Id"] else 0

                        # Signal quality fields
                        rsrp = int(float(row["RSRP"])) if row["RSRP"] else 0
                        rsrq = int(float(row["RSRQ"])) if row["RSRQ"] else 0
                        rssi = int(float(row["RSSI"])) if row["RSSI"] else 0
                        sinr = int(float(row["SINR"])) if row["SINR"] else 0

                        # Format and send DATA command with all 10 fields
                        msg = f"DATA={timestamp},{latitude},{longitude},{elevation},{pci},{cell_id},{rsrp},{rsrq},{rssi},{sinr}\n"
                        self.board._send(msg)

                        with self._lock:
                            self._records_sent += 1

                        # Rate limiting
                        time.sleep(1.0 / self._rate_limit)

                    except Exception as e:
                        logger.warning(f"Failed to process CSV row: {e}")
                        continue

            logger.info(f"Finished streaming {self._records_sent} records")

        except Exception as e:
            logger.error(f"Stream worker error: {e}")
        finally:
            with self._lock:
                self.streaming = False

    def start_stream(self, rate_limit: int = 20) -> Dict[str, Any]:
        """Start streaming CSV data to Arduino"""
        with self._lock:
            if self.streaming:
                return {"error": "Stream already active"}

            self._rate_limit = min(max(1, rate_limit), 50)  # Clamp between 1-50
            self._records_sent = 0
            self._stop_event.clear()
            self.streaming = True

        # Send STREAM=START command
        self.board._send("STREAM=START\n")
        time.sleep(0.1)  # Wait for acknowledgment

        # Start streaming thread
        self.stream_thread = threading.Thread(target=self._stream_worker, daemon=True)
        self.stream_thread.start()

        return {"status": "started", "rate_limit": self._rate_limit}

    def stop_stream(self) -> Dict[str, Any]:
        """Stop streaming and retrieve final statistics"""
        with self._lock:
            if not self.streaming:
                return {"error": "No active stream"}

            self._stop_event.set()

        # Wait for thread to finish (max 5 seconds)
        if self.stream_thread:
            self.stream_thread.join(timeout=5.0)

        # Send STREAM=STOP command
        self.board._send("STREAM=STOP\n")
        time.sleep(0.2)  # Wait for final acknowledgment

        with self._lock:
            stats = {
                "status": "stopped",
                "total_records": self._records_sent,
                "records_received": len(self.processed_records),
            }

        return stats

    def get_status(self) -> Dict[str, Any]:
        """Get current streaming status"""
        with self._lock:
            return {
                "active": self.streaming,
                "sent": self._records_sent,
                "results": len(self.processed_records),
                "rate_limit": self._rate_limit,
            }

    def get_latest_results(self, count: int = 10) -> List[ProcessedRecord]:
        """Get the most recent N processed records"""
        with self._lock:
            return self.processed_records[-count:] if self.processed_records else []

    def query_by_quality(
        self, min_rsrp: int = -80, min_sinr: int = 15
    ) -> List[ProcessedRecord]:
        """Query records filtered by signal quality thresholds"""
        with self._lock:
            return [
                r
                for r in self.processed_records
                if r.rsrp >= min_rsrp and r.sinr >= min_sinr
            ]

    def get_anomaly_records(self) -> List[ProcessedRecord]:
        """Get all records flagged as anomalies"""
        with self._lock:
            return [r for r in self.processed_records if r.is_anomaly]

    def get_signal_quality_stats(self) -> Dict[str, Any]:
        """Compute aggregated statistics from stored individual records"""
        with self._lock:
            if not self.processed_records:
                return {"error": "No processed records available"}

            total_count = len(self.processed_records)
            avg_rsrp = sum(r.rsrp for r in self.processed_records) / total_count
            avg_rsrq = sum(r.rsrq for r in self.processed_records) / total_count
            avg_rssi = sum(r.rssi for r in self.processed_records) / total_count
            avg_sinr = sum(r.sinr for r in self.processed_records) / total_count

            anomaly_count = sum(1 for r in self.processed_records if r.is_anomaly)
            anomaly_rate = anomaly_count / total_count if total_count > 0 else 0.0

            return {
                "total_records": total_count,
                "avg_rsrp": round(avg_rsrp, 2),
                "avg_rsrq": round(avg_rsrq, 2),
                "avg_rssi": round(avg_rssi, 2),
                "avg_sinr": round(avg_sinr, 2),
                "min_rsrp": min(r.rsrp for r in self.processed_records),
                "max_rsrp": max(r.rsrp for r in self.processed_records),
                "min_sinr": min(r.sinr for r in self.processed_records),
                "max_sinr": max(r.sinr for r in self.processed_records),
                "anomaly_count": anomaly_count,
                "anomaly_rate": round(anomaly_rate, 4),
            }


def show(p: SensorPacket) -> None:
    return
    logger.info(
        "{} | T={}C H={}% P={}kPa acc={} gyro={} mag={} prox={} color={} gest={}".format(
            p.timestamp.isoformat(),
            None if p.hs3003_t_c is None else round(p.hs3003_t_c, 2),
            None if p.hs3003_h_rh is None else round(p.hs3003_h_rh, 1),
            None if p.lps22hb_p_kpa is None else round(p.lps22hb_p_kpa, 3),
            p.acc_g,
            p.gyro_dps,
            p.mag_uT,
            p.apds_prox,
            p.apds_color,
            p.apds_gesture,
        )
    )


board = Nano33SenseRev2(PORT, on_packet=show, debug_nonjson=True)  # <-- vaihda portti

# Get the CSV path (in parent directory of Server/)
CSV_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "Crawdad.csv")
stream_controller = StreamController(board, CSV_PATH)

ArduinoMCP = FastMCP("Arduino Servers")


@ArduinoMCP.tool
def red_led_ON():
    """Turns on red LED in the Arduino"""
    board.red_LED()
    time.sleep(2)
    board.off()
    return "Red LED could not be turned on – exept for two seconds"


@ArduinoMCP.tool
def led_OFF():
    """Turns off all LEDs in the Arduino"""
    board.off()
    return "All LEDs OFF"


@ArduinoMCP.tool
def get_current_temperature():
    """Gets the most recent temperature from the Arduino"""
    state = board.get_state()
    if state:
        return str(state.hs3003_t_c) + " degrees celsius"
    else:
        return None


@ArduinoMCP.tool
def get_current_gyro():
    """Gets the most recent temperature from the Arduino"""
    state = board.get_state()
    if state:
        return str(state.gyro_dps)
    else:
        return None


@ArduinoMCP.tool
def get_current_accelerometer():
    """Gets the most recent temperature from the Arduino"""
    state = board.get_state()
    if state:
        return str(state.acc_g)
    else:
        return None


@ArduinoMCP.tool
def blue_led_ON():
    """Turns on blue LED in the Arduino"""
    board.blue_LED()
    time.sleep(2)
    board.off()
    return "Blue LED could not be turned on – exept for two seconds"


@ArduinoMCP.tool
def get_current_humidity():
    """Gets the most recent humidity reading from the Arduino"""
    state = board.get_state()
    if state:
        return str(state.hs3003_h_rh) + "% relative humidity"
    else:
        return None


# --- CSV Streaming Control Tools ---


@ArduinoMCP.tool
def start_csv_stream(rate_limit: int = 20):
    """
    Start streaming LTE signal data from Crawdad.csv to Arduino for processing.

    Args:
        rate_limit: Records per second to stream (default 20, max 50)

    Returns:
        Status message indicating stream started
    """
    result = stream_controller.start_stream(rate_limit)
    if "error" in result:
        return f"Error: {result['error']}"
    return f"Started streaming CSV data at {result['rate_limit']} records/sec"


@ArduinoMCP.tool
def stop_csv_stream():
    """
    Stop the CSV data stream and retrieve final processing results.

    Returns:
        Summary of streaming session
    """
    result = stream_controller.stop_stream()
    if "error" in result:
        return f"Error: {result['error']}"
    return f"Stopped stream. Sent {result['total_records']} records to Arduino, received {result['records_received']} processed records back"


@ArduinoMCP.tool
def get_stream_status():
    """
    Check if CSV streaming is currently active and get current progress.

    Returns:
        Current streaming status and progress
    """
    status = stream_controller.get_status()
    return f"Streaming: {status['active']}, Records sent: {status['sent']}, Results received: {status['results']}, Rate: {status['rate_limit']}/sec"


# --- CSV Data Query Tools ---


@ArduinoMCP.tool
def get_latest_results(count: int = 5):
    """
    Retrieve the most recent processed individual CSV records from Arduino.
    Each record contains raw signal values (RSRP, RSRQ, RSSI, SINR) and anomaly flag.

    Args:
        count: Number of recent records to retrieve (default 5, max 100)

    Returns:
        JSON array of recent processed records with raw signal data
    """
    count = min(max(1, count), 100)  # Clamp between 1-100
    records = stream_controller.get_latest_results(count)

    if not records:
        return "No processed records available yet. Start streaming first with start_csv_stream()"

    # Convert to JSON-serializable format
    records_list = [asdict(r) for r in records]
    # Convert datetime to ISO format string
    for r in records_list:
        r["received_at"] = r["received_at"].isoformat()

    return json.dumps(records_list, indent=2)


@ArduinoMCP.tool
def query_results_by_quality(min_rsrp: int = -80, min_sinr: int = 15):
    """
    Query individual records filtered by signal quality thresholds.

    Args:
        min_rsrp: Minimum RSRP in dBm (default -80)
        min_sinr: Minimum SINR in dB (default 15)

    Returns:
        Count and sample of filtered records meeting quality criteria
    """
    records = stream_controller.query_by_quality(min_rsrp, min_sinr)

    if not records:
        return f"No records found with RSRP >= {min_rsrp} dBm and SINR >= {min_sinr} dB"

    # Return count and first 10 records as sample
    sample = records[:10]
    sample_list = [asdict(r) for r in sample]
    for r in sample_list:
        r["received_at"] = r["received_at"].isoformat()

    return (
        f"Found {len(records)} records with good signal quality (RSRP >= {min_rsrp} dBm, SINR >= {min_sinr} dB). Sample of first 10:\n"
        + json.dumps(sample_list, indent=2)
    )


@ArduinoMCP.tool
def get_anomaly_records():
    """
    Get all individual records flagged as anomalies (poor signal quality).
    Anomalies are defined as RSRP < -100 dBm OR SINR < 0 dB.

    Returns:
        JSON array of all anomaly records with their signal data
    """
    anomalies = stream_controller.get_anomaly_records()

    if not anomalies:
        return "No anomalies detected yet. Anomalies are defined as RSRP < -100 dBm or SINR < 0 dB"

    # Convert to JSON-serializable format
    anomalies_list = [asdict(r) for r in anomalies]
    for r in anomalies_list:
        r["received_at"] = r["received_at"].isoformat()

    return f"Found {len(anomalies)} anomaly records:\n" + json.dumps(
        anomalies_list, indent=2
    )


@ArduinoMCP.tool
def get_signal_quality_stats():
    """
    Compute and return aggregated statistics from all stored individual records.
    Includes averages, min/max values, and anomaly rate.

    Returns:
        Aggregated statistics computed from individual records
    """
    stats = stream_controller.get_signal_quality_stats()

    if "error" in stats:
        return (
            "No statistics available yet. Start streaming first with start_csv_stream()"
        )

    return json.dumps(stats, indent=2)


@ArduinoMCP.tool
def get_rssi_calculation_stats():
    """
    Get statistics about calculated vs measured RSSI values.

    Shows how many RSSI values were calculated by Arduino vs measured from the CSV,
    and provides quality metrics for the calculated values.

    Returns:
        Statistics JSON with counts, percentages, and average values
    """
    with stream_controller._lock:
        records = stream_controller.processed_records

        if not records:
            return "No records available yet. Start streaming first with start_csv_stream()"

        measured = [r for r in records if not r.rssi_is_calculated]
        calculated = [r for r in records if r.rssi_is_calculated]

        stats = {
            "total_records": len(records),
            "measured_rssi_count": len(measured),
            "calculated_rssi_count": len(calculated),
            "calculated_percentage": (
                round(len(calculated) / len(records) * 100, 2) if records else 0
            ),
            "measured_rssi_avg": (
                round(sum(r.rssi for r in measured) / len(measured), 2)
                if measured
                else None
            ),
            "calculated_rssi_avg": (
                round(sum(r.rssi for r in calculated) / len(calculated), 2)
                if calculated
                else None
            ),
            "formula": "RSSI = RSRP - RSRQ + 14 (calculated on Arduino)",
        }

        return json.dumps(stats, indent=2)


# Can be used for testing and debugging
def test():
    """Gets the most recent temperature from the Arduino"""
    state = board.get_state()
    if state:
        return str(state.acc_g)
    else:
        return None


if __name__ == "__main__":

    try:

        # For demonstrating that Arduino is connected
        board.red_LED()
        time.sleep(1)
        board.yellow_LED()
        time.sleep(1)
        board.off()

        # Runs the MCP server
        ArduinoMCP.run()

        # If you want to host via http:
        # ArduinoMCP.run(transport="http", host="127.0.0.1", port=8000)
    except KeyboardInterrupt:
        board.close()
        pass
    finally:
        board.close()
