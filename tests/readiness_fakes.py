"""Explicit quiet event source for existing tests of unrelated browser contracts."""

from unittest.mock import Mock


def attach_quiet_loading_source(instance):
    instance.reset_loading()
    instance._event_source = Mock(main_frame_id="fake-frame", read_events=Mock(return_value=([], False)))
