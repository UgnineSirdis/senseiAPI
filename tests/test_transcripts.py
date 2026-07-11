from audio.schemas import diarized_segments_from_transcript
from transcription.models import Transcript, Word


def test_diarized_segments_empty_without_words() -> None:
    transcript = Transcript(text="hello", language="he")
    assert diarized_segments_from_transcript(transcript) == []


def test_diarized_segments_maps_words() -> None:
    transcript = Transcript(
        text="שלום עולם",
        language="he",
        words=(
            Word(text="שלום", start=0.0, end=0.4),
            Word(text="עולם", start=0.5, end=1.0),
        ),
    )
    assert diarized_segments_from_transcript(transcript) == [
        {"speaker": "unknown", "start_time": 0.0, "end_time": 0.4, "text": "שלום"},
        {"speaker": "unknown", "start_time": 0.5, "end_time": 1.0, "text": "עולם"},
    ]
