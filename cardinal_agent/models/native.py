"""Normalize native client tools without letting provider payloads execute code.

Transports are SDK create methods (or deterministic fakes), called with keyword
arguments. No credentials, SDK clients or executable functions are serialized.
"""
from copy import deepcopy
from dataclasses import dataclass, field
import json

from cardinal_agent.types import ToolCall


@dataclass
class NativeReply:
    text: str = ''
    tool_call: ToolCall | None = None
    provider_call_id: str | None = None
    usage: dict = field(default_factory=dict)


class NativeProtocolError(ValueError):
    pass


def _object(value):
    return value.model_dump() if hasattr(value, 'model_dump') else value


def _call(name, args, identifier):
    if not isinstance(name, str) or not name or not isinstance(args, dict):
        raise NativeProtocolError('Native tool call requires a name and object arguments.')
    if not isinstance(identifier, str) or not identifier:
        raise NativeProtocolError('Native tool call requires a provider call ID.')
    try:
        json.dumps(args, allow_nan=False)
    except (ValueError, TypeError) as exc:
        raise NativeProtocolError('Native arguments must be finite JSON values.') from exc
    return ToolCall(name, args)


def _usage(value):
    value = value or {}
    return {k: v for k, v in value.items() if isinstance(v, (int, float)) and not isinstance(v, bool)}


class _Adapter:
    native_tools = True

    def __init__(self, transport, model, *, max_tokens=2048, provider=None):
        self.transport = transport
        self.model = model
        self.max_tokens = max_tokens
        self.provider = provider or self.protocol_name

    def __call__(self, messages):
        # Text-only auxiliary calls (e.g. summaries) still use the same transport.
        reply = self.complete_native(messages, [])
        if reply.tool_call:
            raise NativeProtocolError('A text-only auxiliary call returned a tool invocation.')
        return reply.text

    def _history(self, messages):
        # Reconstruct pairs from trusted metadata, never from text that happens
        # to resemble a tool result. Compaction may leave orphaned evidence.
        results = {m['_harness_result']['id']: m for m in messages if '_harness_result' in m}
        paired = {m['_harness_call']['id'] for m in messages
                  if '_harness_call' in m and m['_harness_call']['id'] in results}
        for message in messages:
            call = message.get('_harness_call')
            result = message.get('_harness_result')
            if call and call['id'] in paired:
                yield 'pair', message, results[call['id']]
            elif result and result['id'] in paired:
                continue
            elif call:
                yield 'plain', {'role': 'assistant', 'content':
                    f"Earlier request to {call['name']} (result omitted from context)."}, None
            else:
                yield 'plain', message, None


class OpenAIChatAdapter(_Adapter):
    """OpenAI-compatible Chat Completions client tools (non-streaming)."""
    protocol_name = 'openai-chat'

    def complete_native(self, messages, schemas):
        history = []
        for kind, message, result in self._history(messages):
            if kind == 'pair':
                call = message['_harness_call']
                history.append({'role': 'assistant', 'content': call.get('text') or None,
                                'tool_calls': [{'id': call['id'], 'type': 'function', 'function':
                                    {'name': call['name'], 'arguments': json.dumps(call['args'], ensure_ascii=False)}}]})
                history.append({'role': 'tool', 'tool_call_id': call['id'], 'content': result['content']})
            else:
                history.append({'role': message['role'], 'content': message['content']})
        request = {'model': self.model, 'messages': history, 'max_tokens': self.max_tokens}
        if schemas:
            request.update(tools=[{'type': 'function', 'function': deepcopy(s)} for s in schemas],
                           parallel_tool_calls=False)
        response = _object(self.transport(**request))
        choices = response.get('choices', [])
        if len(choices) != 1 or choices[0].get('finish_reason') not in ('stop', 'tool_calls'):
            raise NativeProtocolError('Incomplete or unsupported native completion; no tool will execute.')
        message = choices[0]['message']
        text = message.get('content') or ''
        if not isinstance(text, str):
            raise NativeProtocolError('Only text and client tool calls are supported.')
        if message.get('function_call') is not None:
            raise NativeProtocolError('Legacy function_call responses are not supported.')
        calls = message.get('tool_calls') or []
        if len(calls) > 1:
            raise NativeProtocolError('Multiple native calls are not supported; no tool will execute.')
        if not calls:
            if choices[0]['finish_reason'] == 'tool_calls':
                raise NativeProtocolError('Tool finish reason without a call.')
            return NativeReply(text=text, usage=_usage(response.get('usage')))
        if choices[0]['finish_reason'] != 'tool_calls' or calls[0].get('type') != 'function':
            raise NativeProtocolError('Unsupported or incomplete tool call.')
        item = calls[0]
        function = item['function']
        try:
            args = json.loads(function['arguments'])
        except (ValueError, TypeError) as exc:
            raise NativeProtocolError('Native arguments are not complete JSON.') from exc
        return NativeReply(text, _call(function.get('name'), args, item.get('id')),
                           item['id'], _usage(response.get('usage')))


class AnthropicMessagesAdapter(_Adapter):
    """Anthropic Messages client tool_use/tool_result blocks (non-streaming)."""
    protocol_name = 'anthropic-messages'

    def complete_native(self, messages, schemas):
        system, history = [], []
        for kind, message, result in self._history(messages):
            if message['role'] == 'system':
                system.append(message['content'])
                continue
            if kind == 'pair':
                call = message['_harness_call']
                blocks = ([{'type': 'text', 'text': call['text']}] if call.get('text') else [])
                blocks.append({'type': 'tool_use', 'id': call['id'], 'name': call['name'], 'input': call['args']})
                history.append({'role': 'assistant', 'content': blocks})
                history.append({'role': 'user', 'content': [{'type': 'tool_result', 'tool_use_id': call['id'],
                                'content': result['content'], 'is_error': result['_harness_result']['status'] != 'ok'}]})
            else:
                history.append({'role': message['role'], 'content': [{'type': 'text', 'text': message['content'] or ' '}]})
        merged = []
        for item in history:
            if merged and merged[-1]['role'] == item['role']:
                merged[-1]['content'].extend(item['content'])
            else:
                merged.append(item)
        request = {'model': self.model, 'system': '\n\n'.join(system), 'messages': merged,
                   'max_tokens': self.max_tokens}
        if schemas:
            request.update(tools=[{'name': s['name'], 'description': s['description'],
                                   'input_schema': deepcopy(s['parameters'])} for s in schemas],
                           tool_choice={'type': 'auto', 'disable_parallel_tool_use': True})
        response = _object(self.transport(**request))
        if response.get('stop_reason') not in ('end_turn', 'tool_use'):
            raise NativeProtocolError('Incomplete or unsupported native completion; no tool will execute.')
        blocks = response.get('content', [])
        if any(b.get('type') not in ('text', 'tool_use') for b in blocks):
            raise NativeProtocolError('Only text and client tool_use blocks are supported.')
        calls = [b for b in blocks if b['type'] == 'tool_use']
        text = '\n'.join(b['text'] for b in blocks if b['type'] == 'text')
        if len(calls) > 1:
            raise NativeProtocolError('Multiple native calls are not supported; no tool will execute.')
        if not calls:
            if response['stop_reason'] == 'tool_use':
                raise NativeProtocolError('Tool stop reason without a call.')
            return NativeReply(text=text, usage=_usage(response.get('usage')))
        if response['stop_reason'] != 'tool_use':
            raise NativeProtocolError('Incomplete native tool call.')
        item = calls[0]
        return NativeReply(text, _call(item.get('name'), item.get('input'), item.get('id')),
                           item['id'], _usage(response.get('usage')))
