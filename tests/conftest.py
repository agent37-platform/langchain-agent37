"""Track upstream contract-test mismatches without changing sandbox behavior."""

import pytest

_UPSTREAM_CONTRACT_FAILURES = {
    "test_glob": 41511,
    "test_glob_basic_pattern": 41511,
    "test_glob_hidden_files_explicitly": 41511,
    "test_glob_with_character_class": 41511,
    "test_glob_with_question_mark": 41511,
    "test_glob_with_directories": 39948,
    "test_write_existing_file_fails": 41511,
}


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    for item in items:
        if "TestAgent37Standard::" in item.nodeid and item.name in _UPSTREAM_CONTRACT_FAILURES:
            issue = _UPSTREAM_CONTRACT_FAILURES[item.name]
            item.add_marker(
                pytest.mark.xfail(
                    strict=True,
                    raises=AssertionError,
                    reason=f"Remove when fixed: https://github.com/langchain-ai/langchain/issues/{issue}",
                )
            )
