"""Filter pipeline 单元测试。"""

from __future__ import annotations

from engine.filter.pipeline import _parse_json_array


# ── _parse_json_array 基础解析 ──

def test_parse_simple_array():
    text = '[{"score": 7.5, "category": "policy"}]'
    result = _parse_json_array(text)
    assert len(result) == 1
    assert result[0]["score"] == 7.5


def test_parse_multiple_items():
    text = '[{"score": 8}, {"score": 6}]'
    result = _parse_json_array(text)
    assert len(result) == 2


def test_parse_single_object():
    """单个对象应包装为列表。"""
    text = '{"score": 7}'
    result = _parse_json_array(text)
    assert len(result) == 1
    assert result[0]["score"] == 7


# ── 代码块提取 ──

def test_parse_markdown_code_block():
    text = '```json\n[{"score": 8}]\n```'
    result = _parse_json_array(text)
    assert len(result) == 1
    assert result[0]["score"] == 8


def test_parse_code_block_without_lang():
    text = '```\n[{"score": 5}]\n```'
    result = _parse_json_array(text)
    assert len(result) == 1
    assert result[0]["score"] == 5


def test_parse_code_block_with_surrounding_text():
    text = 'Here is the result:\n```json\n[{"score": 9}]\n```\nDone.'
    result = _parse_json_array(text)
    assert len(result) == 1


# ── 尾部逗号修复 ──

def test_parse_trailing_comma_in_object():
    text = '[{"score": 7, "category": "policy",}]'
    result = _parse_json_array(text)
    assert len(result) == 1
    assert result[0]["category"] == "policy"


def test_parse_trailing_comma_in_array():
    text = '[{"score": 7}, {"score": 8},]'
    result = _parse_json_array(text)
    assert len(result) == 2


# ── 边界情况 ──

def test_parse_empty_string():
    result = _parse_json_array("")
    assert result == []


def test_parse_invalid_json():
    result = _parse_json_array("not json at all")
    assert result == []


def test_parse_empty_array():
    result = _parse_json_array("[]")
    assert result == []


def test_parse_nested_json_in_text():
    text = 'Some prefix [{"score": 6}] some suffix'
    result = _parse_json_array(text)
    assert len(result) == 1
    assert result[0]["score"] == 6
