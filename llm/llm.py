from transformers import AutoTokenizer, AutoModelForCausalLM, pipeline
from langchain_huggingface import HuggingFacePipeline
import torch
'''
It enables offline LLM reasoning for real-time IoT oversight without API costs/latency
Note: Adjust the path based on the folder where your model is located.
'''
#Adjust the path based on the folder where your model is located.
MODEL_PATH = "qwen2.5_local"

def load_qwen():
    print("Loading Qwen LLM (CPU)...")
    tokenizer = AutoTokenizer.from_pretrained(
        MODEL_PATH, trust_remote_code=True, fix_mistral_regex=True
    )
    model = AutoModelForCausalLM.from_pretrained(
        MODEL_PATH,
        trust_remote_code=True,
        torch_dtype=torch.float32,  
        device_map=None,            
        low_cpu_mem_usage=True
    )
    model.eval()
    
    pipe = pipeline(
        "text-generation", 
        model=model,
        tokenizer=tokenizer,
        max_new_tokens=512,    
        temperature=0.3,
        do_sample=True
    )
    llm = HuggingFacePipeline(pipeline=pipe)
    print("✅ Qwen LLM loaded (CPU)!")
    return llm
