import sys


class TranscriptionOutput:
    """
    Handles transcription output to console.
    """

    def __init__(self, use_color: bool = False):
        self.use_color = use_color

    def print_text(self, text: str):
        """Print transcription text to stdout."""
        if text.strip():
            print(text)

    def print_partial(self, text: str):
        """Print partial transcription with carriage return for live preview."""
        if text.strip():
            sys.stdout.write(f"\r{text}")
            sys.stdout.flush()

    def print_progress(self, current: int, total: int, prefix: str = "Downloading"):
        """Print progress indicator."""
        if total > 0:
            percent = (current / total) * 100
            sys.stdout.write(f"\r{prefix}: {percent:.1f}%")
            sys.stdout.flush()
        else:
            sys.stdout.write(f"\r{prefix}...")
            sys.stdout.flush()

    def print_info(self, message: str):
        """Print info message."""
        print(message)

    def print_error(self, message: str):
        """Print error message to stderr."""
        print(message, file=sys.stderr)

    def print_stopped(self):
        """Print stopped message."""
        print("\nTranscription stopped.")
