from base.mqtt_base import MQTTBaseAgent
import json
import paho.mqtt.client as mqtt
import time
import uuid
import threading
'''
Final execution agent - receives light commands, 
awaits LLM supervisor approval,
executes approved commands on physical lights.
'''
ACTUATOR_COMMANDS_TOPIC = "home/agents/actuator-commands"
ACTUATOR_STATUS_TOPIC = "home/agents/actuator/status"
SUPERVISOR_FEEDBACK_TOPIC = "home/agents/supervisor/feedback"

class ActuatorAgent(MQTTBaseAgent):
    def __init__(self):
        super().__init__("actuator")
        self.pending_requests = {}
        self.wait_conditions = {}  
    
    def subscribe_to_topics(self):
        self.connect()
        self.client.subscribe(ACTUATOR_COMMANDS_TOPIC)
        self.client.message_callback_add(ACTUATOR_COMMANDS_TOPIC, self.handle_commands)
        self.client.subscribe(SUPERVISOR_FEEDBACK_TOPIC)
        self.client.message_callback_add(SUPERVISOR_FEEDBACK_TOPIC, self.handle_supervisor_feedback)
        print(" ActuatorAgent subscribed (30s FAST EXECUTION)!")
    
    def handle_commands(self, client, userdata, msg):
        try:
            data = json.loads(msg.payload.decode())
            commands = data["light_commands"]
            request_id = str(uuid.uuid4())[:8]
            
            print(f"\n  Actuator received: {commands} (ID: {request_id})")
            
            pending_status = json.dumps({
                "from": "actuator", "status": "pending", "request_id": request_id,
                "rooms": list(commands.keys()), "commands": commands, "timestamp": time.time()
            })
            client.publish(ACTUATOR_STATUS_TOPIC, pending_status, qos=1)
            print(f"AWAITING supervisor (30s max): {len(commands)} rooms (ID: {request_id})")
            
            self.pending_requests[request_id] = {"commands": commands, "client": client}
            self.wait_conditions[request_id] = threading.Condition()
            
            wait_thread = threading.Thread(target=self._wait_for_supervisor_thread, args=(request_id,))
            wait_thread.daemon = True
            wait_thread.start()
            
        except Exception as e:
            print(f"Actuator error: {e}")
    
    def handle_supervisor_feedback(self, client, userdata, msg):
        try:
            feedback = json.loads(msg.payload.decode())
            decision = feedback["decision"]
            request_id = decision.get("request_id")
            if not request_id: 
                print(f"No request_id in feedback, using latest pending: {list(self.pending_requests.keys())[-1] if self.pending_requests else 'None'}")
                if self.pending_requests:
                    request_id = list(self.pending_requests.keys())[-1]
                else:
                    return
            
            if request_id in self.pending_requests and request_id in self.wait_conditions:
                print(f" Supervisor: {decision['status']} - {decision.get('reason', 'N/A')} (ID: {request_id})")
                self.pending_requests[request_id]["decision"] = decision
                
                with self.wait_conditions[request_id]:
                    self.wait_conditions[request_id].notify()
            else:
                print(f" Late feedback ignored: {request_id}")
        except Exception as e:
            print(f"Feedback error: {e}")
    
    def _wait_for_supervisor_thread(self, request_id):
        """30s FAST EXECUTION - for immediate testing"""
        timeout = 30.0  
        start_time = time.time()
        
        with self.wait_conditions[request_id]:
            while request_id in self.pending_requests:
                if time.time() - start_time > timeout:
                    print(f" {int(timeout)}s TIMEOUT → SAFETY APPROVED (ID: {request_id})")
                    self._execute_or_reject(request_id, {"status": "approved", "reason": f"{int(timeout)}s timeout"})
                    return
                
                if "decision" in self.pending_requests[request_id]:
                    decision = self.pending_requests[request_id]["decision"]
                    self._execute_or_reject(request_id, decision)
                    return
                
                self.wait_conditions[request_id].wait(timeout=1.0)
    
    def _execute_or_reject(self, request_id, decision):
        commands = self.pending_requests[request_id]["commands"]
        client = self.pending_requests[request_id]["client"]
        
        if decision.get('status') in ['approved', 'warning']:
            print(f"EXECUTING {len(commands)} rooms (ID: {request_id})")
            for room, color in commands.items():
                phys_topic = f"home/{room}/light/control"
                client.publish(phys_topic, json.dumps({"color": color, "room": room}), qos=1)
                print(f"PHYSICAL: {room} = {color}")
        else:
            print(f"REJECTED by supervisor: {decision.get('reason', 'unknown')} (ID: {request_id})")
        
        # Final status
        final_status = json.dumps({
            "from": "actuator", "status": "completed",
            "request_id": request_id, "decision": decision.get('status'),
            "rooms": list(commands.keys()), "timestamp": time.time()
        })
        client.publish(ACTUATOR_STATUS_TOPIC, final_status, qos=1)
        print(f" FINAL: {decision.get('status', 'timeout')} {len(commands)} rooms (ID: {request_id})")
        
        self._cleanup_request(request_id)
    
    def _cleanup_request(self, request_id):
        self.pending_requests.pop(request_id, None)
        self.wait_conditions.pop(request_id, None)
    
    def run(self):
        print(" ActuatorAgent ready (30s FAST EXECUTION)...")
        try:
            self.client.loop_forever()
        except KeyboardInterrupt:
            print("\n Actuator stopped")
        finally:
            self.disconnect()

if __name__ == "__main__":
    actuator = ActuatorAgent()
    actuator.subscribe_to_topics()
    actuator.run()
