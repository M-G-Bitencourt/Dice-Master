"""Tests for the ANSI rendering helpers in utils/ansi.py."""

from __future__ import annotations

from utils.ansi import (
    DANGER_COLOR,
    LABEL_COLOR,
    NEUTRAL_COLOR,
    RESET,
    SUCCESS_COLOR,
    WARN_COLOR,
    ansi,
    bar_segments,
    clamp_code_block,
    code_block,
    pad,
    paginate_rows,
    resource_bar,
    sanitize,
    severity_color,
    truncate_visible,
    visible_len,
)


class TestSanitize:
    def test_replaces_each_backtick_with_a_single_quote(self):
        assert sanitize("a`b``c") == "a'b''c"

    def test_leaves_text_without_backticks_unchanged(self):
        assert sanitize("plain text") == "plain text"

    def test_empty_string_stays_empty(self):
        assert sanitize("") == ""


class TestAnsi:
    def test_wraps_sanitized_text_in_sgr_sequence(self):
        assert ansi("x`y", "1;31") == f"\x1b[1;31mx'y{RESET}"

    def test_appends_module_reset_after_content(self):
        assert ansi("ok", "0") == f"\x1b[0mok{RESET}"


class TestCodeBlock:
    def test_joins_lines_inside_ansi_fence(self):
        assert code_block(["a", "b"]) == "```ansi\na\nb\n```"

    def test_empty_line_list_produces_empty_body(self):
        assert code_block([]) == "```ansi\n\n```"


class TestVisibleLen:
    def test_counts_plain_characters(self):
        assert visible_len("abc") == 3

    def test_ignores_complete_sgr_sequences(self):
        assert visible_len(f"\x1b[1;31mabc{RESET}") == 3

    def test_empty_string_is_zero(self):
        assert visible_len("") == 0

    def test_incomplete_escape_sequence_is_counted_verbatim(self):
        assert visible_len("\x1b[31") == 4


class TestTruncateVisible:
    def test_returns_short_text_unchanged(self):
        assert truncate_visible("abc", 5) == "abc"

    def test_returns_text_at_exact_width_unchanged(self):
        assert truncate_visible("abcde", 5) == "abcde"

    def test_long_text_gets_ascii_ellipsis(self):
        assert truncate_visible("abcdefgh", 6) == "abc..."

    def test_width_three_truncates_without_ellipsis(self):
        assert truncate_visible("abcdef", 3) == "abc"

    def test_width_two_truncates_without_ellipsis(self):
        assert truncate_visible("abcdef", 2) == "ab"

    def test_width_zero_returns_empty_string(self):
        assert truncate_visible("abcdef", 0) == ""

    def test_negative_width_slices_from_the_end(self):
        # Current behavior: widths <= 3 take plain[:width] directly, so a
        # negative width removes characters from the end instead of returning
        # an empty prefix. Pinned as-is; reported as a minor edge-case risk.
        assert truncate_visible("abcdef", -1) == "abcde"

    def test_sanitizes_backticks_before_truncating(self):
        assert truncate_visible("a`b", 10) == "a'b"


class TestPad:
    def test_pads_with_spaces_to_requested_visible_width(self):
        assert pad("abc", 5) == "abc  "

    def test_text_at_exact_width_is_unchanged(self):
        assert pad("abc", 3) == "abc"

    def test_text_wider_than_width_is_unchanged(self):
        assert pad("abcdef", 4) == "abcdef"

    def test_uses_visible_width_for_colored_text(self):
        colored = f"\x1b[31mabc{RESET}"
        assert pad(colored, 5) == f"{colored}  "

    def test_empty_text_and_zero_width(self):
        assert pad("", 0) == ""


class TestSeverityColor:
    def test_zero_maximum_is_neutral(self):
        assert severity_color(5, 0) == NEUTRAL_COLOR

    def test_negative_maximum_is_neutral(self):
        assert severity_color(5, -10) == NEUTRAL_COLOR

    def test_ratio_at_two_thirds_is_success(self):
        assert severity_color(2, 3) == SUCCESS_COLOR

    def test_ratio_above_two_thirds_is_success(self):
        assert severity_color(7, 9) == SUCCESS_COLOR

    def test_current_above_maximum_is_success(self):
        assert severity_color(11, 10) == SUCCESS_COLOR

    def test_ratio_between_thirds_is_warning(self):
        assert severity_color(1, 2) == WARN_COLOR

    def test_ratio_at_one_third_is_warning(self):
        assert severity_color(1, 3) == WARN_COLOR

    def test_ratio_below_one_third_is_danger(self):
        assert severity_color(1, 4) == DANGER_COLOR

    def test_negative_current_is_danger(self):
        assert severity_color(-5, 10) == DANGER_COLOR


class TestBarSegments:
    def test_full_bar_has_only_filled_segment(self):
        assert bar_segments(10, 10, 4) == ("####", "")

    def test_half_bar_splits_evenly(self):
        assert bar_segments(5, 10, 4) == ("##", "--")

    def test_fractional_segment_uses_bankers_rounding(self):
        # Current behavior: Python round() uses banker's rounding, so
        # 0.125 * 20 = 2.5 yields 2 filled segments instead of 3.
        assert bar_segments(1, 8, 20) == ("##", "-" * 18)

    def test_zero_maximum_yields_empty_track(self):
        assert bar_segments(5, 0, 4) == ("", "----")

    def test_negative_maximum_yields_empty_track(self):
        assert bar_segments(5, -2, 4) == ("", "----")

    def test_negative_current_is_clamped_to_zero(self):
        assert bar_segments(-3, 10, 4) == ("", "----")

    def test_current_above_maximum_is_clamped_to_full(self):
        assert bar_segments(99, 10, 4) == ("####", "")

    def test_zero_width_returns_two_empty_strings(self):
        assert bar_segments(5, 10, 0) == ("", "")

    def test_segment_lengths_always_add_up_to_width(self):
        for current, maximum in ((0, 10), (3, 10), (10, 10)):
            filled, empty = bar_segments(current, maximum, 7)
            assert len(filled) + len(empty) == 7


class TestResourceBar:
    def test_full_bar_has_no_empty_track(self):
        expected = (
            f"{ansi('PV', LABEL_COLOR)} "
            f"[{ansi('##', SUCCESS_COLOR)}] "
            f"{ansi('10/10', SUCCESS_COLOR)}"
        )
        assert resource_bar("PV", 10, 10, width=2) == expected

    def test_empty_bar_has_no_filled_segment(self):
        expected = (
            f"{ansi('PV', LABEL_COLOR)} "
            f"[{ansi('--', NEUTRAL_COLOR)}] "
            f"{ansi('0/10', DANGER_COLOR)}"
        )
        assert resource_bar("PV", 0, 10, width=2) == expected

    def test_zero_maximum_uses_neutral_color(self):
        expected = (
            f"{ansi('PV', LABEL_COLOR)} "
            f"[{ansi('--', NEUTRAL_COLOR)}] "
            f"{ansi('0/0', NEUTRAL_COLOR)}"
        )
        assert resource_bar("PV", 0, 0, width=2) == expected

    def test_label_backticks_are_sanitized(self):
        rendered = resource_bar("P`V", 5, 10, width=2)
        assert "`" not in rendered
        assert "P'V" in rendered

    def test_default_width_is_twenty(self):
        filled, empty = bar_segments(5, 10, 20)
        expected = (
            f"{ansi('PV', LABEL_COLOR)} "
            f"[{ansi(filled, WARN_COLOR)}{ansi(empty, NEUTRAL_COLOR)}] "
            f"{ansi('5/10', WARN_COLOR)}"
        )
        assert resource_bar("PV", 5, 10) == expected


class TestClampCodeBlock:
    def test_value_within_limit_is_returned_unchanged(self):
        assert clamp_code_block("abc", 5) == "abc"

    def test_value_at_exact_limit_is_returned_unchanged(self):
        assert clamp_code_block("abcde", 5) == "abcde"

    def test_even_fence_count_returns_plain_cut(self):
        assert clamp_code_block("a```b```c", 8) == "a```b```"

    def test_no_fence_returns_plain_cut(self):
        assert clamp_code_block("x" * 10, 4) == "xxxx"

    def test_zero_limit_with_even_fence_count_returns_empty(self):
        assert clamp_code_block("abc", 0) == ""

    def test_odd_fence_count_appends_reset_and_closing_fence(self):
        value = "```abc" + "z" * 10
        assert clamp_code_block(value, 10) == "``" + RESET + "\n```"

    def test_odd_fence_truncates_to_last_complete_sgr_sequence(self):
        value = "xxxx" + "\x1b[31m" + "yyy" + "\x1b[1m" + "```" + "abcdefgh"
        expected = "xxxx\x1b[31m" + RESET + "\n```"
        assert clamp_code_block(value, 22) == expected

    def test_tiny_limit_returns_closing_suffix_longer_than_limit(self):
        # Current behavior: when the limit is smaller than the closing suffix,
        # the payload is expanded beyond the requested limit so the fence
        # stays balanced. Pinned as-is; reported as a clamping edge case.
        value = "```" + "abcdefgh"
        result = clamp_code_block(value, 4)
        assert result == RESET + "\n```"
        assert len(result) > 4


class TestPaginateRows:
    def test_empty_rows_produce_no_pages(self):
        assert list(paginate_rows([], 0)) == []

    def test_splits_when_length_budget_is_exceeded(self):
        rows = [("p1", "aaaa"), ("p2", "bbbb"), ("p3", "cccc")]
        pages = list(paginate_rows(rows, base_length=0, budget=12))
        assert pages == [[("p1", "aaaa"), ("p2", "bbbb")], [("p3", "cccc")]]

    def test_base_length_counts_towards_the_budget(self):
        rows = [("p1", "aaaa"), ("p2", "bbbb")]
        pages = list(paginate_rows(rows, base_length=8, budget=12))
        assert pages == [[("p1", "aaaa")], [("p2", "bbbb")]]

    def test_max_rows_caps_each_page(self):
        rows = [(index, "x") for index in range(30)]
        pages = list(paginate_rows(rows, base_length=0, budget=10000, max_rows=25))
        assert [len(page) for page in pages] == [25, 5]
        assert pages[0][0] == (0, "x")
        assert pages[1][-1] == (29, "x")

    def test_max_rows_boundary_keeps_exactly_twenty_five(self):
        rows = [(index, "x") for index in range(25)]
        pages = list(paginate_rows(rows, base_length=0, budget=10000, max_rows=25))
        assert len(pages) == 1
        assert len(pages[0]) == 25

    def test_row_larger_than_budget_still_gets_a_page(self):
        big = ("big", "x" * 50)
        small = ("small", "y")
        pages = list(paginate_rows([big, small], base_length=0, budget=10))
        assert pages == [[big], [small]]

    def test_single_oversized_row_is_preserved(self):
        big = ("big", "x" * 50)
        assert list(paginate_rows([big], base_length=0, budget=10)) == [[big]]

    def test_default_budget_is_used_when_not_provided(self):
        rows = [("p1", "a" * 1000), ("p2", "b" * 1000)]
        pages = list(paginate_rows(rows, base_length=0))
        assert [len(page) for page in pages] == [1, 1]

    def test_payloads_are_preserved_by_identity(self):
        payload = object()
        pages = list(paginate_rows([(payload, "line")], base_length=0))
        assert pages[0][0][0] is payload
