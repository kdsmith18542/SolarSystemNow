"""Settings view."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from .base_view import BaseView


class SettingsView(BaseView):
    def __init__(self, store, parent=None) -> None:
        super().__init__(store, parent)
        layout = QVBoxLayout(self)
        layout.setSpacing(16)
        form = QFormLayout()

        # Location inputs
        self.loc_name = QLineEdit()
        self.loc_name.setPlaceholderText("Name (e.g. Home)")
        self.loc_lat = QLineEdit()
        self.loc_lat.setPlaceholderText("Latitude (e.g. 51.5074)")
        self.loc_lon = QLineEdit()
        self.loc_lon.setPlaceholderText("Longitude (e.g. -0.1278)")
        loc_row = QHBoxLayout()
        loc_row.addWidget(self.loc_name)
        loc_row.addWidget(self.loc_lat)
        loc_row.addWidget(self.loc_lon)
        loc_add = QPushButton("Add location")
        loc_add.clicked.connect(self._add_location)
        loc_row.addWidget(loc_add)
        form.addRow("Add location:", loc_row)

        # Saved locations list & delete
        self.loc_list = QListWidget()
        self.loc_list.setMaximumHeight(90)
        loc_list_row = QHBoxLayout()
        loc_list_row.addWidget(self.loc_list)
        loc_del_btn = QPushButton("Remove selected")
        loc_del_btn.clicked.connect(self._delete_location)
        loc_list_row.addWidget(loc_del_btn)
        form.addRow("Saved locations:", loc_list_row)

        # Tide station inputs
        self.tide_id = QLineEdit()
        self.tide_id.setPlaceholderText("e.g. 8454000")
        self.tide_name = QLineEdit()
        self.tide_name.setPlaceholderText("Label")
        tide_row = QHBoxLayout()
        tide_row.addWidget(self.tide_id)
        tide_row.addWidget(self.tide_name)
        tide_add = QPushButton("Add tide station")
        tide_add.clicked.connect(self._add_tide_station)
        tide_row.addWidget(tide_add)
        form.addRow("Add tide station:", tide_row)

        # Saved tide stations list & delete
        self.tide_list = QListWidget()
        self.tide_list.setMaximumHeight(80)
        tide_list_row = QHBoxLayout()
        tide_list_row.addWidget(self.tide_list)
        tide_del_btn = QPushButton("Remove selected")
        tide_del_btn.clicked.connect(self._delete_tide_station)
        tide_list_row.addWidget(tide_del_btn)
        form.addRow("Saved tide stations:", tide_list_row)

        self.nasa_key = QLineEdit()
        self.nasa_key.setEchoMode(QLineEdit.EchoMode.Password)
        form.addRow("NASA API key (optional):", self.nasa_key)

        self.retention = QSpinBox()
        self.retention.setRange(1, 3650)
        self.retention.setValue(90)
        self.retention.setSuffix(" days")
        form.addRow("Snapshot retention:", self.retention)

        self.db_path_lbl = QLabel()
        self.db_path_lbl.setStyleSheet("color: #666; font-size: 12px;")
        form.addRow("Database path:", self.db_path_lbl)

        btn_row = QHBoxLayout()
        self.save_btn = QPushButton("Save settings")
        self.save_btn.clicked.connect(self._save)
        self.backup_btn = QPushButton("Export backup…")
        self.backup_btn.clicked.connect(self._export)
        btn_row.addWidget(self.save_btn)
        btn_row.addWidget(self.backup_btn)
        btn_row.addStretch(1)
        form.addRow(btn_row)

        layout.addLayout(form)
        layout.addStretch(1)
        self.refresh()

    def refresh(self) -> None:
        self.loc_list.clear()
        locations = self.store.get_setting("locations") or []
        for loc in locations:
            item_text = f"{loc.get('name', 'Location')} ({loc.get('lat')}, {loc.get('lon')})"
            item = QListWidgetItem(item_text)
            item.setData(100, loc.get("key"))
            self.loc_list.addItem(item)

        self.tide_list.clear()
        tide_stations = self.store.get_setting("tide_stations") or []
        for station in tide_stations:
            item_text = f"{station.get('name', station.get('id'))} (ID: {station.get('id')})"
            item = QListWidgetItem(item_text)
            item.setData(100, station.get("id"))
            self.tide_list.addItem(item)

        self.nasa_key.setText(self.store.get_setting("nasa_api_key") or "")
        self.retention.setValue(self.store.get_setting("retention_days", 90))
        self.db_path_lbl.setText(str(self.store.db_path))

    def _add_location(self) -> None:
        name = self.loc_name.text().strip()
        try:
            lat = float(self.loc_lat.text())
            lon = float(self.loc_lon.text())
        except ValueError:
            QMessageBox.warning(self, "Invalid input", "Enter numeric latitude and longitude.")
            return
        locations = self.store.get_setting("locations") or []
        key = f"{lat:.4f},{lon:.4f}"
        locations = [l for l in locations if l.get("key") != key]
        locations.insert(0, {"name": name or key, "lat": lat, "lon": lon, "key": key})
        self.store.set_setting("locations", locations)
        self.loc_name.clear()
        self.loc_lat.clear()
        self.loc_lon.clear()
        self.refresh()

    def _delete_location(self) -> None:
        selected = self.loc_list.currentItem()
        if not selected:
            return
        key = selected.data(100)
        locations = self.store.get_setting("locations") or []
        locations = [l for l in locations if l.get("key") != key]
        self.store.set_setting("locations", locations)
        self.refresh()

    def _add_tide_station(self) -> None:
        station_id = self.tide_id.text().strip()
        name = self.tide_name.text().strip() or station_id
        if not station_id:
            QMessageBox.warning(self, "Invalid input", "Enter a NOAA tide station ID.")
            return
        stations = self.store.get_setting("tide_stations") or []
        stations = [s for s in stations if s.get("id") != station_id]
        stations.insert(0, {"id": station_id, "name": name})
        self.store.set_setting("tide_stations", stations)
        self.tide_id.clear()
        self.tide_name.clear()
        self.refresh()

    def _delete_tide_station(self) -> None:
        selected = self.tide_list.currentItem()
        if not selected:
            return
        station_id = selected.data(100)
        stations = self.store.get_setting("tide_stations") or []
        stations = [s for s in stations if s.get("id") != station_id]
        self.store.set_setting("tide_stations", stations)
        self.refresh()

    def _save(self) -> None:
        self.store.set_setting("nasa_api_key", self.nasa_key.text().strip() or None)
        self.store.set_setting("retention_days", self.retention.value())
        QMessageBox.information(self, "Settings", "Settings saved.")

    def _export(self) -> None:
        dest, _ = QFileDialog.getSaveFileName(self, "Export backup", "ssnow-backup.tar.gz", "*.tar.gz")
        if not dest:
            return
        try:
            path = self.store.export_backup(Path(dest))
            QMessageBox.information(self, "Backup", f"Backup written to {path}")
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Backup failed", str(exc))
