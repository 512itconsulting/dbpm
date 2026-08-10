import io

from dbpm.progress import report_progress


class _FlushTrackingStream(io.StringIO):
    def __init__(self) -> None:
        super().__init__()
        self.flushed = False

    def flush(self) -> None:
        self.flushed = True
        super().flush()


def test_report_progress_uses_prefix_and_flushes() -> None:
    stream = _FlushTrackingStream()

    report_progress("Resolving dependencies...", stream=stream)

    assert stream.getvalue() == "dbpm: Resolving dependencies...\n"
    assert stream.flushed is True
