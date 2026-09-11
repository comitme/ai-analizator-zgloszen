"""Reading a batch of customer messages from a file.

These rules matter more than they look: this is the path a real shop's exported
inbox takes into the system, and a silently dropped or mangled message means paying
for a run that measures the wrong thing.
"""

import pytest

from ticket_triage.evaluation.batch import BatchFormatError, parse_tickets


def _write(tmp_path, name: str, content: str):
    path = tmp_path / name
    path.write_text(content, encoding="utf-8")
    return path


class TestPlainText:
    def test_one_message_per_line(self, tmp_path):
        path = _write(tmp_path, "zgloszenia.txt", "Chcę zwrot.\nGdzie paczka?\n")

        assert parse_tickets(path) == ["Chcę zwrot.", "Gdzie paczka?"]

    def test_blank_lines_and_comments_are_skipped(self, tmp_path):
        path = _write(
            tmp_path, "z.txt", "# zgłoszenia testowe\nChcę zwrot.\n\n   \nGdzie paczka?\n"
        )

        assert parse_tickets(path) == ["Chcę zwrot.", "Gdzie paczka?"]

    def test_an_unknown_extension_is_read_as_plain_text(self, tmp_path):
        path = _write(tmp_path, "maile.dat", "Chcę zwrot.")

        assert parse_tickets(path) == ["Chcę zwrot."]


class TestJsonl:
    def test_reads_the_text_field(self, tmp_path):
        path = _write(
            tmp_path,
            "z.jsonl",
            '{"text": "Chcę zwrot."}\n{"text": "Gdzie paczka?"}\n',
        )

        assert parse_tickets(path) == ["Chcę zwrot.", "Gdzie paczka?"]

    def test_polish_field_name_is_accepted(self, tmp_path):
        """A shop exporting its own data will not necessarily name the column in English."""
        path = _write(tmp_path, "z.jsonl", '{"tresc": "Chcę zwrot.", "id": 7}\n')

        assert parse_tickets(path) == ["Chcę zwrot."]

    def test_multi_line_message_survives(self, tmp_path):
        """The reason JSONL exists here: real emails have paragraphs."""
        path = _write(
            tmp_path, "z.jsonl", '{"text": "Dzień dobry,\\n\\nchcę zwrot.\\n\\nPozdrawiam"}\n'
        )

        assert parse_tickets(path) == ["Dzień dobry,\n\nchcę zwrot.\n\nPozdrawiam"]

    def test_broken_json_names_the_line(self, tmp_path):
        path = _write(tmp_path, "z.jsonl", '{"text": "ok"}\n{to nie jest json}\n')

        with pytest.raises(BatchFormatError, match="linia 2"):
            parse_tickets(path)

    def test_missing_text_field_names_the_line(self, tmp_path):
        path = _write(tmp_path, "z.jsonl", '{"subject": "zwrot"}\n')

        with pytest.raises(BatchFormatError, match="linia 1"):
            parse_tickets(path)


class TestCsv:
    def test_reads_the_text_column(self, tmp_path):
        path = _write(tmp_path, "z.csv", "id,text\n1,Chcę zwrot.\n2,Gdzie paczka?\n")

        assert parse_tickets(path) == ["Chcę zwrot.", "Gdzie paczka?"]

    def test_missing_column_lists_what_was_found(self, tmp_path):
        """A wrong column name must not look like an empty file."""
        path = _write(tmp_path, "z.csv", "id,subject\n1,zwrot\n")

        with pytest.raises(BatchFormatError, match="subject"):
            parse_tickets(path)


class TestRefusals:
    def test_missing_file_is_reported_clearly(self, tmp_path):
        with pytest.raises(BatchFormatError, match="nie istnieje"):
            parse_tickets(tmp_path / "nie-ma.txt")

    def test_empty_file_is_an_error_not_an_empty_run(self, tmp_path):
        """Otherwise the tool reports a successful run over nothing."""
        path = _write(tmp_path, "z.txt", "\n\n# tylko komentarz\n")

        with pytest.raises(BatchFormatError, match="Brak zgłoszeń"):
            parse_tickets(path)
