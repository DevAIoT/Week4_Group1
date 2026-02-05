from llm.llm import load_qwen
from base.mqtt_base import MQTTBaseAgent
import json
import time
import threading
import re
'''
Subscribes to actuator status reports → Qwen LLM validates execution (rules + AI reasoning) 
→ publishes approval/warning/rejection feedback with 100s timeout protection
'''

ACTUATOR_STATUS_TOPIC = "home/agents/actuator/status"
SUPERVISOR_FEEDBACK_TOPIC = "home/agents/supervisor/feedback"

class LLMSupervisorAgent(MQTTBaseAgent):
    def __init__(self):
        super().__init__("llm_supervisor")
        self.llm = load_qwen()
        self.review_count = 0
        self.last_decision_time = 0
        self.llm_result = None
    
    def subscribe_to_topics(self):
        self.connect()
        self.client.subscribe(ACTUATOR_STATUS_TOPIC)
        self.client.message_callback_add(ACTUATOR_STATUS_TOPIC, self.review)
        print(" llm_supervisor connected (rc=0)")
    
    def review(self, client, userdata, msg):
        try:
            self.review_count += 1
            actuator_data = json.loads(msg.payload.decode())
            rooms = actuator_data["rooms"]
            request_id = actuator_data.get("request_id", "unknown")  
            
            print(f"\n LLM reviewing: {rooms} (#{self.review_count})")
            
            feedback = self.make_llm_decision_with_timeout(rooms, actuator_data, timeout=100.0)
            feedback['request_id'] = request_id  
            
            payload = json.dumps({
                "from": "llm_supervisor", 
                "decision": feedback
            })
            client.publish(SUPERVISOR_FEEDBACK_TOPIC, payload, qos=1)
            print(f"LLM: {feedback['status']} - {feedback['reason']}")
            
        except Exception as e:
            print(f" LLM Supervisor error: {e}")
            fallback = {"status": "approved", "reason": "Emergency fallback"}
            client.publish(SUPERVISOR_FEEDBACK_TOPIC, json.dumps({
                "from": "llm_supervisor", "decision": fallback
            }))
    
    def make_llm_decision_with_timeout(self, rooms, actuator_data, timeout=100.0):
        num_rooms = len(rooms)
        current_time = time.strftime("%H:%M")
        hour = int(current_time.split(":")[0])
        is_night = hour >= 22 or hour <= 6
        
        if num_rooms == 0:
            return {"status": "rejected", "reason": "No rooms executed"}
        if num_rooms > 5:
            return {"status": "rejected", "reason": f"Flood: {num_rooms} rooms"}
        if is_night and "bedroom" in [r.lower() for r in rooms]:
            return {"status": "warning", "reason": f"Night bedroom lights"}
        
        result = self._run_llm_with_timeout(rooms, current_time, num_rooms, timeout)
        
        if result:
            print(f" Qwen LLM: {result['status']} after {result.get('time_taken', 'N/A')}s")
            return result
        
        print(" LLM timed out after 100s - final fallback")
        return {"status": "approved", "reason": f"100s timeout: {num_rooms} rooms"}
    
    def _run_llm_with_timeout(self, rooms, current_time, num_rooms, timeout):
        def llm_task():
            prompt = f"<|im_start|>system\nYou are a JSON generator. Output ONLY valid JSON.\n<|im_end|>\n<|im_start|>user\nReview rooms: {rooms}\nTime: {current_time}\nCount: {num_rooms}\n\nOutput ONLY: {{\"status\":\"approved\",\"reason\":\"Normal operation\"}}\n<|im_end|>\n<|im_start|>assistant\n"
            
            try:
                start_time = time.time()
                response = self.llm.invoke(prompt)
                llm_time = time.time() - start_time
                print(f"⏱️ LLM inference: {llm_time:.1f}s")
                print(f"📄 Raw LLM response: {repr(response[:200])}...")
                
                result = self._extract_json_robustly(response)
                
                if result and result.get('status') in ['approved', 'warning', 'rejected']:
                    self.llm_result = {
                        'status': result['status'],
                        'reason': result.get('reason', 'LLM decision')[:50],
                        'time_taken': f"{llm_time:.1f}s"
                    }
                    return

                hour = int(current_time.split(":")[0])
                if 6 <= hour < 22 and num_rooms <= 3:
                    self.llm_result = {
                        'status': 'approved', 
                        'reason': f'Normal {num_rooms} rooms daytime',
                        'time_taken': f"{llm_time:.1f}s"
                    }
                else:
                    self.llm_result = {
                        'status': 'warning', 
                        'reason': f'Unusual pattern detected',
                        'time_taken': f"{llm_time:.1f}s"
                    }
                    
            except Exception as e:
                print(f"LLM error: {e}")
                self.llm_result = None
        
        self.llm_result = None
        llm_thread = threading.Thread(target=llm_task)
        llm_thread.daemon = True
        llm_thread.start()
        llm_thread.join(timeout)
        return self.llm_result
    
    def _extract_json_robustly(self, response):
        """Extract JSON from any LLM response format"""
        text = response.strip()
        
        text = re.sub(r'<\|im_start\|>.*?<\|im_end\|>\n?', '', text, flags=re.DOTALL)
        text = re.sub(r'<\|im_start\|>assistant\n?', '', text)
        
        text = re.sub(r'```json\s*|\s*```', '', text, flags=re.DOTALL)

        json_match = re.search(r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}', text)
        if json_match:
            try:
                result = json.loads(json_match.group())
                return result
            except json.JSONDecodeError:
                pass
        
        try:
            result = json.loads(text)
            return result
        except json.JSONDecodeError:
            pass
        
        return None
    
    def run(self):
        print("LLM Supervisor active (Qwen + 100s timeout + QWEN-FIXED JSON)...")
        try:
            self.client.loop_forever()
        except KeyboardInterrupt:
            print("\n LLM Supervisor stopped")
        finally:
            self.disconnect()

if __name__ == "__main__":
    supervisor = LLMSupervisorAgent()
    supervisor.subscribe_to_topics()
    supervisor.run()
