"""The Heating Coil Controller"""
"""Author: Jozef Moravcik"""
"""email: jozef.moravcik@moravcik.eu"""

""" config_change_logger.py """

"""
Logger zmien konfiguračných parametrov heating_coil_controller.

Pri každej zmene konfigurácie (uložení options flow) sa zaznamená
kompletný snapshot všetkých parametrov s časovou značkou.
Porovnaním dvoch po sebe idúcich snapshotov je možné zistiť,
čo sa kedy zmenilo.

Log súbor: config/analysis/heating_coil_controller/csv/_config_changes_log.csv
"""

import csv
import os
from datetime import datetime

CONFIG_CHANGE_LOG_PATH = "/config/logs/heating_coil_controller/_config_changes_log.csv"


def log_config_snapshot(entry_id: str, title: str, config: dict):
    """Zaznamená snapshot konfiguračných parametrov do CSV súboru.

    Každý riadok = jeden parameter s časovou značkou.
    Parametre sa dajú filtrovať podľa entry_id a timestamp.

    Args:
        entry_id: ID config entry
        title: názov zariadenia
        config: aktuálna konfigurácia (data + options)
    """
    os.makedirs(os.path.dirname(CONFIG_CHANGE_LOG_PATH), exist_ok=True)

    file_exists = os.path.exists(CONFIG_CHANGE_LOG_PATH)
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    with open(CONFIG_CHANGE_LOG_PATH, "a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f, delimiter=";")
        if not file_exists:
            writer.writerow(["timestamp", "entry_id", "title", "parameter", "value"])

        for key in sorted(config.keys()):
            writer.writerow([now_str, entry_id[:8], title, key, config[key]])
