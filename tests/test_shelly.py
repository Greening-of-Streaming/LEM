from lem.devices.shelly import _select_gen2_meter


def test_meter_switch_relay():
    # A relay-with-metering plug (Plug S/Plus/Pro) exposes switch:0.
    status = {"switch:0": {"apower": 12.3}, "sys": {}, "wifi": {}}
    assert _select_gen2_meter(status) == ("Switch.GetStatus?id=0", "apower")


def test_meter_pm_only_plug():
    # The Shelly Plug PM G3 has NO switch — power lives under pm1:0. Regression:
    # LEM used to query Switch.GetStatus here, 404, and report a flat 0 W.
    status = {"pm1:0": {"apower": 1.5}, "plugpm_ui": {}, "sys": {}}
    assert _select_gen2_meter(status) == ("PM1.GetStatus?id=0", "apower")


def test_meter_energy_monitor():
    status = {"em1:0": {"act_power": 42.0}, "sys": {}}
    assert _select_gen2_meter(status) == ("EM1.GetStatus?id=0", "act_power")


def test_meter_switch_wins_when_both_present():
    status = {"switch:0": {"apower": 5}, "pm1:0": {"apower": 5}}
    assert _select_gen2_meter(status) == ("Switch.GetStatus?id=0", "apower")


def test_meter_falls_back_to_switch_when_unknown():
    assert _select_gen2_meter({"sys": {}, "wifi": {}}) == ("Switch.GetStatus?id=0", "apower")
