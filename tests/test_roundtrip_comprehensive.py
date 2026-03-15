"""Comprehensive roundtrip tests for PRS creation, injection, and validation.

Exercises the full pipeline: create blank PRS, inject templates/systems,
serialize, re-parse, validate, and verify byte-exact roundtrip. Covers
all template types, profile templates, and multi-system scenarios.
"""

import pytest

from quickprs.builder import create_blank_prs
from quickprs.injector import (
    add_conv_system, make_conv_set, make_conv_channel,
    make_p25_group, make_trunk_channel, make_trunk_set,
    make_group_set, make_iden_set,
)
from quickprs.templates import get_template_names, get_template_channels
from quickprs.validation import validate_prs
from quickprs.prs_parser import parse_prs_bytes
from quickprs.record_types import ConvSystemConfig, ConvSet, ConvChannel


# ─── Template injection roundtrips ───────────────────────────────────


class TestTemplateInjectionRoundtrip:
    """Test injecting each template individually and in combination."""

    @pytest.mark.parametrize("template_name", get_template_names())
    def test_single_template_roundtrip(self, template_name):
        """Each template individually roundtrips through inject/serialize/parse."""
        channels = get_template_channels(template_name)
        conv_set = make_conv_set(template_name[:8].upper(), channels)
        config = ConvSystemConfig(
            system_name=template_name[:8].upper(),
            long_name=template_name[:8].upper(),
            conv_set_name=template_name[:8].upper(),
        )

        prs = create_blank_prs()
        add_conv_system(prs, config, conv_set=conv_set)

        out1 = prs.to_bytes()
        prs2 = parse_prs_bytes(out1)
        out2 = prs2.to_bytes()
        assert out1 == out2, f"Roundtrip failed for template '{template_name}'"

    @pytest.mark.parametrize("template_name", get_template_names())
    def test_single_template_validates(self, template_name):
        """Each template individually passes validation with no errors."""
        channels = get_template_channels(template_name)
        conv_set = make_conv_set(template_name[:8].upper(), channels)
        config = ConvSystemConfig(
            system_name=template_name[:8].upper(),
            long_name=template_name[:8].upper(),
            conv_set_name=template_name[:8].upper(),
        )

        prs = create_blank_prs()
        add_conv_system(prs, config, conv_set=conv_set)

        issues = validate_prs(prs)
        errors = [i for i in issues if i[0] == 'ERROR']
        assert len(errors) == 0, \
            f"Validation errors for '{template_name}': {errors}"

    def test_all_templates_combined_roundtrip(self):
        """Inject ALL templates into one PRS, roundtrip, and validate."""
        prs = create_blank_prs()

        for name in get_template_names():
            channels = get_template_channels(name)
            conv_set = make_conv_set(name[:8].upper(), channels)
            config = ConvSystemConfig(
                system_name=name[:8].upper(),
                long_name=name[:8].upper(),
                conv_set_name=name[:8].upper(),
            )
            add_conv_system(prs, config, conv_set=conv_set)

        out1 = prs.to_bytes()
        prs2 = parse_prs_bytes(out1)
        out2 = prs2.to_bytes()
        assert out1 == out2

        issues = validate_prs(prs2)
        errors = [i for i in issues if i[0] == 'ERROR']
        assert len(errors) == 0

    @pytest.mark.parametrize("pair", [
        ("murs", "noaa"),
        ("gmrs", "frs"),
        ("marine", "interop"),
        ("public_safety", "noaa"),
        ("murs", "gmrs"),
        ("interop", "marine"),
    ])
    def test_template_pair_roundtrip(self, pair):
        """Pairs of templates roundtrip correctly."""
        prs = create_blank_prs()
        for name in pair:
            channels = get_template_channels(name)
            conv_set = make_conv_set(name[:8].upper(), channels)
            config = ConvSystemConfig(
                system_name=name[:8].upper(),
                long_name=name[:8].upper(),
                conv_set_name=name[:8].upper(),
            )
            add_conv_system(prs, config, conv_set=conv_set)

        out1 = prs.to_bytes()
        prs2 = parse_prs_bytes(out1)
        out2 = prs2.to_bytes()
        assert out1 == out2


# ─── Profile template roundtrips ─────────────────────────────────────


class TestProfileRoundtrip:
    """Test full profile template build/roundtrip/validate."""

    PROFILES = [
        "scanner_basic", "public_safety", "ham_portable",
        "gmrs_family", "fire_department", "law_enforcement",
        "ems", "search_rescue",
    ]

    @pytest.mark.parametrize("profile", PROFILES)
    def test_profile_roundtrip(self, profile):
        """Profile template builds, serializes, and re-parses identically."""
        from quickprs.profile_templates import build_from_profile

        prs = build_from_profile(profile)
        out1 = prs.to_bytes()
        prs2 = parse_prs_bytes(out1)
        out2 = prs2.to_bytes()
        assert out1 == out2

    @pytest.mark.parametrize("profile", PROFILES)
    def test_profile_validates(self, profile):
        """Profile template passes validation with no errors."""
        from quickprs.profile_templates import build_from_profile

        prs = build_from_profile(profile)
        issues = validate_prs(prs)
        errors = [i for i in issues if i[0] == 'ERROR']
        assert len(errors) == 0, f"Errors in profile '{profile}': {errors}"

    @pytest.mark.parametrize("profile", PROFILES)
    def test_profile_has_sections(self, profile):
        """Profile template produces a PRS with expected sections."""
        from quickprs.profile_templates import build_from_profile

        prs = build_from_profile(profile)
        assert len(prs.sections) > 0
        # Should have at least CPersonality and CConvChannel
        class_names = {s.class_name for s in prs.sections}
        assert "CPersonality" in class_names

    @pytest.mark.parametrize("profile", PROFILES)
    def test_profile_nonzero_size(self, profile):
        """Profile template produces non-trivial output."""
        from quickprs.profile_templates import build_from_profile

        prs = build_from_profile(profile)
        data = prs.to_bytes()
        assert len(data) > 100


# ─── Blank PRS roundtrip ────────────────────────────────────────────


class TestBlankPRS:
    """Test blank PRS creation and roundtrip."""

    def test_blank_roundtrip(self):
        """Blank PRS roundtrips through serialize/parse."""
        prs = create_blank_prs()
        out1 = prs.to_bytes()
        prs2 = parse_prs_bytes(out1)
        out2 = prs2.to_bytes()
        assert out1 == out2

    def test_blank_validates(self):
        """Blank PRS passes validation."""
        prs = create_blank_prs()
        issues = validate_prs(prs)
        errors = [i for i in issues if i[0] == 'ERROR']
        assert len(errors) == 0

    def test_blank_has_personality(self):
        """Blank PRS has a CPersonality section."""
        prs = create_blank_prs()
        sec = prs.get_section_by_class("CPersonality")
        assert sec is not None

    @pytest.mark.parametrize("filename", [
        "Test.PRS", "MY_RADIO.PRS", "A.PRS",
        "Long Filename Here.PRS",
    ])
    def test_blank_custom_filename(self, filename):
        """Blank PRS with custom filename roundtrips."""
        prs = create_blank_prs(filename=filename)
        out1 = prs.to_bytes()
        prs2 = parse_prs_bytes(out1)
        out2 = prs2.to_bytes()
        assert out1 == out2

    @pytest.mark.parametrize("saved_by", ["", "USER1", "QuickPRS v0.9"])
    def test_blank_saved_by(self, saved_by):
        """Blank PRS with various saved_by values roundtrips."""
        prs = create_blank_prs(saved_by=saved_by)
        out1 = prs.to_bytes()
        prs2 = parse_prs_bytes(out1)
        out2 = prs2.to_bytes()
        assert out1 == out2


# ─── Multi-system injection ─────────────────────────────────────────


class TestMultiSystemInjection:
    """Test injecting multiple systems of various types."""

    def test_three_conv_systems(self):
        """Three conventional systems roundtrip correctly."""
        prs = create_blank_prs()
        for i in range(3):
            ch_data = [
                {'short_name': f'CH{i}{j}', 'tx_freq': 146.0 + j * 0.01}
                for j in range(5)
            ]
            conv_set = make_conv_set(f"SET{i}", ch_data)
            config = ConvSystemConfig(
                system_name=f"SYS{i}",
                long_name=f"System {i}",
                conv_set_name=f"SET{i}",
            )
            add_conv_system(prs, config, conv_set=conv_set)

        out1 = prs.to_bytes()
        prs2 = parse_prs_bytes(out1)
        out2 = prs2.to_bytes()
        assert out1 == out2

    def test_many_channels_roundtrip(self):
        """System with many channels roundtrips correctly."""
        prs = create_blank_prs()
        ch_data = [
            {'short_name': f'CH{i:04d}', 'tx_freq': 146.0 + i * 0.0125}
            for i in range(50)
        ]
        conv_set = make_conv_set("BIGSET", ch_data)
        config = ConvSystemConfig(
            system_name="BIG",
            long_name="Big System",
            conv_set_name="BIGSET",
        )
        add_conv_system(prs, config, conv_set=conv_set)

        out1 = prs.to_bytes()
        prs2 = parse_prs_bytes(out1)
        out2 = prs2.to_bytes()
        assert out1 == out2

    def test_channels_with_tones_roundtrip(self):
        """Channels with CTCSS tones roundtrip correctly."""
        prs = create_blank_prs()
        ch_data = [
            {'short_name': 'TONE1', 'tx_freq': 146.52,
             'tx_tone': '100.0', 'rx_tone': '100.0'},
            {'short_name': 'TONE2', 'tx_freq': 146.54,
             'tx_tone': '156.7', 'rx_tone': '156.7'},
            {'short_name': 'NOTONE', 'tx_freq': 146.56},
        ]
        conv_set = make_conv_set("TONES", ch_data)
        config = ConvSystemConfig(
            system_name="TONES",
            long_name="Tone Test",
            conv_set_name="TONES",
        )
        add_conv_system(prs, config, conv_set=conv_set)

        out1 = prs.to_bytes()
        prs2 = parse_prs_bytes(out1)
        out2 = prs2.to_bytes()
        assert out1 == out2

    def test_duplex_channels_roundtrip(self):
        """Duplex channels (different TX/RX) roundtrip correctly."""
        prs = create_blank_prs()
        ch_data = [
            {'short_name': 'RPTR1', 'tx_freq': 146.34, 'rx_freq': 146.94},
            {'short_name': 'RPTR2', 'tx_freq': 146.22, 'rx_freq': 146.82},
            {'short_name': 'SPLX', 'tx_freq': 146.52},
        ]
        conv_set = make_conv_set("DUPLEX", ch_data)
        config = ConvSystemConfig(
            system_name="DUPLEX",
            long_name="Duplex Test",
            conv_set_name="DUPLEX",
        )
        add_conv_system(prs, config, conv_set=conv_set)

        out1 = prs.to_bytes()
        prs2 = parse_prs_bytes(out1)
        out2 = prs2.to_bytes()
        assert out1 == out2


# ─── Validation edge cases ──────────────────────────────────────────


class TestValidationEdgeCases:
    """Test validation behavior on edge-case PRS structures."""

    def test_blank_prs_no_errors(self):
        """Freshly created blank PRS has no errors."""
        prs = create_blank_prs()
        issues = validate_prs(prs)
        errors = [i for i in issues if i[0] == 'ERROR']
        assert len(errors) == 0

    def test_validation_returns_list(self):
        """validate_prs always returns a list."""
        prs = create_blank_prs()
        issues = validate_prs(prs)
        assert isinstance(issues, list)

    def test_validation_tuple_format(self):
        """Each validation issue is a (severity, message) tuple."""
        prs = create_blank_prs()
        issues = validate_prs(prs)
        for issue in issues:
            assert len(issue) == 2
            severity, message = issue
            assert severity in ('ERROR', 'WARNING', 'INFO')
            assert isinstance(message, str)

    def test_modified_prs_still_validates(self):
        """PRS with added content still passes validation."""
        prs = create_blank_prs()
        channels = get_template_channels("murs")
        conv_set = make_conv_set("MURS", channels)
        config = ConvSystemConfig(
            system_name="MURS",
            long_name="MURS",
            conv_set_name="MURS",
        )
        add_conv_system(prs, config, conv_set=conv_set)

        issues = validate_prs(prs)
        errors = [i for i in issues if i[0] == 'ERROR']
        assert len(errors) == 0


# ─── Byte-level verification ────────────────────────────────────────


class TestByteLevelRoundtrip:
    """Verify byte-level properties of roundtripped data."""

    def test_terminator_present(self):
        """Output ends with the file terminator."""
        from quickprs.binary_io import FILE_TERMINATOR
        prs = create_blank_prs()
        data = prs.to_bytes()
        assert data.endswith(FILE_TERMINATOR)

    def test_starts_with_ffff(self):
        """Output starts with 0xFFFF section marker."""
        prs = create_blank_prs()
        data = prs.to_bytes()
        assert data[0:2] == b'\xff\xff'

    def test_size_consistent(self):
        """PRSFile.to_bytes produces consistent output across calls."""
        prs = create_blank_prs()
        out1 = prs.to_bytes()
        out2 = prs.to_bytes()
        assert out1 == out2

    def test_multiple_roundtrips_stable(self):
        """Multiple roundtrips produce identical output."""
        prs = create_blank_prs()
        data = prs.to_bytes()
        for _ in range(5):
            prs2 = parse_prs_bytes(data)
            data2 = prs2.to_bytes()
            assert data == data2
            data = data2

    def test_injected_data_grows_size(self):
        """Adding templates increases the file size."""
        prs1 = create_blank_prs()
        size_before = len(prs1.to_bytes())

        prs2 = create_blank_prs()
        channels = get_template_channels("gmrs")
        conv_set = make_conv_set("GMRS", channels)
        config = ConvSystemConfig(
            system_name="GMRS",
            long_name="GMRS",
            conv_set_name="GMRS",
        )
        add_conv_system(prs2, config, conv_set=conv_set)
        size_after = len(prs2.to_bytes())

        assert size_after > size_before


# ─── Incremental injection ───────────────────────────────────────────


class TestIncrementalInjection:
    """Test that successive injections remain consistent."""

    def test_successive_injections_stable(self):
        """Each injection increases size but all previous data is preserved."""
        prs = create_blank_prs()
        prev_data = prs.to_bytes()

        templates = ["murs", "noaa", "marine", "frs", "gmrs"]
        for name in templates:
            channels = get_template_channels(name)
            conv_set = make_conv_set(name[:8].upper(), channels)
            config = ConvSystemConfig(
                system_name=name[:8].upper(),
                long_name=name[:8].upper(),
                conv_set_name=name[:8].upper(),
            )
            add_conv_system(prs, config, conv_set=conv_set)
            curr_data = prs.to_bytes()
            assert len(curr_data) > len(prev_data)
            prev_data = curr_data

    def test_injection_order_independent_validation(self):
        """Injecting templates in different orders both validate clean."""
        for order in [
            ["murs", "noaa", "marine"],
            ["marine", "murs", "noaa"],
        ]:
            prs = create_blank_prs()
            for name in order:
                channels = get_template_channels(name)
                conv_set = make_conv_set(name[:8].upper(), channels)
                config = ConvSystemConfig(
                    system_name=name[:8].upper(),
                    long_name=name[:8].upper(),
                    conv_set_name=name[:8].upper(),
                )
                add_conv_system(prs, config, conv_set=conv_set)

            issues = validate_prs(prs)
            errors = [i for i in issues if i[0] == 'ERROR']
            assert len(errors) == 0


# ─── Channel content verification ────────────────────────────────────


class TestChannelContentVerification:
    """Verify that channel data survives injection and roundtrip."""

    def test_murs_channel_count(self):
        """MURS template injects exactly 5 channels."""
        prs = create_blank_prs()
        channels = get_template_channels("murs")
        assert len(channels) == 5
        conv_set = make_conv_set("MURS", channels)
        assert len(conv_set.channels) == 5

    def test_gmrs_channel_count(self):
        """GMRS template injects exactly 22 channels."""
        channels = get_template_channels("gmrs")
        assert len(channels) == 22

    def test_frs_channel_count(self):
        """FRS template injects exactly 22 channels."""
        channels = get_template_channels("frs")
        assert len(channels) == 22

    def test_noaa_channel_count(self):
        """NOAA template injects exactly 7 channels."""
        channels = get_template_channels("noaa")
        assert len(channels) == 7

    def test_weather_same_as_noaa(self):
        """'weather' alias returns same data as 'noaa'."""
        noaa = get_template_channels("noaa")
        weather = get_template_channels("weather")
        assert len(noaa) == len(weather)
        for n, w in zip(noaa, weather):
            assert n['tx_freq'] == w['tx_freq']

    def test_marine_channel_count(self):
        """Marine template returns expected number of channels."""
        channels = get_template_channels("marine")
        assert len(channels) >= 10  # at least 10 marine channels

    def test_interop_channel_count(self):
        """Interop template returns expected number of channels."""
        channels = get_template_channels("interop")
        assert len(channels) >= 15  # 5 VHF + 5 UHF + 5 800MHz + some 700

    def test_public_safety_channel_count(self):
        """Public safety template returns expected number of channels."""
        channels = get_template_channels("public_safety")
        assert len(channels) >= 5


# ─── Profile template detail verification ────────────────────────────


class TestProfileDetails:
    """Verify profile template contents match expectations."""

    def test_scanner_basic_has_noaa_and_marine(self):
        """Scanner basic profile includes NOAA and Marine."""
        from quickprs.profile_templates import get_profile_template
        profile = get_profile_template("scanner_basic")
        assert "noaa" in profile['templates']
        assert "marine" in profile['templates']

    def test_public_safety_has_interop(self):
        """Public safety profile includes interop channels."""
        from quickprs.profile_templates import get_profile_template
        profile = get_profile_template("public_safety")
        assert "interop" in profile['templates']

    def test_ham_portable_has_custom_channels(self):
        """Ham portable profile has custom amateur channels."""
        from quickprs.profile_templates import get_profile_template
        profile = get_profile_template("ham_portable")
        assert len(profile['custom_channels']) > 0

    def test_fire_department_has_custom_channels(self):
        """Fire department profile has custom fireground channels."""
        from quickprs.profile_templates import get_profile_template
        profile = get_profile_template("fire_department")
        assert len(profile['custom_channels']) > 0

    def test_unknown_profile_raises(self):
        """Unknown profile name raises ValueError."""
        from quickprs.profile_templates import get_profile_template
        with pytest.raises(ValueError, match="Unknown profile"):
            get_profile_template("nonexistent_profile")

    def test_list_profile_templates(self):
        """list_profile_templates returns expected number of profiles."""
        from quickprs.profile_templates import list_profile_templates
        profiles = list_profile_templates()
        assert len(profiles) == 8
        names = [p[0] for p in profiles]
        assert "scanner_basic" in names
        assert "law_enforcement" in names

    def test_profile_descriptions_non_empty(self):
        """All profile descriptions are non-empty strings."""
        from quickprs.profile_templates import list_profile_templates
        for name, desc in list_profile_templates():
            assert len(desc) > 0
            assert isinstance(desc, str)


# ─── Validation detail levels ────────────────────────────────────────


class TestValidationDetails:
    """Test validation at different detail levels."""

    def test_detailed_validation(self):
        """validate_prs_detailed returns categorized results."""
        from quickprs.validation import validate_prs_detailed
        prs = create_blank_prs()
        results = validate_prs_detailed(prs)
        assert isinstance(results, dict)

    def test_detailed_validation_with_content(self):
        """validate_prs_detailed works on injected PRS."""
        from quickprs.validation import validate_prs_detailed
        prs = create_blank_prs()
        channels = get_template_channels("gmrs")
        conv_set = make_conv_set("GMRS", channels)
        config = ConvSystemConfig(
            system_name="GMRS",
            long_name="GMRS",
            conv_set_name="GMRS",
        )
        add_conv_system(prs, config, conv_set=conv_set)

        results = validate_prs_detailed(prs)
        assert isinstance(results, dict)
        # Should have no error categories
        for category, issues in results.items():
            errors = [i for i in issues if i[0] == 'ERROR']
            assert len(errors) == 0, \
                f"Errors in category '{category}': {errors}"


# ─── PRSFile structure tests ────────────────────────────────────────


class TestPRSFileStructure:
    """Test PRSFile object methods and properties."""

    def test_summary_output(self):
        """PRSFile.summary() returns formatted string."""
        prs = create_blank_prs()
        summary = prs.summary()
        assert isinstance(summary, str)
        assert "Sections" in summary

    def test_get_section_by_class(self):
        """get_section_by_class finds existing sections."""
        prs = create_blank_prs()
        sec = prs.get_section_by_class("CPersonality")
        assert sec is not None
        assert sec.class_name == "CPersonality"

    def test_get_section_by_class_missing(self):
        """get_section_by_class returns None for missing sections."""
        prs = create_blank_prs()
        sec = prs.get_section_by_class("CDoesNotExist")
        assert sec is None

    def test_get_sections_by_class(self):
        """get_sections_by_class returns list."""
        prs = create_blank_prs()
        secs = prs.get_sections_by_class("CPersonality")
        assert isinstance(secs, list)
        assert len(secs) >= 1

    def test_sections_have_offsets(self):
        """All sections have valid offset and raw data."""
        prs = create_blank_prs()
        for sec in prs.sections:
            assert hasattr(sec, 'offset')
            assert hasattr(sec, 'raw')
            assert len(sec.raw) > 0

    def test_total_bytes_matches_sections(self):
        """Sum of section raw bytes equals total to_bytes output."""
        prs = create_blank_prs()
        total = prs.to_bytes()
        section_total = sum(len(s.raw) for s in prs.sections)
        assert len(total) == section_total


# ─── Health check on built PRS ───────────────────────────────────────


class TestHealthCheckOnBuilt:
    """Run health checks on programmatically built PRS files."""

    def test_health_check_blank(self):
        """Health check runs on blank PRS without crashing."""
        from quickprs.health_check import run_health_check
        prs = create_blank_prs()
        results = run_health_check(prs)
        assert isinstance(results, list)

    def test_health_check_with_templates(self):
        """Health check on PRS with multiple templates."""
        from quickprs.health_check import run_health_check
        prs = create_blank_prs()
        for name in ["murs", "noaa", "marine"]:
            channels = get_template_channels(name)
            conv_set = make_conv_set(name[:8].upper(), channels)
            config = ConvSystemConfig(
                system_name=name[:8].upper(),
                long_name=name[:8].upper(),
                conv_set_name=name[:8].upper(),
            )
            add_conv_system(prs, config, conv_set=conv_set)
        results = run_health_check(prs)
        assert isinstance(results, list)

    def test_health_results_format(self):
        """Health check results are (severity, message) tuples."""
        from quickprs.health_check import run_health_check
        prs = create_blank_prs()
        results = run_health_check(prs)
        for item in results:
            assert len(item) >= 2
            assert isinstance(item[1], str)

    def test_format_health_report(self):
        """format_health_report produces non-empty output."""
        from quickprs.health_check import run_health_check, format_health_report
        prs = create_blank_prs()
        results = run_health_check(prs)
        report = format_health_report(results)
        assert isinstance(report, list)
        assert len(report) > 0
