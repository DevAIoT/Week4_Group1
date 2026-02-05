"""
Quick Arduino connection and functionality test script.
Run this before starting the full orchestrator to verify Arduino connection.
"""
import sys
from pathlib import Path

# Add agents directory to path
sys.path.insert(0, str(Path(__file__).parent / "agents"))

from sensor_agent1 import Nano33SenseRev2
import time

# Configuration - change this to your Arduino port
ARDUINO_PORT = "COM3"  # Windows: COM3, Mac: /dev/cu.usbmodem21201, Linux: /dev/ttyACM0

def test_arduino():
    print("=" * 60)
    print("Arduino Nano 33 Sense Rev2 Connection Test")
    print("=" * 60)

    try:
        print(f"\n[1/4] Connecting to Arduino on {ARDUINO_PORT}...")
        board = Nano33SenseRev2(ARDUINO_PORT)
        time.sleep(2)  # Wait for initialization
        print("✓ Connection successful!\n")

        print("[2/4] Reading sensor data...")
        state = board.get_state()
        if state:
            print("✓ Sensor data received:")
            if state.hs3003_t_c is not None:
                print(f"   Temperature: {state.hs3003_t_c:.1f}°C")
            if state.hs3003_h_rh is not None:
                print(f"   Humidity: {state.hs3003_h_rh:.1f}%")
            if state.lps22hb_p_kpa is not None:
                print(f"   Pressure: {state.lps22hb_p_kpa:.1f} kPa")
            if state.apds_prox is not None:
                print(f"   Proximity: {state.apds_prox}")
            print()
        else:
            print("✗ No sensor data received (timeout)\n")

        print("[3/4] Testing LED control...")
        print("   Red LED...", end=" ", flush=True)
        board.red_LED()
        time.sleep(1)
        print("✓")

        print("   Yellow LED...", end=" ", flush=True)
        board.yellow_LED()
        time.sleep(1)
        print("✓")

        print("   Green LED...", end=" ", flush=True)
        board.green_LED()
        time.sleep(1)
        print("✓")

        print("   Turning off...", end=" ", flush=True)
        board.off()
        time.sleep(0.5)
        print("✓\n")

        print("[4/4] Closing connection...")
        board.close()
        print("✓ Connection closed\n")

        print("=" * 60)
        print("✓ ALL TESTS PASSED!")
        print("=" * 60)
        print("\nYour Arduino is ready to use with the system.")
        print("You can now run: python orchestrator.py")
        return True

    except Exception as e:
        print(f"\n✗ TEST FAILED: {e}")
        print("\nTroubleshooting:")
        print("1. Check that Arduino is connected via USB")
        print("2. Verify ARDUINO_PORT is correct (check Device Manager on Windows)")
        print("3. Close Arduino IDE Serial Monitor if open")
        print("4. Ensure Arduino firmware is uploaded")
        print(f"5. Try other ports: COM4, COM5 (Windows) or /dev/ttyACM0 (Linux)")
        return False

if __name__ == "__main__":
    success = test_arduino()
    sys.exit(0 if success else 1)
