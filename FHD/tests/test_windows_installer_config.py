from pathlib import Path

import yaml

FHD_ROOT = Path(__file__).resolve().parents[1]


def test_per_user_nsis_installer_does_not_enter_uac_plugin_path() -> None:
    config = yaml.safe_load(
        (FHD_ROOT / "desktop" / "electron-builder.yml").read_text(encoding="utf-8")
    )
    nsis = config["nsis"]

    assert nsis["perMachine"] is False
    assert nsis["allowElevation"] is False
    assert nsis["allowToChangeInstallationDirectory"] is True
