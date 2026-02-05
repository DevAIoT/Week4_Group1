from base.mqtt_base import MQTTBaseAgent
import json
import time
'''
LightControllerAgent subscribes to sensor commands and supervisor feedback, 
logs incoming decisions, and immediately forwards them unchanged (with timestamp)
to home/agents/actuator-commands for physical light execution
'''

LIGHT_COMMANDS_TOPIC = "home/agents/light-commands"
ACTUATOR_COMMANDS_TOPIC = "home/agents/actuator-commands"
SUPERVISOR_FEEDBACK_TOPIC = "home/agents/supervisor/feedback"

class LightControllerAgent(MQTTBaseAgent):
    def __init__(self):
        super().__init__("light_controller")
    
    def subscribe_to_topics(self):
        
        self.connect()
        self.client.subscribe(LIGHT_COMMANDS_TOPIC)
        self.client.subscribe(SUPERVISOR_FEEDBACK_TOPIC)
        self.client.message_callback_add(LIGHT_COMMANDS_TOPIC, self.handle_sensor)
        self.client.message_callback_add(SUPERVISOR_FEEDBACK_TOPIC, self.handle_feedback)
        print("LightController subscribed! (MQTT ONLY)")
    
    def run(self):
        try:
            print("LightController ready...")
            self.client.loop_forever()
        except KeyboardInterrupt:
            print("\n LightController stopped")
        finally:
            self.disconnect()
    
    def handle_sensor(self, client, userdata, msg):
        try:
            data = json.loads(msg.payload.decode())
            commands = data["light_commands"]
            print(f"\n LightController received: {commands}")
            
            # Forward to actuator with timestamp
            payload = json.dumps({
                "from": "light_controller",
                "timestamp": time.time(),
                "light_commands": commands
            })
            client.publish(ACTUATOR_COMMANDS_TOPIC, payload, qos=1)
            print(f" LightController → Actuator: {commands}")
            
        except json.JSONDecodeError as e:
            print(f"Invalid sensor data: {e}")
        except Exception as e:
            print(f"LightController error: {e}")
    
    def handle_feedback(self, client, userdata, msg):
        try:
            data = json.loads(msg.payload.decode())
            print(f" LLM Feedback: {data}")
        except json.JSONDecodeError as e:
            print(f"Invalid feedback JSON: {e}")
