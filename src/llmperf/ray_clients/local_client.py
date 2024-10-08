import json
import os
import time
from typing import Any, Dict

import ray
import requests
from transformers import LlamaTokenizerFast

from llmperf.ray_llm_client import LLMClient
from llmperf.models import RequestConfig
from llmperf import common_metrics

tokenizer = LlamaTokenizerFast.from_pretrained("hf-internal-testing/llama-tokenizer")

@ray.remote
class LocalLLMClient(LLMClient):
    """Client for Local Triton"""

    def __init__(self):
        pass

    def llm_request(self, request_config: RequestConfig) -> Dict[str, Any]:
        return send_req(request_config)
    
def send_req(request_config: RequestConfig) -> Dict[str, Any]:
    url = "http://localhost:8000/v2/models/ensemble/generate"
    headers = {
        "Content-Type": "application/json"
    }

    prompt = request_config.prompt
    prompt, prompt_len = prompt

    time_to_next_token = []
    tokens_received = 0
    ttft = 0
    generated_text = ""
    output_throughput = 0
    total_request_time = 0

    metrics = {}
    metrics[common_metrics.ERROR_CODE] = None
    metrics[common_metrics.ERROR_MSG] = ""
    text_input = f"<|begin_of_text|><|start_header_id|>user<|end_header_id|>{prompt}<|eot_id|><|start_header_id|>assistant<|end_header_id|>"

    try:
        data = {
            "text_input": text_input,
            "max_tokens": request_config.sampling_params.get("max_new_tokens", 2048)
        }

        # Make the POST request
        start_time = time.monotonic()
        response = requests.post(url, headers=headers, data=json.dumps(data))
        total_request_time = time.monotonic() - start_time
        response_code = response.status_code
        response.raise_for_status()

        # Extract the generated text and tokenize it
        response_json = response.json()

        # Extract the generated text
        generated_text = response_json['text_output']
        tokens_received = len(tokenizer.encode(generated_text))
        print("DEBUG: data", data)
        print("DEBUG: generated_text", generated_text)
        print("DEBUG: tokens_received", tokens_received)
        print("DEBUG: total_request_time", total_request_time)
        ttft = -1  # Time to first token; adjust this if your endpoint provides this info
        output_throughput = tokens_received / total_request_time
        time_to_next_token = [
            total_request_time / tokens_received for _ in range(tokens_received)
        ]

    except Exception as e:
        metrics[common_metrics.ERROR_MSG] = str(e)
        metrics[common_metrics.ERROR_CODE] = response_code if 'response_code' in locals() else None
        print(f"Warning Or Error: {e}")

    metrics[common_metrics.INTER_TOKEN_LAT] = time_to_next_token
    metrics[common_metrics.TTFT] = ttft
    metrics[common_metrics.E2E_LAT] = total_request_time
    metrics[common_metrics.REQ_OUTPUT_THROUGHPUT] = output_throughput
    metrics[common_metrics.NUM_TOTAL_TOKENS] = tokens_received + prompt_len
    metrics[common_metrics.NUM_OUTPUT_TOKENS] = tokens_received 
    metrics[common_metrics.NUM_INPUT_TOKENS] = prompt_len

    return metrics, generated_text, request_config


if __name__ == "__main__":
    client = LocalLLMClient.remote()
    request_config_localhost = RequestConfig(
        prompt=("userHow are you?assistant", 5),
        model="localhost",
        sampling_params={
            "max_new_tokens": 1024,
        },
    )
    result_localhost = send_req(request_config_localhost)
    print("RESULT (Localhost):", result_localhost)
