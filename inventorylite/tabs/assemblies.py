from __future__ import annotations

import logging
import sqlite3
import tkinter as tk
from tkinter import ttk, messagebox
from typing import Callable

from inventorylite import db
from inventorylite.ui_components import TableFrame
from inventorylite.utils import Settings, show_error


class AssembliesTab:
    def __init__(self, parent: ttk.Notebook, settings: Settings, on_data_changed: Callable[[], None]) -> None:
        self.parent = parent
        self.settings = settings
        self.on_data_changed = on_data_changed

        self.frame = ttk.Frame(parent)
        self.group_table: TableFrame | None = None
        self.slot_table: TableFrame | None = None

        self._build()

    def _build(self) -> None:
        container = ttk.Frame(self.frame)
        container.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)

        groups_frame = ttk.LabelFrame(container, text="Групи компонентів")
        groups_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 6))
        group_columns = [
            ("code", "Код", 140),
            ("name", "Назва", 200),
            ("note", "Примітка", 200),
        ]
        self.group_table = TableFrame(groups_frame, group_columns, settings=self.settings, persist_key="component_groups")
        self.group_table.pack(fill=tk.BOTH, expand=True, padx=6, pady=6)
        self.group_table.on_double_click(self.edit_group)
        self.group_table.register_context_menu(self.edit_group, self.delete_group)

        group_btns = ttk.Frame(groups_frame)
        group_btns.pack(pady=4)
        ttk.Button(group_btns, text="Додати", command=self.add_group).pack(side=tk.LEFT, padx=4)
        ttk.Button(group_btns, text="Змінити", command=self.edit_group).pack(side=tk.LEFT, padx=4)
        ttk.Button(group_btns, text="Видалити", command=self.delete_group).pack(side=tk.LEFT, padx=4)
        ttk.Button(group_btns, text="Оновити", command=self.refresh_groups).pack(side=tk.LEFT, padx=4)

        slots_frame = ttk.LabelFrame(container, text="Слоти комплектування")
        slots_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(6, 0))
        slot_columns = [
            ("code", "Код", 160),
            ("name", "Назва", 200),
            ("note", "Примітка", 200),
        ]
        self.slot_table = TableFrame(slots_frame, slot_columns, settings=self.settings, persist_key="assembly_slots")
        self.slot_table.pack(fill=tk.BOTH, expand=True, padx=6, pady=6)
        self.slot_table.on_double_click(self.edit_slot)
        self.slot_table.register_context_menu(self.edit_slot, self.delete_slot)

        slot_btns = ttk.Frame(slots_frame)
        slot_btns.pack(pady=4)
        ttk.Button(slot_btns, text="Додати", command=self.add_slot).pack(side=tk.LEFT, padx=4)
        ttk.Button(slot_btns, text="Змінити", command=self.edit_slot).pack(side=tk.LEFT, padx=4)
        ttk.Button(slot_btns, text="Видалити", command=self.delete_slot).pack(side=tk.LEFT, padx=4)
        ttk.Button(slot_btns, text="Оновити", command=self.refresh_slots).pack(side=tk.LEFT, padx=4)

    def show(self) -> None:
        self.refresh_groups()
        self.refresh_slots()

    def refresh_groups(self) -> None:
        if not self.group_table:
            return
        try:
            rows = db.list_component_groups()
        except Exception:
            logging.exception("Failed to load component groups")
            show_error("Комплектації", "Не вдалося завантажити групи компонентів.")
            return
        self.group_table.set_rows(
            [{"id": r["id"], "code": r["code"], "name": r["name"], "note": r.get("note") or ""} for r in rows]
        )

    def refresh_slots(self) -> None:
        if not self.slot_table:
            return
        try:
            rows = db.list_assembly_slots()
        except Exception:
            logging.exception("Failed to load assembly slots")
            show_error("Комплектації", "Не вдалося завантажити слоти комплектування.")
            return
        self.slot_table.set_rows(
            [{"id": r["id"], "code": r["code"], "name": r["name"], "note": r.get("note") or ""} for r in rows]
        )

    def _prompt_record(self, title: str, initial: dict | None = None) -> tuple[str, str, str | None] | None:
        window = tk.Toplevel(self.frame)
        window.title(title)
        window.transient(self.frame.winfo_toplevel())
        window.grab_set()

        ttk.Label(window, text="Код (без пробілів)").grid(row=0, column=0, sticky="w", padx=8, pady=(8, 2))
        code_var = tk.StringVar(value=(initial or {}).get("code", ""))
        code_entry = ttk.Entry(window, textvariable=code_var, width=40)
        code_entry.grid(row=0, column=1, sticky="ew", padx=8, pady=(8, 2))

        ttk.Label(window, text="Назва").grid(row=1, column=0, sticky="w", padx=8, pady=2)
        name_var = tk.StringVar(value=(initial or {}).get("name", ""))
        name_entry = ttk.Entry(window, textvariable=name_var, width=40)
        name_entry.grid(row=1, column=1, sticky="ew", padx=8, pady=2)

        ttk.Label(window, text="Примітка").grid(row=2, column=0, sticky="w", padx=8, pady=2)
        note_var = tk.StringVar(value=(initial or {}).get("note", "") or "")
        note_entry = ttk.Entry(window, textvariable=note_var, width=40)
        note_entry.grid(row=2, column=1, sticky="ew", padx=8, pady=2)

        window.columnconfigure(1, weight=1)

        result: tuple[str, str, str | None] | None = None

        def on_ok() -> None:
            nonlocal result
            code = code_var.get().strip()
            name = name_var.get().strip()
            note = note_var.get().strip() or None
            if not code or not name:
                messagebox.showerror("Помилка вводу", "Код та назва не можуть бути порожніми.", parent=window)
                return
            if any(ch.isspace() for ch in code):
                messagebox.showerror("Помилка вводу", "Код не може містити пробіли.", parent=window)
                return
            result = (code, name, note)
            window.destroy()

        def on_cancel() -> None:
            window.destroy()

        ttk.Button(window, text="OK", command=on_ok).grid(row=3, column=0, padx=8, pady=8, sticky="e")
        ttk.Button(window, text="Скасувати", command=on_cancel).grid(row=3, column=1, padx=8, pady=8, sticky="w")
        window.bind("<Return>", lambda _e: on_ok())
        window.bind("<Escape>", lambda _e: on_cancel())
        code_entry.focus()
        window.wait_window()
        return result

    def add_group(self) -> None:
        values = self._prompt_record("Нова група компонентів")
        if not values:
            return
        try:
            db.create_component_group(*values)
            self.refresh_groups()
            self.on_data_changed()
        except sqlite3.IntegrityError:
            show_error("Групи компонентів", "Код або назва групи вже існує. Використовуйте унікальний код.")
        except Exception:
            logging.exception("Failed to add component group")
            show_error("Групи компонентів", "Не вдалося додати групу компонентів.")

    def edit_group(self) -> None:
        if not self.group_table:
            return
        group_id = self.group_table.selected_id()
        if not group_id:
            show_error("Групи компонентів", "Оберіть групу для редагування.")
            return
        current = next((g for g in db.list_component_groups() if int(g["id"]) == int(group_id)), None)
        values = self._prompt_record("Редагувати групу компонентів", current or {})
        if not values:
            return
        try:
            db.update_component_group(int(group_id), *values)
            self.refresh_groups()
            self.on_data_changed()
        except sqlite3.IntegrityError:
            show_error("Групи компонентів", "Код або назва групи вже існує. Використовуйте унікальний код.")
        except Exception:
            logging.exception("Failed to edit component group")
            show_error("Групи компонентів", "Не вдалося змінити групу компонентів.")

    def delete_group(self) -> None:
        if not self.group_table:
            return
        group_id = self.group_table.selected_id()
        if not group_id:
            show_error("Групи компонентів", "Оберіть групу для видалення.")
            return
        if not messagebox.askyesno("Підтвердження", "Видалити групу компонентів?"):
            return
        try:
            db.delete_component_group(int(group_id))
            self.refresh_groups()
            self.on_data_changed()
        except Exception:
            logging.exception("Failed to delete component group")
            show_error("Групи компонентів", "Не вдалося видалити групу компонентів.")

    def add_slot(self) -> None:
        values = self._prompt_record("Новий слот комплектування")
        if not values:
            return
        try:
            db.create_assembly_slot(*values)
            self.refresh_slots()
            self.on_data_changed()
        except sqlite3.IntegrityError:
            show_error("Слоти комплектування", "Код або назва слоту вже існує. Використовуйте унікальний код.")
        except Exception:
            logging.exception("Failed to add assembly slot")
            show_error("Слоти комплектування", "Не вдалося додати слот комплектування.")

    def edit_slot(self) -> None:
        if not self.slot_table:
            return
        slot_id = self.slot_table.selected_id()
        if not slot_id:
            show_error("Слоти комплектування", "Оберіть слот для редагування.")
            return
        current = next((s for s in db.list_assembly_slots() if int(s["id"]) == int(slot_id)), None)
        values = self._prompt_record("Редагувати слот комплектування", current or {})
        if not values:
            return
        try:
            db.update_assembly_slot(int(slot_id), *values)
            self.refresh_slots()
            self.on_data_changed()
        except sqlite3.IntegrityError:
            show_error("Слоти комплектування", "Код або назва слоту вже існує. Використовуйте унікальний код.")
        except Exception:
            logging.exception("Failed to edit assembly slot")
            show_error("Слоти комплектування", "Не вдалося змінити слот комплектування.")

    def delete_slot(self) -> None:
        if not self.slot_table:
            return
        slot_id = self.slot_table.selected_id()
        if not slot_id:
            show_error("Слоти комплектування", "Оберіть слот для видалення.")
            return
        if not messagebox.askyesno("Підтвердження", "Видалити слот комплектування?"):
            return
        try:
            db.delete_assembly_slot(int(slot_id))
            self.refresh_slots()
            self.on_data_changed()
        except Exception:
            logging.exception("Failed to delete assembly slot")
            show_error("Слоти комплектування", "Не вдалося видалити слот комплектування.")

