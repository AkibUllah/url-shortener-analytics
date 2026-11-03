"""Bulk CSV import and export of links.

Import reads ``url,alias,title,expires_at`` rows, validates each one with ``LinkCreate`` and
creates the valid ones. A bad row is reported, never raised, so one typo does not reject a file
of a thousand campaign links. Each created row is committed on its own: a later failure does not
undo links that were already handed out.
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass, field

from pydantic import ValidationError

from shortener.schemas import LinkCreate
from shortener.services import AliasTakenError, LinkService

IMPORT_COLUMNS = ("url", "alias", "title", "expires_at")

# Row statuses. ``valid`` is used instead of ``created`` on a dry run.
CREATED = "created"
VALID = "valid"
INVALID = "invalid"
ALIAS_TAKEN = "alias_taken"


class CsvImportError(ValueError):
    """The file as a whole cannot be imported (encoding, header, size)."""

    def __init__(self, message: str, *, too_large: bool = False) -> None:
        super().__init__(message)
        self.too_large = too_large


@dataclass
class ImportRow:
    row: int
    status: str
    code: str | None = None
    error: str | None = None


@dataclass
class ImportResult:
    dry_run: bool
    ignored_columns: list[str]
    rows: list[ImportRow] = field(default_factory=list)

    @property
    def succeeded(self) -> int:
        return sum(r.status in (CREATED, VALID) for r in self.rows)

    @property
    def failed(self) -> int:
        return len(self.rows) - self.succeeded


@dataclass
class ParsedCsv:
    rows: list[tuple[int, dict[str, str | None]]]
    ignored_columns: list[str]


def parse_import_csv(data: bytes, max_rows: int) -> ParsedCsv:
    """Decode and split the file into ``(row_number, values)`` pairs.

    Row numbers count data rows from 1 (the header is not a row). Fully blank lines are
    skipped, empty cells become ``None`` and columns other than ``IMPORT_COLUMNS`` are ignored
    and reported, so a file exported by ``GET /api/v1/links/export.csv`` imports as-is.
    """
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise CsvImportError("file must be UTF-8 encoded CSV") from exc

    reader = csv.reader(io.StringIO(text, newline=""))
    try:
        header = next(reader)
    except StopIteration:
        raise CsvImportError("file is empty") from None
    except csv.Error as exc:
        raise CsvImportError(f"malformed CSV: {exc}") from exc

    columns = [h.strip().lower() for h in header]
    if "url" not in columns:
        raise CsvImportError("header must include a 'url' column")
    duplicates = sorted({c for c in columns if c and columns.count(c) > 1})
    if duplicates:
        raise CsvImportError(f"duplicate columns: {', '.join(duplicates)}")
    ignored = [c for c in columns if c and c not in IMPORT_COLUMNS]

    rows: list[tuple[int, dict[str, str | None]]] = []
    try:
        for record in reader:
            if not any(cell.strip() for cell in record):
                continue
            if len(rows) == max_rows:
                raise CsvImportError(
                    f"file has more than {max_rows} rows; split it into smaller files",
                    too_large=True,
                )
            values = {
                name: (record[i].strip() or None) if i < len(record) else None
                for i, name in enumerate(columns)
                if name in IMPORT_COLUMNS
            }
            rows.append((len(rows) + 1, values))
    except csv.Error as exc:
        raise CsvImportError(f"malformed CSV near line {reader.line_num}: {exc}") from exc
    return ParsedCsv(rows=rows, ignored_columns=ignored)


def describe_validation_error(exc: ValidationError) -> str:
    parts = []
    for error in exc.errors():
        location = ".".join(str(p) for p in error["loc"])
        message = error["msg"].removeprefix("Value error, ")
        parts.append(f"{location}: {message}" if location else message)
    return "; ".join(parts)


def import_links(service: LinkService, parsed: ParsedCsv, *, dry_run: bool = False) -> ImportResult:
    result = ImportResult(dry_run=dry_run, ignored_columns=parsed.ignored_columns)
    seen_aliases: dict[str, int] = {}
    for number, values in parsed.rows:
        try:
            payload = LinkCreate.model_validate(values)
        except ValidationError as exc:
            result.rows.append(ImportRow(number, INVALID, error=describe_validation_error(exc)))
            continue

        alias = payload.alias
        if alias is not None:
            if alias in seen_aliases:
                result.rows.append(
                    ImportRow(
                        number,
                        ALIAS_TAKEN,
                        code=alias,
                        error=f"alias '{alias}' is already used by row {seen_aliases[alias]}",
                    )
                )
                continue
            seen_aliases[alias] = number

        if dry_run:
            if alias is not None and service.get_by_code(alias) is not None:
                result.rows.append(_alias_taken(number, alias))
            else:
                result.rows.append(ImportRow(number, VALID, code=alias))
            continue

        try:
            link = service.create(payload)
        except AliasTakenError:
            result.rows.append(_alias_taken(number, alias))
            continue
        result.rows.append(ImportRow(number, CREATED, code=link.code))
    return result


def _alias_taken(number: int, alias: str | None) -> ImportRow:
    return ImportRow(number, ALIAS_TAKEN, code=alias, error=f"alias '{alias}' is already taken")
