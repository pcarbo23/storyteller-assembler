import pytest
import numpy as np
import soundfile as sf
import pyloudnorm as pyln
from pathlib import Path
import tempfile
import json

from src.dtb_converter import normalize_audio_loudness, DTBConverter
from src.main import get_configured_target_lufs


@pytest.fixture
def temp_audio_dir():
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


def create_synthetic_audio(filepath: Path, duration_s: float = 2.0, sr: int = 44100, channels: int = 1, amplitude: float = 0.2):
    """Generates synthetic tone audio file."""
    t = np.linspace(0, duration_s, int(sr * duration_s), endpoint=False)
    freq = 440.0
    tone = np.sin(2 * np.pi * freq * t) * amplitude
    if channels == 2:
        audio_data = np.stack([tone, tone], axis=-1)
    else:
        audio_data = tone
    sf.write(str(filepath), audio_data, sr, subtype="PCM_16")
    return filepath, audio_data, sr


def test_normalize_audio_loudness_default_target(temp_audio_dir):
    """Test normalization to default -21.0 LUFS."""
    in_wav = temp_audio_dir / "input.wav"
    out_wav = temp_audio_dir / "output.wav"
    create_synthetic_audio(in_wav, duration_s=2.0, amplitude=0.1)

    result_path = normalize_audio_loudness(in_wav, out_wav, target_lufs=-21.0)
    assert result_path.exists()

    data, rate = sf.read(str(out_wav))
    meter = pyln.Meter(rate)
    measured_loudness = meter.integrated_loudness(data)

    assert pytest.approx(measured_loudness, abs=0.2) == -21.0


def test_normalize_audio_loudness_custom_levels(temp_audio_dir):
    """Test normalization to custom louder and quieter LUFS levels."""
    in_wav = temp_audio_dir / "input.wav"
    create_synthetic_audio(in_wav, duration_s=2.0, amplitude=0.1)

    for target in [-18.0, -23.5, -16.0]:
        out_wav = temp_audio_dir / f"output_{target}.wav"
        normalize_audio_loudness(in_wav, out_wav, target_lufs=target)
        
        data, rate = sf.read(str(out_wav))
        meter = pyln.Meter(rate)
        measured_loudness = meter.integrated_loudness(data)
        assert pytest.approx(measured_loudness, abs=0.2) == target


def test_normalize_stereo_audio(temp_audio_dir):
    """Test normalization on stereo input."""
    in_wav = temp_audio_dir / "stereo_input.wav"
    out_wav = temp_audio_dir / "stereo_output.wav"
    create_synthetic_audio(in_wav, duration_s=2.0, channels=2, amplitude=0.08)

    normalize_audio_loudness(in_wav, out_wav, target_lufs=-21.0)
    data, rate = sf.read(str(out_wav))
    assert data.ndim == 2
    assert data.shape[1] == 2

    meter = pyln.Meter(rate)
    measured_loudness = meter.integrated_loudness(data)
    assert pytest.approx(measured_loudness, abs=0.2) == -21.0


def test_normalize_silence_handling(temp_audio_dir):
    """Test that pure silence is handled gracefully without NaN or crashing."""
    in_wav = temp_audio_dir / "silence.wav"
    out_wav = temp_audio_dir / "silence_out.wav"
    sr = 44100
    sf.write(str(in_wav), np.zeros((sr * 2,), dtype=np.float32), sr, subtype="PCM_16")

    result = normalize_audio_loudness(in_wav, out_wav, target_lufs=-21.0)
    assert result.exists()
    data, rate = sf.read(str(out_wav))
    assert np.all(data == 0.0)


def test_peak_clipping_protection(temp_audio_dir):
    """Test peak clipping limiter protects against peaks exceeding max_peak_db."""
    in_wav = temp_audio_dir / "hot_input.wav"
    out_wav = temp_audio_dir / "hot_output.wav"
    # Create very quiet signal normalized to very loud level (-6 LUFS) to force potential overshoot
    create_synthetic_audio(in_wav, duration_s=1.0, amplitude=0.01)

    max_peak_db = -1.0
    normalize_audio_loudness(in_wav, out_wav, target_lufs=-6.0, max_peak_db=max_peak_db)
    
    data, rate = sf.read(str(out_wav))
    peak = np.max(np.abs(data))
    max_allowed = 10.0 ** (max_peak_db / 20.0)
    assert peak <= max_allowed + 1e-4


def test_dtb_converter_integration(temp_audio_dir):
    """Test that DTBConverter.convert_audio_to_wav normalizes output to target_lufs."""
    in_wav = temp_audio_dir / "source.wav"
    out_wav = temp_audio_dir / "target.wav"
    create_synthetic_audio(in_wav, duration_s=1.5, amplitude=0.05)

    converter = DTBConverter(prod_id="db10050", work_dir=temp_audio_dir, target_lufs=-22.5)
    result = converter.convert_audio_to_wav(in_wav, out_wav)
    assert result.exists()

    data, rate = sf.read(str(out_wav))
    meter = pyln.Meter(rate)
    measured = meter.integrated_loudness(data)
    assert pytest.approx(measured, abs=0.2) == -22.5


def test_get_configured_target_lufs():
    """Test reading target LUFS from production config."""
    lufs = get_configured_target_lufs()
    assert isinstance(lufs, float)
    assert lufs == -21.0
