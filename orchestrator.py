import threading
import time
from agents.sensor_agent1 import SensorAgent
from agents.light_controller_agent import LightControllerAgent
from agents.actuator_agent1 import ActuatorAgent
from agents.llm_supervisor_agent import LLMSupervisorAgent 

'''
This is the master orchestrator that launches all 4 agents concurrently
to run the complete home automation pipeline

SensorAgent analyzing... → publishes light-commands
↓
LightController received → forwards to actuator-commands  
↓
Actuator received → AWAITING supervisor → pending status
↓
LLM reviewing... → approved/warning → feedback  
↓
Actuator EXECUTING → physical lights → completed status
↓
Loop repeats every 15s (SensorAgent cycle)

'''

def run_all_agents():
    print(" 4-AGENT MQTT-STYLE SYSTEM STARTING...")
    print("Sensor → LightController → LLM Supervisor ↔ Actuator")
    print("=" * 60)
    
    # Create agents
    sensor = SensorAgent()
    controller = LightControllerAgent()
    actuator = ActuatorAgent()
    supervisor = LLMSupervisorAgent()
    
    # Step 1: Connect and subscribe ALL agents
    print("\n PHASE 1: Connecting & Subscribing Agents...")
    sensor.subscribe_to_topics()
    controller.subscribe_to_topics()
    actuator.subscribe_to_topics()
    supervisor.subscribe_to_topics()
    
    # Step 2: Give connections time to stabilize
    print("\n+ PHASE 2: Stabilizing connections (3s)...")
    time.sleep(3)
    
    # Step 3: Start agent run loops in threads
    print("\n PHASE 3: Starting agent threads...")
    threads = [
        threading.Thread(target=sensor.run, daemon=True, name="SensorThread"),
        threading.Thread(target=controller.run, daemon=True, name="ControllerThread"),
        threading.Thread(target=actuator.run, daemon=True, name="ActuatorThread"),
        threading.Thread(target=supervisor.run, daemon=True, name="SupervisorThread")
    ]
    
    for t in threads:
        t.start()
        time.sleep(0.5)  
    
    print("\n ALL AGENTS ACTIVE! Press Ctrl+C to stop.")
    print("-" * 60)
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n PHASE 4: Shutting down...")
        print("\n System shutdown complete!")
        time.sleep(1)

if __name__ == "__main__":
    run_all_agents()
