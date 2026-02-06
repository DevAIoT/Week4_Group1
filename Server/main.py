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
import folium
import duckdb
import tempfile
import webbrowser
from pathlib import Path

from typing import Optional, Callable, Any, Dict, List, Tuple

logger = logging.getLogger("devaiot-mcp")
logger.setLevel(logging.DEBUG)


PORT = "COM5"  # Change to your COM port


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
        self.ser = None
        self.connected = False
        
        try:
            self.ser = serial.Serial(port, baud, timeout=1)
            self.connected = True
            logger.info(f"Successfully connected to Arduino on {port}")
        except serial.SerialException as e:
            logger.warning(f"Failed to connect to Arduino on {port}: {e}")
            logger.warning("Continuing without Arduino connection")
        except Exception as e:
            logger.warning(f"Unexpected error connecting to Arduino: {e}")
            logger.warning("Continuing without Arduino connection")
        
        self.on_packet = on_packet
        self.on_processed_record = on_processed_record
        self.debug_nonjson = debug_nonjson
        self._running = True

        self._latest_pkt = queue.Queue(maxsize=1)

        if self.connected:
            self._thread = threading.Thread(target=self._read_loop, daemon=True)
            self._thread.start()
        else:
            self._thread = None

    # ----- commands -----
    def led_on(self) -> None:
        if self.connected:
            self._send("LED=ON")

    def led_off(self) -> None:
        if self.connected:
            self._send("LED=OFF")

    def rgb(self, r: int, g: int, b: int) -> None:
        if not self.connected:
            return
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
        if not self.connected or self.ser is None:
            return
        if not msg.endswith("\n"):
            msg += "\n"
        try:
            self.ser.write(msg.encode("utf-8"))
        except Exception as e:
            logger.warning(f"Error sending message to Arduino: {e}")

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
        if self._thread is not None:
            self._thread.join(timeout=2)
        if self.ser is not None and self.connected:
            try:
                self.ser.close()
                self.connected = False
            except Exception as e:
                logger.warning(f"Error closing serial connection: {e}")


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


@ArduinoMCP.tool
def retrieve_csv_data(
    limit: int = 100,
    offset: int = 0,
    start_time: str = "",
    end_time: str = "",
    min_latitude: float = -90.0,
    max_latitude: float = 90.0,
    min_longitude: float = -180.0,
    max_longitude: float = 180.0,
    min_rsrp: int = -200,
    max_rsrp: int = 0,
    min_rsrq: int = -50,
    max_rsrq: int = 0,
    min_rssi: int = -200,
    max_rssi: int = 0,
    min_sinr: int = -50,
    max_sinr: int = 100,
    pci: int = -1,
    cell_id: int = -1,
    rssi_generated_only: bool = False,
) -> str:
    """
    Retrieve and filter data from Crawdad_filled.csv with advanced filtering.

    Args:
        limit: Maximum number of records to return (default 100, max 10000)
        offset: Number of records to skip (for pagination)
        start_time: Filter records after this time (format: "YYYY-MM-DD HH:MM:SS")
        end_time: Filter records before this time (format: "YYYY-MM-DD HH:MM:SS")
        min_latitude: Minimum latitude filter
        max_latitude: Maximum latitude filter
        min_longitude: Minimum longitude filter
        max_longitude: Maximum longitude filter
        min_rsrp: Minimum RSRP threshold (dBm)
        max_rsrp: Maximum RSRP threshold (dBm)
        min_rsrq: Minimum RSRQ threshold (dB)
        max_rsrq: Maximum RSRQ threshold (dB)
        min_rssi: Minimum RSSI threshold (dBm)
        max_rssi: Maximum RSSI threshold (dBm)
        min_sinr: Minimum SINR threshold (dB)
        max_sinr: Maximum SINR threshold (dB)
        pci: Filter by specific PCI (-1 for all)
        cell_id: Filter by specific Cell ID (-1 for all)
        rssi_generated_only: If True, only return records with RSSI_Generated=1.0

    Returns:
        JSON array of filtered records with metadata
    """
    # Define CSV path
    csv_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "Crawdad_filled.csv")

    # Validate inputs
    limit = min(max(1, limit), 10000)
    offset = max(0, offset)

    # Check if CSV file exists
    if not os.path.exists(csv_path):
        return json.dumps({
            "status": "error",
            "message": f"CSV file not found: {csv_path}"
        }, indent=2)

    # Validate time formats if provided
    if start_time:
        try:
            datetime.strptime(start_time, "%Y-%m-%d %H:%M:%S")
        except ValueError as e:
            return json.dumps({
                "status": "error",
                "message": f"Invalid start_time format: {e}. Expected 'YYYY-MM-DD HH:MM:SS'"
            }, indent=2)

    if end_time:
        try:
            datetime.strptime(end_time, "%Y-%m-%d %H:%M:%S")
        except ValueError as e:
            return json.dumps({
                "status": "error",
                "message": f"Invalid end_time format: {e}. Expected 'YYYY-MM-DD HH:MM:SS'"
            }, indent=2)

    # Use DuckDB for efficient CSV querying
    try:
        # Initialize DuckDB connection (in-memory)
        conn = duckdb.connect(':memory:')

        # Build dynamic SQL query with WHERE clauses
        where_clauses = []

        # Time range filters
        if start_time:
            where_clauses.append(f"Time >= '{start_time}'")
        if end_time:
            where_clauses.append(f"Time <= '{end_time}'")

        # Geographic bounds
        if min_latitude != -90.0:
            where_clauses.append(f"Latitude >= {min_latitude}")
        if max_latitude != 90.0:
            where_clauses.append(f"Latitude <= {max_latitude}")
        if min_longitude != -180.0:
            where_clauses.append(f"Longitude >= {min_longitude}")
        if max_longitude != 180.0:
            where_clauses.append(f"Longitude <= {max_longitude}")

        # Signal quality thresholds
        if min_rsrp != -200:
            where_clauses.append(f"RSRP >= {min_rsrp}")
        if max_rsrp != 0:
            where_clauses.append(f"RSRP <= {max_rsrp}")
        if min_rsrq != -50:
            where_clauses.append(f"RSRQ >= {min_rsrq}")
        if max_rsrq != 0:
            where_clauses.append(f"RSRQ <= {max_rsrq}")
        if min_rssi != -200:
            where_clauses.append(f"RSSI >= {min_rssi}")
        if max_rssi != 0:
            where_clauses.append(f"RSSI <= {max_rssi}")
        if min_sinr != -50:
            where_clauses.append(f"SINR >= {min_sinr}")
        if max_sinr != 100:
            where_clauses.append(f"SINR <= {max_sinr}")

        # Cell information filters
        if pci != -1:
            where_clauses.append(f"CAST(PCI AS INTEGER) = {pci}")
        if cell_id != -1:
            where_clauses.append(f"CAST(Cell_Id AS INTEGER) = {cell_id}")

        # RSSI_Generated filter
        if rssi_generated_only:
            where_clauses.append("RSSI_Generated = 1.0")

        # Build WHERE clause
        where_sql = ""
        if where_clauses:
            where_sql = " WHERE " + " AND ".join(where_clauses)

        # Get total count of matched records
        count_sql = f"SELECT COUNT(*) FROM read_csv_auto('{csv_path}'){where_sql}"
        total_matched = conn.execute(count_sql).fetchone()[0]

        # Get paginated records
        data_sql = f"SELECT * FROM read_csv_auto('{csv_path}'){where_sql} LIMIT {limit} OFFSET {offset}"
        result = conn.execute(data_sql).fetchall()
        columns = [desc[0] for desc in conn.description]

        # Convert to list of dicts
        paginated_records = []
        for row in result:
            record = {}
            for i, col in enumerate(columns):
                value = row[i]
                # Cast to appropriate types
                if col == "Time":
                    # Convert datetime to string format
                    record[col] = value.strftime("%Y-%m-%d %H:%M:%S") if isinstance(value, datetime) else str(value)
                elif col in ["Latitude", "Longitude", "Elevation", "RSSI_Generated"]:
                    record[col] = float(value) if value is not None else 0.0
                elif col in ["PCI", "Cell_Id", "RSRP", "RSRQ", "RSSI", "SINR"]:
                    record[col] = int(float(value)) if value is not None else 0
                else:
                    record[col] = value
            paginated_records.append(record)

        conn.close()

    except Exception as e:
        return json.dumps({
            "status": "error",
            "message": f"Error querying CSV file: {e}"
        }, indent=2)

    # Build filters_applied summary
    filters_applied = {}

    if start_time or end_time:
        time_range = f"{start_time or 'any'} to {end_time or 'any'}"
        filters_applied["time_range"] = time_range

    if min_latitude != -90.0 or max_latitude != 90.0 or min_longitude != -180.0 or max_longitude != 180.0:
        filters_applied["location_bounds"] = {
            "latitude": [min_latitude, max_latitude],
            "longitude": [min_longitude, max_longitude]
        }

    if min_rsrp != -200 or max_rsrp != 0 or min_rsrq != -50 or max_rsrq != 0 or min_rssi != -200 or max_rssi != 0 or min_sinr != -50 or max_sinr != 100:
        filters_applied["signal_quality"] = {
            "rsrp_range": [min_rsrp, max_rsrp],
            "rsrq_range": [min_rsrq, max_rsrq],
            "rssi_range": [min_rssi, max_rssi],
            "sinr_range": [min_sinr, max_sinr]
        }

    if pci != -1:
        filters_applied["pci"] = pci

    if cell_id != -1:
        filters_applied["cell_id"] = cell_id

    if rssi_generated_only:
        filters_applied["rssi_generated_only"] = True

    # Return JSON response
    result = {
        "status": "success",
        "total_matched": total_matched,
        "returned_count": len(paginated_records),
        "offset": offset,
        "limit": limit,
        "filters_applied": filters_applied,
        "records": paginated_records
    }

    return json.dumps(result, indent=2)


@ArduinoMCP.tool
def query_csv_data(sql_query: str, limit: int = 256) -> str:
    """
    Execute a custom SQL query on the Crawdad_filled.csv dataset using DuckDB.
    
    Only SELECT statements are allowed for safety. The CSV file is automatically 
    available as a table that can be queried directly.
    
    Args:
        sql_query: Custom SQL SELECT query to execute. Must start with SELECT.
        limit: Maximum number of rows to return (default 256, max 10000)
    
    Example queries:
        - "SELECT Time, Latitude, Longitude, RSRP FROM crawdad WHERE RSRP > -80"
        - "SELECT AVG(RSRP), COUNT(*) FROM crawdad GROUP BY PCI"
        - "SELECT * FROM crawdad WHERE Latitude BETWEEN 47.0 AND 47.1 ORDER BY Time LIMIT 50"
        - "SELECT Time, RSRP, RSSI, (RSRP - RSRQ + 14) as calculated_rssi FROM crawdad WHERE RSSI_Generated = 1.0"
        - "SELECT PCI, AVG(SINR) as avg_sinr, COUNT(*) as measurements FROM crawdad GROUP BY PCI HAVING COUNT(*) > 100"
    
    Returns:
        JSON with query results, metadata, and execution status
    """
    # Validate inputs
    limit = min(max(1, limit), 10000)
    sql_query = sql_query.strip()
    
    # Check if query starts with SELECT (case-insensitive)
    if not sql_query.lower().startswith('select'):
        return json.dumps({
            "status": "error",
            "message": "Only SELECT queries are allowed for security reasons. Query must start with 'SELECT'."
        }, indent=2)
    
    # Define CSV path
    csv_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "Crawdad_filled.csv")
    
    # Check if CSV file exists
    if not os.path.exists(csv_path):
        return json.dumps({
            "status": "error", 
            "message": f"CSV file not found: {csv_path}"
        }, indent=2)
    
    try:
        # Initialize DuckDB connection (in-memory)
        conn = duckdb.connect(':memory:')
        
        # Create a virtual table alias for easier querying
        # Replace common table references with the actual CSV path
        processed_query = sql_query
        
        # Replace common table names with the actual CSV file reference
        table_aliases = ['crawdad', 'data', 'csv', 'table']
        csv_reference = f"read_csv_auto('{csv_path}')"
        
        for alias in table_aliases:
            # Case-insensitive replacement
            import re
            pattern = r'\b' + re.escape(alias) + r'\b'
            processed_query = re.sub(pattern, csv_reference, processed_query, flags=re.IGNORECASE)
        
        # If no table alias was found, assume they want to query the entire CSV
        if not any(alias.lower() in processed_query.lower() for alias in table_aliases):
            # Look for FROM clause and replace with CSV reference
            from_match = re.search(r'\bfrom\s+(\w+)', processed_query, re.IGNORECASE)
            if from_match:
                table_name = from_match.group(1)
                processed_query = re.sub(
                    r'\bfrom\s+' + re.escape(table_name) + r'\b', 
                    f'FROM {csv_reference}', 
                    processed_query, 
                    flags=re.IGNORECASE
                )
        
        # Add LIMIT if not already present and limit is specified
        if limit < 10000 and 'limit' not in processed_query.lower():
            processed_query += f" LIMIT {limit}"
        
        # Execute the query
        result = conn.execute(processed_query).fetchall()
        columns = [desc[0] for desc in conn.description]
        
        # Convert to list of dicts
        records = []
        for row in result:
            record = {}
            for i, col in enumerate(columns):
                value = row[i]
                # Handle datetime conversion
                if isinstance(value, datetime):
                    record[col] = value.strftime("%Y-%m-%d %H:%M:%S")
                else:
                    record[col] = value
            records.append(record)
        
        conn.close()
        
        # Return successful result
        return json.dumps({
            "status": "success", 
            "query_executed": processed_query,
            "columns": columns,
            "row_count": len(records),
            "limit_applied": limit,
            "records": records
        }, indent=2)
        
    except Exception as e:
        return json.dumps({
            "status": "error",
            "message": f"Query execution failed: {str(e)}",
            "query_attempted": processed_query
        }, indent=2)


def get_color_for_metric(value: float, metric: str) -> str:
    """Map signal quality metric to HTML color code"""
    if metric == "rsrp":
        if value >= -80:
            return "#00ff00"  # Green - excellent signal
        elif value >= -100:
            return "#ffff00"  # Yellow - fair signal
        else:
            return "#ff0000"  # Red - poor signal
    elif metric == "sinr":
        if value >= 15:
            return "#00ff00"  # Green - excellent
        elif value >= 0:
            return "#ffff00"  # Yellow - fair
        else:
            return "#ff0000"  # Red - poor
    elif metric == "rsrq":
        if value >= -10:
            return "#00ff00"  # Green - excellent
        elif value >= -15:
            return "#ffff00"  # Yellow - fair
        else:
            return "#ff0000"  # Red - poor
    elif metric == "rssi":
        if value >= -65:
            return "#00ff00"  # Green - excellent
        elif value >= -85:
            return "#ffff00"  # Yellow - fair
        else:
            return "#ff0000"  # Red - poor
    elif metric == "anomaly":
        return "#ff0000" if value else "#00ff00"  # Red if anomaly, green if not
    else:
        return "#0000ff"  # Blue - unknown metric


def _get_record_field(record, field: str):
    """
    Safely access a field from either ProcessedRecord or CSV dict format.

    Args:
        record: Either a ProcessedRecord object or a dict from retrieve_csv_data
        field: Field name (ProcessedRecord attribute name)

    Returns:
        Field value with appropriate type conversion
    """
    # Check if it's a ProcessedRecord (has __dataclass_fields__)
    if hasattr(record, '__dataclass_fields__'):
        return getattr(record, field)

    # Otherwise it's a dict from CSV - map field names
    field_mapping = {
        'latitude': 'Latitude',
        'longitude': 'Longitude',
        'elevation': 'Elevation',
        'rsrp': 'RSRP',
        'rsrq': 'RSRQ',
        'rssi': 'RSSI',
        'sinr': 'SINR',
        'pci': 'PCI',
        'cell_id': 'Cell_Id',
    }

    # Special handling for derived fields
    if field == 'is_anomaly':
        return False  # CSV data has no anomaly detection
    elif field == 'rssi_is_calculated':
        return record.get('RSSI_Generated', 0.0) == 1.0
    elif field == 'timestamp':
        # Parse Time string to Unix timestamp
        time_str = record.get('Time', '')
        try:
            dt = datetime.strptime(time_str, "%Y-%m-%d %H:%M:%S")
            return int(dt.timestamp())
        except (ValueError, AttributeError):
            return int(datetime.now().timestamp())
    elif field == 'record_num':
        # Use pre-computed index from dict
        return record.get('_record_num', 0)

    # Regular field mapping
    csv_field = field_mapping.get(field, field)
    return record.get(csv_field, 0)


def create_popup_html(record) -> str:
    """Generate HTML popup content for a data point"""
    timestamp = _get_record_field(record, 'timestamp')
    timestamp_str = datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d %H:%M:%S")

    record_num = _get_record_field(record, 'record_num')

    html = f"""
    <div style="font-family: monospace; font-size: 12px;">
        <b>Timestamp:</b> {timestamp_str}<br>
        <b>Record #:</b> {record_num}<br>
        <hr style="margin: 5px 0;">
        <b>GPS Coordinates:</b><br>
        &nbsp;&nbsp;Lat: {_get_record_field(record, 'latitude'):.6f}°<br>
        &nbsp;&nbsp;Lon: {_get_record_field(record, 'longitude'):.6f}°<br>
        &nbsp;&nbsp;Elevation: {_get_record_field(record, 'elevation'):.1f}m<br>
        <hr style="margin: 5px 0;">
        <b>Signal Quality:</b><br>
        &nbsp;&nbsp;RSRP: {_get_record_field(record, 'rsrp')} dBm<br>
        &nbsp;&nbsp;RSRQ: {_get_record_field(record, 'rsrq')} dB<br>
        &nbsp;&nbsp;RSSI: {_get_record_field(record, 'rssi')} dBm {("(calc)" if _get_record_field(record, 'rssi_is_calculated') else "(meas)")}<br>
        &nbsp;&nbsp;SINR: {_get_record_field(record, 'sinr')} dB<br>
        <hr style="margin: 5px 0;">
        <b>Cell Info:</b><br>
        &nbsp;&nbsp;PCI: {_get_record_field(record, 'pci')}<br>
        &nbsp;&nbsp;Cell ID: {_get_record_field(record, 'cell_id')}<br>
        <hr style="margin: 5px 0;">
        <b>Anomaly:</b> <span style="color: {'red' if _get_record_field(record, 'is_anomaly') else 'green'}; font-weight: bold;">
        {('YES' if _get_record_field(record, 'is_anomaly') else 'NO')}</span>
    </div>
    """
    return html


def calculate_map_center(records) -> Tuple[float, float]:
    """Calculate geographic centroid for map centering"""
    if not records:
        return (0.0, 0.0)

    avg_lat = sum(_get_record_field(r, 'latitude') for r in records) / len(records)
    avg_lon = sum(_get_record_field(r, 'longitude') for r in records) / len(records)
    return (avg_lat, avg_lon)




@ArduinoMCP.tool
def plot_signal_map(
    color_by: str = "rsrp",
    show_anomalies_only: bool = False,
    max_points: int = 10000,
    output_format: str = "html",
    records_json: str = ""
) -> str:
    """
    Plot GPS data collection path on an interactive map with signal quality visualization.

    Args:
        color_by: Metric for color coding ('rsrp', 'sinr', 'rsrq', 'rssi', 'anomaly')
        show_anomalies_only: If True, only plot anomaly records
        max_points: Maximum points to plot (default 10000)
        output_format: Output format ('html' for interactive)
        records_json: Optional JSON string from retrieve_csv_data. If provided, plots this data
                      instead of Arduino streaming data. Pass the complete JSON output from
                      retrieve_csv_data to visualize filtered CSV data without Arduino streaming.

    Returns:
        JSON with map file path, statistics, and success message
    """
    # Determine data source and track if using CSV format
    using_csv_format = False
    if records_json:
        # Use data from retrieve_csv_data (keep as dicts)
        try:
            data = json.loads(records_json)
            if not isinstance(data, dict):
                return json.dumps({
                    "status": "error",
                    "message": "records_json must be a JSON object with 'status' and 'records' fields, not a list"
                }, indent=2)
            if data.get("status") != "success":
                return json.dumps({
                    "status": "error",
                    "message": f"Input JSON has error status: {data.get('message', 'Unknown error')}"
                }, indent=2)
            records = data["records"]  # Keep as dicts
            using_csv_format = True

            # Add index-based record_num to each dict
            for idx, record in enumerate(records):
                record['_record_num'] = idx + 1
        except (json.JSONDecodeError, KeyError) as e:
            return json.dumps({
                "status": "error",
                "message": f"Invalid records_json format: {e}"
            }, indent=2)
    else:
        # Use existing stream controller data (ProcessedRecord objects)
        with stream_controller._lock:
            records = list(stream_controller.processed_records)

    # Check if we have data
    if not records:
        return json.dumps({
            "status": "error",
            "message": "No records available yet. Start streaming first with start_csv_stream() or pass records_json from retrieve_csv_data()"
        }, indent=2)

    # Filter records
    filtered_records = []
    for record in records:

        # Validate coordinates (skip invalid GPS data)
        lat = _get_record_field(record, 'latitude')
        lon = _get_record_field(record, 'longitude')
        if lat == 0.0 and lon == 0.0:
            continue

        filtered_records.append(record)

    # Limit to max_points by sampling evenly
    if len(filtered_records) > max_points:
        step = len(filtered_records) / max_points
        sampled_records = [filtered_records[int(i * step)] for i in range(max_points)]
        filtered_records = sampled_records

    # Calculate map center
    center_lat, center_lon = calculate_map_center(filtered_records)

    # Create Folium map
    m = folium.Map(
        location=[center_lat, center_lon],
        zoom_start=13,
        tiles="OpenStreetMap"
    )

    # Add polyline showing movement trajectory
    path_coords = [[_get_record_field(r, 'latitude'), _get_record_field(r, 'longitude')] for r in filtered_records]
    folium.PolyLine(
        path_coords,
        color="blue",
        weight=2,
        opacity=0.7,
        popup="Data collection path"
    ).add_to(m)

    # Add circle markers at each point
    anomaly_count = 0
    for record in filtered_records:
        # Get color based on selected metric
        if color_by == "anomaly":
            color = get_color_for_metric(_get_record_field(record, 'is_anomaly'), "anomaly")
        else:
            metric_value = _get_record_field(record, color_by)
            color = get_color_for_metric(metric_value, color_by)

        if _get_record_field(record, 'is_anomaly'):
            anomaly_count += 1

        # Create marker with popup
        folium.CircleMarker(
            location=[_get_record_field(record, 'latitude'), _get_record_field(record, 'longitude')],
            radius=6,
            color=color,
            fill=True,
            fillColor=color,
            fillOpacity=0.7,
            popup=folium.Popup(create_popup_html(record), max_width=300)
        ).add_to(m)

    # Add legend
    legend_html = f"""
    <div style="position: fixed;
                bottom: 50px; right: 50px; width: 200px; height: auto;
                background-color: white; border:2px solid grey; z-index:9999;
                font-size:14px; padding: 10px; border-radius: 5px;">
        <h4 style="margin-top:0;">Signal Quality Legend</h4>
        <p style="margin: 5px 0;"><b>Color by: {color_by.upper()}</b></p>
    """

    if color_by == "rsrp":
        legend_html += """
        <p style="margin: 5px 0;"><span style="color: #00ff00;">&#9679;</span> Excellent (≥ -80 dBm)</p>
        <p style="margin: 5px 0;"><span style="color: #ffff00;">&#9679;</span> Fair (-100 to -80 dBm)</p>
        <p style="margin: 5px 0;"><span style="color: #ff0000;">&#9679;</span> Poor (< -100 dBm)</p>
        """
    elif color_by == "sinr":
        legend_html += """
        <p style="margin: 5px 0;"><span style="color: #00ff00;">&#9679;</span> Excellent (≥ 15 dB)</p>
        <p style="margin: 5px 0;"><span style="color: #ffff00;">&#9679;</span> Fair (0 to 15 dB)</p>
        <p style="margin: 5px 0;"><span style="color: #ff0000;">&#9679;</span> Poor (< 0 dB)</p>
        """
    elif color_by == "rsrq":
        legend_html += """
        <p style="margin: 5px 0;"><span style="color: #00ff00;">&#9679;</span> Excellent (≥ -10 dB)</p>
        <p style="margin: 5px 0;"><span style="color: #ffff00;">&#9679;</span> Fair (-15 to -10 dB)</p>
        <p style="margin: 5px 0;"><span style="color: #ff0000;">&#9679;</span> Poor (< -15 dB)</p>
        """
    elif color_by == "rssi":
        legend_html += """
        <p style="margin: 5px 0;"><span style="color: #00ff00;">&#9679;</span> Excellent (≥ -65 dBm)</p>
        <p style="margin: 5px 0;"><span style="color: #ffff00;">&#9679;</span> Fair (-85 to -65 dBm)</p>
        <p style="margin: 5px 0;"><span style="color: #ff0000;">&#9679;</span> Poor (< -85 dBm)</p>
        """

    legend_html += """
        <p style="margin: 5px 0; margin-top: 10px;"><span style="color: blue;">─</span> Collection path</p>
    </div>
    """

    m.get_root().html.add_child(folium.Element(legend_html))

    # Save to temp file with timestamp
    timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")
    temp_dir = tempfile.gettempdir()
    map_filename = f"signal_map_{timestamp_str}.html"
    map_path = os.path.join(temp_dir, map_filename)

    m.save(map_path)

    # Calculate coordinate bounds
    min_lat = min(_get_record_field(r, 'latitude') for r in filtered_records)
    max_lat = max(_get_record_field(r, 'latitude') for r in filtered_records)
    min_lon = min(_get_record_field(r, 'longitude') for r in filtered_records)
    max_lon = max(_get_record_field(r, 'longitude') for r in filtered_records)

    # Auto-open in browser
    webbrowser.open('file://' + os.path.abspath(map_path))

    # Return result
    result = {
        "status": "success",
        "map_file": map_path,
        "format": output_format,
        "records_plotted": len(filtered_records),
        "anomalies_plotted": anomaly_count,
        "coordinate_bounds": {
            "min_latitude": round(min_lat, 6),
            "max_latitude": round(max_lat, 6),
            "min_longitude": round(min_lon, 6),
            "max_longitude": round(max_lon, 6),
            "center_latitude": round(center_lat, 6),
            "center_longitude": round(center_lon, 6)
        },
        "color_by": color_by,
        "message": f"Map opened in browser with {len(filtered_records)} points"
    }

    return json.dumps(result, indent=2)


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

        # For demonstrating that Arduino is connected (only if connected)
        if board.connected:
            board.red_LED()
            time.sleep(1)
            board.yellow_LED()
            time.sleep(1)
            board.off()
        else:
            logger.info("Arduino not connected, skipping LED tests")

        # Runs the MCP server
        ArduinoMCP.run()

        # If you want to host via http:
        # ArduinoMCP.run(transport="http", host="127.0.0.1", port=8000)
    except KeyboardInterrupt:
        board.close()
        pass
    finally:
        board.close()
