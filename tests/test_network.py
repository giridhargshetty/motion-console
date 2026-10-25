import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "prototype"))
from network import friendly_error, parse_devices, parse_wifi_list, split_terse  # noqa: E402


def test_parse_devices_on_a_box_without_wifi():
    # What the Wyse 7040 reports: cable + phone tethering, no Wi-Fi adapter.
    text = "ethernet:connected\nethernet:connected\ntun:connected (externally)\nloopback:connected (externally)\n"
    assert parse_devices(text) == (False, True)
    assert parse_devices("wifi:disconnected\nethernet:unavailable\n") == (True, False)


def test_split_terse_handles_escaped_colons():
    assert split_terse(r"*:Office\:2:55:WPA2") == ["*", "Office:2", "55", "WPA2"]


def test_parse_wifi_list_dedupes_sorts_and_finds_current():
    text = "\n".join([
        " :Neighbour:40:WPA2",
        "*:Home:70:WPA2 WPA3",
        " :Home:85:WPA2 WPA3",   # same name on another band: keep the strongest
        " ::90:WPA2",            # hidden network: skipped
        " :Cafe:30:",            # open network
    ])
    networks, in_use = parse_wifi_list(text)
    assert networks == [("Home", 85, True), ("Neighbour", 40, True), ("Cafe", 30, False)]
    assert in_use == "Home"


def test_friendly_error_for_wrong_password():
    assert "password" in friendly_error("Error: Connection activation failed: Secrets were required, but not provided.")
