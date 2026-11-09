"""Named model/embedding adapters. Provider credentials never enter trained data."""
from cota.llm.factory import endpoint_value
from cota.llm.observation import model_purpose, observe_model_call, provider_request, provider_response

from .base import PolicyServices


class PolicyResources:
    def __init__(self, endpoints, model=None):
        self.endpoints = endpoints
        self.external_model = model
        self.models = {}

    def model(self, name):
        if self.external_model:
            return self.external_model(name)
        if name not in self.models:
            from cota.llm import LLM
            configs = self.endpoints.get('llms', {})
            if name not in configs:
                raise ValueError(f'Unknown Policy llm: {name}')
            self.models[name] = LLM(configs[name])
            self.models[name].name = name
        return self.models[name]

    async def embed(self, name, texts):
        from openai import AsyncOpenAI
        config = self.endpoints.get('embeddings', {}).get(name)
        if not isinstance(config, dict) or set(config) - {'type', 'key', 'apibase', 'model', 'dimensions'}:
            raise ValueError(f'Invalid embedding resource: {name}')
        if config.get('type', 'openai') != 'openai':
            raise ValueError('Built-in embedding resources require OpenAI-compatible endpoints')
        def resolve(key):
            return endpoint_value(config, key)
        params = {'model': resolve('model'), 'input': texts, 'encoding_format': 'float'}
        if 'dimensions' in config:
            if type(config['dimensions']) is not int or config['dimensions'] < 1:
                raise ValueError('Embedding dimensions must be positive')
            params['dimensions'] = config['dimensions']
        api_key, base_url = resolve('key'), resolve('apibase')
        async def generate(**parameters):
            await provider_request(parameters)
            async with AsyncOpenAI(api_key=api_key, base_url=base_url, timeout=30, max_retries=1) as client:
                response = await client.embeddings.create(**parameters)
            provider_response(response)
            ordered = sorted(response.data, key=lambda item: item.index)
            if [item.index for item in ordered] != list(range(len(texts))):
                raise ValueError('Embedding response indices are invalid')
            return [item.embedding for item in ordered]
        with model_purpose('policy_embedding'):
            return await observe_model_call(generate, params, llm=name)

    def services(self):
        return PolicyServices(model=self.model, embedding=self.embed)

    async def close(self):
        for llm in self.models.values():
            client = getattr(llm.client, 'client', None)
            if client is not None:
                await client.close()
