import boto3
import json
import logging
from botocore.config import Config

logger = logging.getLogger(__name__)

class BedrockClient:
    def __init__(self, model_id, temperature=0.0, region="us-east-1", aws_access_key=None, aws_secret_key=None):
        config = Config(connect_timeout=600, read_timeout=600)
        if aws_access_key and aws_secret_key:
            self.bedrock_runtime = boto3.client(
                'bedrock-runtime',
                region_name=region,
                aws_access_key_id=aws_access_key,
                aws_secret_access_key=aws_secret_key,
                config=config
            )
        else:
            self.bedrock_runtime = boto3.client('bedrock-runtime', region_name=region, config=config)

        self.model_id = model_id
        self.temperature = temperature

    def generate_text(self, prompt, system_prompt=None, max_tokens=64000):
        messages = [{"role": "user", "content": [{"type": "text", "text": prompt}]}]
        body = {
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": max_tokens,
            "temperature": self.temperature,
            "messages": messages
        }
        if system_prompt and "anthropic.claude" in self.model_id:
            body["system"] = system_prompt

        response = self.bedrock_runtime.invoke_model(
            modelId=self.model_id,
            body=json.dumps(body)
        )
        response_body = json.loads(response.get("body").read())
        return response_body['content'][0]['text']
