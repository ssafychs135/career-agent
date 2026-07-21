import json


def parse_research_json(text: str) -> dict:
    """claude result 텍스트에서 JSON 객체를 파싱.

    코드펜스(```json)·서두 설명·후미 텍스트에 관용적: 첫 '{'~마지막 '}' 구간만 취해
    json.loads 한다. 객체가 없거나 파싱 불가면 ValueError.
    """
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise ValueError("no JSON object in claude output")
    try:
        return json.loads(text[start : end + 1])
    except json.JSONDecodeError as e:
        raise ValueError(f"invalid JSON: {e}") from e
