"""Constants used by plan validation checks."""

from __future__ import annotations

import re

SUPPORTED_PLAN_VERSIONS = frozenset({"1.0"})
ON_ERROR_POLICIES = frozenset({"fail_fast", "continue"})

SCHEMA_MAX_PARAM_DEPTH = 10
SCHEMA_MAX_PARAM_ITEMS = 1_000
SCHEMA_MAX_STRING_LENGTH = 10_000

OPERATION_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
STEP_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
RUN_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$")
WINDOWS_RESERVED_NAME = re.compile(
    r"^(con|prn|aux|nul|com[1-9]|lpt[1-9]|clock\$|conin\$|conout\$)(\..*)?$",
    re.IGNORECASE,
)
DRIVE_PREFIX = re.compile(r"^[A-Za-z]:")

PATH_KEYS = frozenset(
    {
        "path",
        "paths",
        "file",
        "files",
        "filename",
        "filenames",
        "dir",
        "directory",
        "folder",
    }
)
PATH_SUFFIXES = (
    "_path",
    "_paths",
    "_file",
    "_files",
    "_filename",
    "_dir",
    "_directory",
    "_folder",
)
FORBIDDEN_PARAM_KEYS = frozenset(
    {
        "code",
        "script",
        "python",
        "source_code",
        "command",
        "shell",
        "cmd",
        "eval",
        "exec",
        "sql",
        "raw_sql",
        "query",
        "statement",
    }
)
SECRET_PARAM_KEYS = frozenset(
    {
        "password",
        "passwd",
        "secret",
        "token",
        "api_key",
        "apikey",
        "credential",
        "credentials",
        "private_key",
        "access_key",
        "client_secret",
        "connection_string",
        "dsn",
    }
)
WRITE_SIDE_EFFECT_TOKENS = (
    "write",
    "ddl",
    "destructive",
    "delete",
    "drop",
    "truncate",
    "insert",
    "update",
    "load",
    "create",
    "alter",
    "network",
    "secret",
)
WRITE_OPERATION_TOKENS = (
    "write",
    "save",
    "insert",
    "update",
    "delete",
    "drop",
    "truncate",
    "load",
    "create",
    "alter",
    "ddl",
)
DESTRUCTIVE_OPERATIONS = frozenset({"drop_duplicate_rows", "drop_empty_rows", "filter_rows"})

DANGEROUS_PATTERNS = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"\beval\s*\(",
        r"\bexec\s*\(",
        r"\b__import__\s*\(",
        r"\bimport\s+[A-Za-z_]",
        r"\bsubprocess\b",
        r"\bos\.system\b",
        r"\bshell\s*=",
        r"\bctypes\b",
        r"\bpickle\b",
        r"\bmarshal\b",
        r"\bcompile\s*\(",
        r"\b__builtins__\b",
        r"\bglobals\s*\(",
        r"\blocals\s*\(",
    )
)
SQL_PATTERNS = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"\b(drop|truncate|alter|create)\s+(table|database|schema|view|index)\b",
        r"\bdelete\s+from\b",
        r"\binsert\s+into\b",
        r"\bupdate\s+[A-Za-z_][A-Za-z0-9_]*\s+set\b",
        r"\bunion\s+select\b",
        r";\s*(drop|delete|update|insert|alter|truncate)\b",
    )
)
