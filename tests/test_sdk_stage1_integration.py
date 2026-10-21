"""Explicit root-only checks: build agent-sdk first; not backend-only CI input."""
import asyncio
import os
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))
from app.sdk_bridge import SDKInterrupted, _exchange  # noqa: E402


def test_disabled_node_entry_through_python_bridge(tmp_path):
    node = os.environ['SDK_TEST_NODE']  # explicitly supplied absolute Node22 fixture binary
    request = {'v': 1, 'id': 'integration', 'task': 'summary', 'model': 'haiku', 'prompt': 'offline fixture'}
    with pytest.raises(SDKInterrupted, match='disabled'):
        asyncio.run(_exchange([node, str(ROOT / 'agent-sdk/dist/main.js')], request, home=str(tmp_path), timeout=2))


def test_fixture_result_golden_through_both_languages(tmp_path):
    node = os.environ['SDK_TEST_NODE']
    fixture = tmp_path / 'fixture.mjs'
    adapter = (ROOT / 'agent-sdk/dist/adapter.js').as_uri()
    protocol = (ROOT / 'agent-sdk/dist/protocol.js').as_uri()
    fixture.write_text(f'''import {{ translateFixture }} from {adapter!r};
import {{ encode }} from {protocol!r};
let text = ''; for await (const part of process.stdin) text += part;
const req = JSON.parse(text);
for (const frame of translateFixture(req, [{{type:'result',subtype:'success',is_error:false,result:'요약\\n기술스택: Python, React'}}])) process.stdout.write(encode(frame));
''')
    request = {'v': 1, 'id': 'golden', 'task': 'summary', 'model': 'haiku', 'prompt': 'offline fixture'}
    assert asyncio.run(_exchange([node, str(fixture)], request, home=str(tmp_path), timeout=2)) == '요약\n기술스택: Python, React'
