import paho.mqtt.client as mqtt
import json
import time
'''
Base class for all 4 agents - 
provides standardized Paho MQTT client setup and connection management.
'''

BROKER = "localhost"
PORT = 1883

class MQTTBaseAgent:
    def __init__(self, agent_name):
        self.agent_name = agent_name
        self.connected_flag = False
        
        self.client = mqtt.Client(client_id=f"{agent_name}_v1")
        self.client.on_connect = self.on_connect
    
    def on_connect(self, client, userdata, flags, rc):
        if rc == 0:
            self.connected_flag = True
            print(f" {self.agent_name} connected (rc=0)")
        else:
            self.connected_flag = False
            print(f" {self.agent_name} connection failed (rc={rc})")
    
    def connect(self):
        """ FIXED: Connect ONLY - no loop_start()"""
        if self.connected_flag:
            return
        
        try:
            self.client.connect(BROKER, PORT, 60)
            time.sleep(1)
        except Exception as e:
            print(f" {self.agent_name} connection error: {e}")
    
    def disconnect(self):
        if self.connected_flag:
            self.client.disconnect()
            self.connected_flag = False
            print(f" {self.agent_name} disconnected")
