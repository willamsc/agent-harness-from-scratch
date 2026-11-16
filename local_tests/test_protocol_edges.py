"""Protocol shape errors are separate from registry schema validation."""
import pytest

from cardinal_agent.agent.protocol import parse_response


@pytest.mark.parametrize('payload', ['[]', 'null', '{"name":1,"args":{}}',
                                     '{"name":"echo","args":[]}', '{"name":"echo"}'])
def test_wrong_payload_shapes_are_errors(payload):
    result = parse_response('<tool_call>' + payload + '</tool_call>')
    assert result.error and result.tool_call is None


def test_complete_json_still_needs_closing_tag():
    result = parse_response('<tool_call>{"name":"echo","args":{}}')
    assert result.error and result.tool_call is None


def test_whitespace_body_and_unknown_tool_are_preserved_for_registry():
    result = parse_response(' Before.\n<tool_call>\n {"name":"unknown","args":{}} \n</tool_call>\nAfter. ')
    assert result.error is None
    assert result.text == 'Before.\n\nAfter.'
    assert result.tool_call.name == 'unknown'
    assert result.tool_call.args == {}
