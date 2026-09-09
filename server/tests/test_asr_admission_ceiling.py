"""Admission ceilings for the Whisper and sherpa CPU ASR backends.

Companion to ``test_sensevoice_capability_injection``. SenseVoice already had a
profile→capability chain; Whisper and sherpa hardcoded their ceilings inside
voxedge (1 and 4), so no profile could raise them and ``/asr`` returned 429 for
every request past the first. Both now read the value from their config
dataclass, and this module pins the product half of that chain: the shared
resolver, the two builders, and the three shipped profiles.

voxedge is an optional extra and is absent on a dev host, so the config
dataclasses are stubbed — the same reason and the same technique the SenseVoice
module uses. A failed import degrades to ``ConcurrencyCapability.default()``
(max_concurrent=1), which would let a "defaults to 1" assertion pass while
proving nothing.
"""
from __future__ import annotations

import json
import sys
import types
from dataclasses import dataclass, fields
from pathlib import Path

import pytest

from server.core import voxedge_backend_config as vbc

_PROFILE_DIR = Path(__file__).resolve().parents[2] / "configs" / "profiles"

_ADMISSION_ENV = (
    "SENSEVOICE_MAX_CONCURRENT",
    "WHISPER_MAX_CONCURRENT",
    "SHERPA_ASR_MAX_CONCURRENT",
)


@pytest.fixture(autouse=True)
def _clear_env(monkeypatch):
    for name in _ADMISSION_ENV:
        monkeypatch.delenv(name, raising=False)


# ── _resolve_asr_slots: env → profile asr_max_slots → default ────────

def test_slots_default_when_nothing_is_set():
    assert vbc._resolve_asr_slots("X_MAX", 4, profile={}, env={}) == 4


def test_slots_from_profile_top_level():
    assert vbc._resolve_asr_slots("X_MAX", 1, profile={"asr_max_slots": 8}, env={}) == 8


@pytest.mark.parametrize("key", ["asr_max_slots", "max_concurrent"])
def test_slots_from_nested_asr_block(key):
    profile = {"asr": {key: 6}}
    assert vbc._resolve_asr_slots("X_MAX", 1, profile=profile, env=profile and {}) == 6


def test_env_beats_profile():
    assert (
        vbc._resolve_asr_slots(
            "X_MAX", 1, profile={"asr_max_slots": 8}, env={"X_MAX": "2"}
        )
        == 2
    )


@pytest.mark.parametrize("raw", ["0", "-4"])
def test_non_positive_env_is_clamped_to_one(raw):
    assert vbc._resolve_asr_slots("X_MAX", 4, profile={}, env={"X_MAX": raw}) == 1


def test_unparseable_env_falls_back_to_default_rather_than_raising():
    # A capacity hint must not be able to take the service down at boot.
    assert vbc._resolve_asr_slots("X_MAX", 4, profile={}, env={"X_MAX": "eight"}) == 4


def test_unparseable_profile_value_falls_back_to_default():
    assert (
        vbc._resolve_asr_slots("X_MAX", 4, profile={"asr_max_slots": "eight"}, env={})
        == 4
    )


# ── _with_optional_max_concurrent: tolerate an older voxedge ─────────

@dataclass
class _WithField:
    max_concurrent: int = 1


@dataclass
class _WithoutField:
    other: int = 0


def test_field_is_passed_when_the_dataclass_declares_it():
    kwargs = vbc._with_optional_max_concurrent(_WithField, {}, 8, "x.y", default=1)
    assert kwargs == {"max_concurrent": 8}


def test_field_is_dropped_on_an_older_voxedge(caplog):
    with caplog.at_level("WARNING"):
        kwargs = vbc._with_optional_max_concurrent(
            _WithoutField, {"other": 1}, 8, "x.y", default=1
        )
    assert kwargs == {"other": 1}
    # Silence here is the failure mode the guard exists for: the knob would
    # look wired up and do nothing.
    assert "x.y" in caplog.text


def test_no_warning_when_the_request_matches_the_built_in_default(caplog):
    with caplog.at_level("WARNING"):
        vbc._with_optional_max_concurrent(_WithoutField, {}, 4, "x.y", default=4)
    assert caplog.text == ""


# ── sherpa builder ───────────────────────────────────────────────────

@pytest.fixture
def _stub_sherpa(monkeypatch):
    @dataclass
    class _StubSherpaConfig:
        language_mode: str = "zh_en"
        streaming_model_dir: object = None
        streaming_provider: str = "cuda"
        offline_provider: object = None
        num_threads: int = 4
        model_root: str = "/opt/models"
        offline_use_itn: bool = True
        offline_language: str = ""
        max_concurrent: int = 4

    for name in ("voxedge", "voxedge.backends", "voxedge.backends.sherpa",
                 "voxedge.backends.sherpa.asr"):
        monkeypatch.setitem(sys.modules, name, types.ModuleType(name))
    sys.modules["voxedge.backends.sherpa.asr"].SherpaASRConfig = _StubSherpaConfig
    return _StubSherpaConfig


def test_sherpa_default_ceiling_is_the_historical_four(_stub_sherpa):
    cfg = vbc.build_sherpa_asr_config(profile={}, env={})
    assert cfg.max_concurrent == 4


def test_sherpa_profile_raises_the_ceiling(_stub_sherpa):
    cfg = vbc.build_sherpa_asr_config(profile={"asr_max_slots": 8}, env={})
    assert cfg.max_concurrent == 8


def test_sherpa_env_overrides_the_profile(_stub_sherpa):
    cfg = vbc.build_sherpa_asr_config(
        profile={"asr_max_slots": 8}, env={"SHERPA_ASR_MAX_CONCURRENT": "2"}
    )
    assert cfg.max_concurrent == 2


def test_sherpa_other_fields_are_untouched(_stub_sherpa):
    """The admission change must not move any existing default."""
    cfg = vbc.build_sherpa_asr_config(profile={"asr_max_slots": 8}, env={})
    assert cfg.language_mode == "zh_en"
    assert cfg.streaming_provider == "cuda"
    assert cfg.offline_provider == "cuda"
    assert cfg.num_threads == 4
    assert cfg.model_root == "/opt/models"
    assert cfg.offline_use_itn is True
    assert cfg.offline_language == ""


def test_sherpa_builder_survives_a_voxedge_without_the_field(monkeypatch, caplog):
    @dataclass
    class _OldSherpaConfig:
        language_mode: str = "zh_en"
        streaming_model_dir: object = None
        streaming_provider: str = "cuda"
        offline_provider: object = None
        num_threads: int = 4
        model_root: str = "/opt/models"
        offline_use_itn: bool = True
        offline_language: str = ""

    for name in ("voxedge", "voxedge.backends", "voxedge.backends.sherpa",
                 "voxedge.backends.sherpa.asr"):
        monkeypatch.setitem(sys.modules, name, types.ModuleType(name))
    sys.modules["voxedge.backends.sherpa.asr"].SherpaASRConfig = _OldSherpaConfig

    with caplog.at_level("WARNING"):
        cfg = vbc.build_sherpa_asr_config(profile={"asr_max_slots": 8}, env={})
    assert not any(f.name == "max_concurrent" for f in fields(cfg))
    assert "cpu.sherpa_asr" in caplog.text


# ── whisper builder ──────────────────────────────────────────────────

@pytest.fixture
def _stub_whisper(monkeypatch):
    @dataclass
    class _StubWhisperConfig:
        encoder_kind: str = ""
        encoder_path: str = ""
        decoder_dir: str = ""
        vocab_dir: str = ""
        window_s: float = 30.0
        language: str = "en"
        padding_cutoff_s: float = 0.0
        decoder_threads: int = 0
        max_new_tokens: object = None
        all_cores: bool = False
        max_concurrent: int = 1

    pkg = types.ModuleType("voxedge.backends.whisper")
    pkg.WhisperASRConfig = _StubWhisperConfig
    for name in ("voxedge", "voxedge.backends"):
        monkeypatch.setitem(sys.modules, name, types.ModuleType(name))
    monkeypatch.setitem(sys.modules, "voxedge.backends.whisper", pkg)
    return _StubWhisperConfig


_WHISPER_ENV = {"WHISPER_VARIANT": "base", "MODEL_DIR": "/opt/models"}


def test_whisper_default_ceiling_is_one(_stub_whisper):
    cfg = vbc.build_whisper_trt_asr_config(profile={}, env=dict(_WHISPER_ENV))
    assert cfg.max_concurrent == 1


def test_whisper_profile_raises_the_ceiling(_stub_whisper):
    cfg = vbc.build_whisper_trt_asr_config(
        profile={"asr_max_slots": 8}, env=dict(_WHISPER_ENV)
    )
    assert cfg.max_concurrent == 8


def test_whisper_env_overrides_the_profile(_stub_whisper):
    env = dict(_WHISPER_ENV, WHISPER_MAX_CONCURRENT="3")
    cfg = vbc.build_whisper_trt_asr_config(profile={"asr_max_slots": 8}, env=env)
    assert cfg.max_concurrent == 3


@pytest.mark.parametrize(
    "builder,variant",
    [
        # Each encoder path ships its own variant names (the window is baked
        # into the artifact), so the ceiling has to be checked per path rather
        # than assumed to ride along from the TRT one.
        (vbc.build_whisper_hailo_asr_config, "base"),
        (vbc.build_whisper_rk_asr_config, "base10"),
        (vbc.build_whisper_trt_asr_config, "base"),
    ],
)
def test_every_whisper_encoder_path_honours_the_ceiling(
    _stub_whisper, builder, variant
):
    env = dict(_WHISPER_ENV, WHISPER_VARIANT=variant)
    cfg = builder(profile={"asr_max_slots": 5}, env=env)
    assert cfg.max_concurrent == 5


def test_whisper_geometry_still_comes_from_the_variant(_stub_whisper):
    """The ceiling must not disturb the shape fields, which select the graph."""
    cfg = vbc.build_whisper_trt_asr_config(
        profile={"asr_max_slots": 8}, env=dict(_WHISPER_ENV)
    )
    assert cfg.encoder_kind == "tensorrt"
    assert cfg.window_s == 30.0
    assert cfg.language == "en"


# ── the shipped profiles ─────────────────────────────────────────────

@pytest.mark.parametrize(
    "name",
    ["jetson-sensevoice", "orin-whisper", "rpi5-sensevoice"],
)
def test_benchmarked_profiles_admit_eight(name):
    """These three carry the measured c=1..8 concurrency results.

    A profile that admits 1 makes every c>=2 request a 429, which is what the
    first bench round actually measured.
    """
    profile = json.loads((_PROFILE_DIR / f"{name}.json").read_text())
    assert profile["asr_max_slots"] == 8
    assert profile["max_concurrent_sessions"] == 8


@pytest.mark.parametrize(
    "name",
    ["jetson-sensevoice", "orin-whisper", "rpi5-sensevoice"],
)
def test_profile_session_ceiling_never_exceeds_its_backend_slots(name):
    """capability_resolver clamps the session ceiling to the backend ceiling.

    Declaring more sessions than slots is not an error, it is silently reduced
    — so the two numbers must be written together or the profile lies.
    """
    profile = json.loads((_PROFILE_DIR / f"{name}.json").read_text())
    assert profile["max_concurrent_sessions"] <= profile["asr_max_slots"]
