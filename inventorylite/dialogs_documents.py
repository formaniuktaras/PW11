from __future__ import annotations

import sqlite3
import tkinter as tk
from datetime import datetime
from tkinter import ttk, messagebox
from typing import Optional

from inventorylite import db, sku_gen, dates
from inventorylite.helpers import format_rate, parse_paste_lines, _find_index_by_name
from inventorylite.ui_components import DatePicker, rate_prompt
from inventorylite.utils import Settings, get_base_currency_code


def ensure_rate_for_date(currency_code: str, rate_date: str) -> float:
    currency_code = currency_code.strip().upper()
    rate_date = dates.normalize_date_to_iso(rate_date, field_label="Дата")
    base_currency = get_base_currency_code()
    if not currency_code or currency_code == base_currency:
        return 1.0
    existing = db.rate_on_date(currency_code, rate_date)
    if existing is not None:
        return existing
    suggestion: float | None = None
    try:
        suggestion = db.rate_on_or_before(currency_code, rate_date)
    except Exception:
        suggestion = None
    while True:
        if suggestion:
            direct_default = format_rate(suggestion)
            inverse_default = format_rate(1.0 / suggestion)
        else:
            direct_default = ""
            inverse_default = ""
        result = rate_prompt(
            "Курс валюти",
            currency_code,
            base_currency,
            initial_direct=direct_default,
            initial_inverse=inverse_default,
        )
        if not result:
            raise ValueError("Курс не вказано")
        rate = float(result["direct"])
        db.add_currency_rate(currency_code, rate_date, rate)
        return rate


def document_prompt(
    doc_type: str,
    products,
    counterparties,
    warehouses,
    channels,
    currencies,
    doc=None,
    lines=None,
    settings: Settings | None = None,
):
    dlg = tk.Toplevel()
    dlg.title("Документ")
    dlg.grab_set()
    editable = not doc or doc["status"] == "draft"

    if doc and isinstance(doc, sqlite3.Row):
        doc = dict(doc)

    dlg.columnconfigure(0, weight=1)
    dlg.rowconfigure(0, weight=1)
    content = ttk.Frame(dlg, padding=10)
    content.grid(row=0, column=0, sticky="nsew")
    content.columnconfigure(1, weight=1)

    row_idx = 0
    ttk.Label(content, text="Тип").grid(row=row_idx, column=0, padx=6, pady=4, sticky="e")
    doc_type_label = "Закупівля" if doc_type == "purchase" else "Продаж"
    ttk.Label(content, text=doc_type_label).grid(row=row_idx, column=1, padx=6, pady=4, sticky="w")

    row_idx += 1
    ttk.Label(content, text="Дата (ДД.ММ.РРРР)").grid(row=row_idx, column=0, padx=6, pady=4, sticky="e")
    date_picker = DatePicker(
        content,
        initial=doc["doc_date"] if doc else datetime.now().strftime("%Y-%m-%d"),
        state="normal" if editable else "disabled",
    )
    date_picker.grid(row=row_idx, column=1, padx=6, pady=4, sticky="w")

    row_idx += 1
    ttk.Label(content, text="Валюта").grid(row=row_idx, column=0, padx=6, pady=4, sticky="e")
    curr_var = tk.StringVar(
        value=doc["currency_code"]
        if doc
        else (currencies[0]["code"] if currencies else get_base_currency_code())
    )
    curr_codes = [c["code"] for c in currencies] if currencies else [get_base_currency_code()]
    curr_combo = ttk.Combobox(content, textvariable=curr_var, values=curr_codes, state="readonly")
    if not editable:
        curr_combo.state(["disabled"])
    curr_combo.grid(row=row_idx, column=1, padx=6, pady=4, sticky="w")
    last_currency = curr_var.get()

    row_idx += 1
    ttk.Label(content, text="Курс до базової").grid(row=row_idx, column=0, padx=6, pady=4, sticky="e")
    try:
        default_rate = doc["exchange_rate"] if doc else ensure_rate_for_date(curr_var.get(), date_picker.get())
    except Exception:
        default_rate = doc["exchange_rate"] if doc else 1.0
    rate_var = tk.StringVar(value=f"{default_rate:.4f}")
    rate_entry = ttk.Entry(content, textvariable=rate_var, width=12, state="normal" if editable else "disabled")
    rate_entry.grid(row=row_idx, column=1, padx=6, pady=4, sticky="w")

    row_idx += 1
    ttk.Label(content, text="Склад").grid(row=row_idx, column=0, padx=6, pady=4, sticky="e")
    wh_var = tk.StringVar()
    wh_names = [w["name"] for w in warehouses]
    wh_combo = ttk.Combobox(content, textvariable=wh_var, values=wh_names, state="readonly")
    wh_combo.grid(row=row_idx, column=1, padx=6, pady=4, sticky="w")

    row_idx += 1
    ch_var = tk.StringVar()
    ch_combo = None
    if doc_type == "sale":
        ttk.Label(content, text="Канал").grid(row=row_idx, column=0, padx=6, pady=4, sticky="e")
        ch_names = [c["name"] for c in channels]
        ch_combo = ttk.Combobox(content, textvariable=ch_var, values=ch_names, state="readonly")
        ch_combo.grid(row=row_idx, column=1, padx=6, pady=4, sticky="w")
        row_idx += 1

    ttk.Label(content, text="Контрагент").grid(row=row_idx, column=0, padx=6, pady=4, sticky="e")
    allowed_types = {"purchase": {"supplier", "both", "other"}, "sale": {"customer", "both", "other"}}[doc_type]
    filtered_counterparties = [c for c in counterparties if c["type"] in allowed_types]
    cp_names = ["-"] + [c["name"] for c in filtered_counterparties]
    cp_var = tk.StringVar()
    cp_combo = ttk.Combobox(content, textvariable=cp_var, values=cp_names, state="readonly", width=25)
    cp_combo.grid(row=row_idx, column=1, padx=6, pady=4, sticky="w")
    row_idx += 1

    ttk.Label(content, text="Коментар").grid(row=row_idx, column=0, padx=6, pady=4, sticky="e")
    comment_var = tk.StringVar(value=doc["comment"] if doc else "")
    ttk.Entry(content, textvariable=comment_var, width=40).grid(row=row_idx, column=1, padx=6, pady=4, sticky="ew")

    row_idx += 1
    order_expense_var = tk.StringVar(value=f"{float(doc.get('order_expense_doc', 0.0)):.2f}" if doc else "0")
    if doc_type == "sale":
        ttk.Label(content, text="Витрати замовлення").grid(row=row_idx, column=0, padx=6, pady=4, sticky="e")
        ttk.Entry(content, textvariable=order_expense_var, width=20).grid(row=row_idx, column=1, padx=6, pady=4, sticky="w")
        row_idx += 1

    scan_frame = ttk.LabelFrame(content, text="Сканування")
    scan_frame.grid(row=row_idx, column=0, columnspan=2, padx=6, pady=6, sticky="ew")
    scan_frame.columnconfigure(1, weight=1)

    ttk.Label(scan_frame, text="Скан-код").grid(row=0, column=0, padx=6, pady=4, sticky="e")
    scan_var = tk.StringVar()
    scan_entry = ttk.Entry(scan_frame, textvariable=scan_var, width=30, state="normal" if editable else "disabled")
    scan_entry.grid(row=0, column=1, padx=6, pady=4, sticky="w")
    ttk.Label(scan_frame, text="К-сть при скані").grid(row=0, column=2, padx=6, pady=4, sticky="e")
    scan_qty_var = tk.IntVar(value=1)
    scan_qty_spin = ttk.Spinbox(
        scan_frame,
        from_=1,
        to=999,
        textvariable=scan_qty_var,
        width=6,
        state="normal" if editable else "disabled",
    )
    scan_qty_spin.grid(row=0, column=3, padx=6, pady=4, sticky="w")
    scan_plus_one_var = tk.BooleanVar(value=False)
    scan_plus_one = ttk.Checkbutton(
        scan_frame,
        text="Кожен скан = +1",
        variable=scan_plus_one_var,
        state="normal" if editable else "disabled",
    )
    scan_plus_one.grid(row=0, column=4, padx=6, pady=4, sticky="w")
    scan_use_avg_cost_var = tk.BooleanVar(value=True)
    ttk.Checkbutton(
        scan_frame,
        text="Ціна зі середньої собівартості",
        variable=scan_use_avg_cost_var,
    ).grid(row=1, column=1, padx=6, pady=(0, 4), sticky="w")
    paste_btn = ttk.Button(
        scan_frame,
        text="Вставити список…",
        command=lambda: None,
        state="normal" if editable else "disabled",
    )
    paste_btn.grid(row=1, column=2, padx=6, pady=(0, 4), sticky="w")
    scan_status = ttk.Label(scan_frame, text="")
    scan_status.grid(row=2, column=0, columnspan=5, padx=6, pady=(0, 4), sticky="w")

    def _apply_scan_mode() -> None:
        if scan_plus_one_var.get():
            scan_qty_var.set(1)
            scan_qty_spin.config(state="disabled")
        else:
            scan_qty_spin.config(state="normal" if editable else "disabled")

    scan_plus_one.config(command=_apply_scan_mode)
    _apply_scan_mode()

    row_idx += 1
    ttk.Label(content, text="Рядки").grid(row=row_idx, column=0, padx=6, pady=4, sticky="ne")
    line_frame = ttk.Frame(content)
    line_frame.grid(row=row_idx, column=1, padx=6, pady=4, sticky="nsew")
    line_frame.grid_columnconfigure(0, weight=1)
    content.rowconfigure(row_idx, weight=1)

    columns = ["product", "quantity", "price", "amount"]
    tree = ttk.Treeview(line_frame, columns=columns, show="headings", height=8)
    headings = {
        "product": ("Товар", 200),
        "quantity": ("Кількість", 90),
        "price": ("Ціна", 90),
        "amount": ("Сума", 90),
    }
    for col, (title, width) in headings.items():
        tree.heading(col, text=title)
        tree.column(col, width=width, anchor="w")
    tree.grid(row=0, column=0, sticky="nsew")
    yscroll = ttk.Scrollbar(line_frame, orient="vertical", command=tree.yview)
    tree.configure(yscrollcommand=yscroll.set)
    yscroll.grid(row=0, column=1, sticky="ns")
    line_frame.grid_rowconfigure(0, weight=1)

    def refresh_currency_ui() -> None:
        price_label.config(text=f"Ціна ({curr_var.get()})")
        tree.heading("price", text=f"Ціна ({curr_var.get()})")
        tree.heading("amount", text=f"Сума ({curr_var.get()})")

    def on_currency_change(event=None):
        nonlocal last_currency
        if editable:
            try:
                rate_val = ensure_rate_for_date(curr_var.get(), date_picker.get())
            except ValueError as exc:
                messagebox.showerror("Курс", str(exc))
                curr_var.set(last_currency)
                return
            rate_var.set(f"{rate_val:.4f}")
            last_currency = curr_var.get()
        refresh_currency_ui()

    curr_combo.bind("<<ComboboxSelected>>", on_currency_change)

    product_lookup = {f"{p['name']} ({p['sku']})": p["id"] for p in products}
    products_by_id = {p["id"]: f"{p['name']} ({p['sku']})" for p in products}
    product_names = list(product_lookup.keys())

    row_idx += 1
    entry_frame = ttk.Frame(content)
    entry_frame.grid(row=row_idx, column=0, columnspan=2, padx=6, pady=4, sticky="ew")
    entry_frame.columnconfigure(1, weight=1)
    ttk.Label(entry_frame, text="Товар").grid(row=0, column=0, padx=4, pady=2, sticky="e")
    product_var = tk.StringVar()
    product_combo_state = "normal" if editable else "readonly"
    product_combo = ttk.Combobox(entry_frame, textvariable=product_var, values=product_names, state=product_combo_state, width=40)
    product_combo.grid(row=0, column=1, padx=4, pady=2, sticky="ew")
    if product_lookup:
        product_combo.current(0)

    def filter_products(event=None):
        if not editable:
            return
        text = product_var.get().lower()
        matches = [name for name in product_names if text in name.lower()]
        product_combo["values"] = matches if matches else product_names

    product_combo.bind("<KeyRelease>", filter_products)

    ttk.Label(entry_frame, text="Кількість").grid(row=0, column=2, padx=4, pady=2, sticky="e")
    qty_var = tk.StringVar(value="1")
    qty_entry = ttk.Entry(entry_frame, textvariable=qty_var, width=10)
    qty_entry.grid(row=0, column=3, padx=4, pady=2, sticky="w")

    price_label = ttk.Label(entry_frame, text="Ціна")
    price_label.grid(row=0, column=4, padx=4, pady=2, sticky="e")
    price_var = tk.StringVar(value="0")
    price_entry = ttk.Entry(entry_frame, textvariable=price_var, width=10)
    price_entry.grid(row=0, column=5, padx=4, pady=2, sticky="w")

    line_data = []
    if lines:
        for ln in lines:
            price_field = "purchase_price" if doc_type == "purchase" else "sale_price"
            line_data.append(
                {
                    "product_id": ln["product_id"],
                    "product_name": ln["product_name"],
                    "quantity": float(ln["quantity"]),
                    "price": float(ln[price_field]),
                    "amount": float(ln["quantity"]) * float(ln[price_field]),
                }
            )

    if doc:
        if doc["warehouse_id"]:
            try:
                wh_combo.current(next(i for i, w in enumerate(warehouses) if w["id"] == doc["warehouse_id"]))
            except StopIteration:
                wh_combo.set(warehouses[0]["name"] if warehouses else "")
        if curr_codes:
            try:
                curr_combo.current(curr_codes.index(doc.get("currency_code", curr_codes[0])))
            except ValueError:
                curr_combo.current(0)
        if doc_type == "sale" and ch_combo:
            if doc["channel"]:
                try:
                    ch_combo.current(next(i for i, c in enumerate(channels) if c["name"] == doc["channel"]))
                except StopIteration:
                    ch_combo.set(channels[0]["name"] if channels else "")
            elif channels:
                ch_combo.current(0)
        if doc.get("supplier_id"):
            target = next((c["name"] for c in filtered_counterparties if c["id"] == doc.get("supplier_id")), "-")
            cp_var.set(target)
        if doc.get("customer_id"):
            target = next((c["name"] for c in filtered_counterparties if c["id"] == doc.get("customer_id")), "-")
            cp_var.set(target)
    else:
        if warehouses:
            wh_combo.current(0)
        if ch_combo and channels:
            ch_combo.current(0)
        if curr_codes:
            curr_combo.current(0)
        cp_var.set("-")

    selected_idx: list[int] = []

    refresh_currency_ui()

    def _get_default_product_setting(key: str, default: str = "") -> str:
        nonlocal settings
        if settings is None:
            return default
        try:
            if isinstance(settings, Settings):
                return (settings.get("defaults", "product", key) or default)
        except Exception:
            pass
        try:
            return (settings.get("defaults", {}).get("product", {}).get(key) or default)
        except Exception:
            return default

    def refresh_lines():
        tree.delete(*tree.get_children())
        for idx, ln in enumerate(line_data):
            tree.insert(
                "",
                "end",
                iid=str(idx),
                values=(
                    ln["product_name"],
                    f"{ln['quantity']:.2f}",
                    f"{ln['price']:.2f}",
                    f"{ln['amount']:.2f}",
                ),
            )

    editor = {"w": None, "row": None, "col": None}

    editable_keys = {"quantity", "price"}
    col_to_key = {"#1": "product", "#2": "quantity", "#3": "price", "#4": "amount"}

    def _close_editor(save: bool):
        w = editor["w"]
        if not w:
            return
        try:
            if save:
                row_iid = editor["row"]
                col_id = editor["col"]
                key = col_to_key.get(col_id)
                if key in editable_keys:
                    idx = int(row_iid)
                    try:
                        val = _parse_float(w.get())
                    except ValueError:
                        messagebox.showerror("Валідація", "Невірне число")
                        return
                    if key == "quantity" and val <= 0:
                        messagebox.showerror("Валідація", "Кількість повинна бути > 0")
                        return
                    if key == "price" and val < 0:
                        messagebox.showerror("Валідація", "Значення не може бути від'ємним")
                        return

                    line_data[idx][key] = val
                    if key in ("quantity", "price"):
                        q = float(line_data[idx]["quantity"])
                        p = float(line_data[idx]["price"])
                        line_data[idx]["amount"] = q * p

                    refresh_lines()
                    tree.selection_set(row_iid)
                    tree.focus(row_iid)
                    tree.see(row_iid)
        finally:
            try:
                w.destroy()
            except Exception:
                pass
            editor["w"] = None
            editor["row"] = None
            editor["col"] = None

    def _begin_edit(row_iid: str, col_id: str):
        key = col_to_key.get(col_id)
        if key not in editable_keys:
            return
        if not editable:
            return
        if editor["w"]:
            _close_editor(save=True)

        bbox = tree.bbox(row_iid, col_id)
        if not bbox:
            return
        x, y, w_, h_ = bbox

        e = ttk.Entry(tree)
        idx = int(row_iid)
        e.insert(0, str(line_data[idx].get(key, "")))
        e.select_range(0, "end")
        e.focus_set()
        e.place(x=x, y=y, width=w_, height=h_)

        editor["w"] = e
        editor["row"] = row_iid
        editor["col"] = col_id

        e.bind("<Return>", lambda ev: (_close_editor(True), "break"))
        e.bind("<KP_Enter>", lambda ev: (_close_editor(True), "break"))
        e.bind("<Escape>", lambda ev: (_close_editor(False), "break"))
        e.bind("<FocusOut>", lambda ev: _close_editor(True))

    def _scan_get_counterparty_id() -> Optional[int]:
        cp_name = cp_var.get()
        if not cp_name or cp_name == "-":
            return None
        match = next((c for c in filtered_counterparties if c["name"] == cp_name), None)
        return match["id"] if match else None

    def _current_warehouse_id() -> int | None:
        name = (wh_var.get() or "").strip()
        w = next((x for x in warehouses if x["name"] == name), None)
        return int(w["id"]) if w else None

    def _scan_resolve_product(code: str) -> Optional[sqlite3.Row]:
        if settings is None:
            prefix = ""
        elif isinstance(settings, Settings):
            prefix = settings.get("defaults", "product", "barcode_prefix") or ""
        else:
            prefix = (settings.get("defaults", {}).get("product", {}).get("barcode_prefix") or "")
        prefix = prefix.strip()
        if doc_type == "purchase":
            counterparty_id = _scan_get_counterparty_id()
            if counterparty_id:
                product = db.get_product_by_supplier_code(counterparty_id, code)
                if product:
                    return product
        product = db.find_product_by_scan_code(code, barcode_prefix=prefix)
        if product:
            return product
        product = db.find_product_by_sku_or_name(None, None, supplier_sku=code)
        if product:
            return product
        supplier_lookup = getattr(db, "get_product_by_supplier_sku", None)
        if callable(supplier_lookup):
            return supplier_lookup(code)
        return None

    def _scan_add_line(product_row: sqlite3.Row, qty_delta: float) -> None:
        for idx, ln in enumerate(line_data):
            if ln["product_id"] == product_row["id"]:
                ln["quantity"] += qty_delta
                ln["amount"] = ln["quantity"] * ln["price"]
                refresh_lines()
                tree.selection_set(str(idx))
                tree.focus(str(idx))
                tree.see(str(idx))
                return
        price0 = 0.0
        if scan_use_avg_cost_var.get():
            wh_id = _current_warehouse_id()
            if wh_id:
                _, avg_cost = db.get_stock_balance(int(product_row["id"]), int(wh_id))
                if doc_type == "sale":
                    try:
                        rate = _parse_float(rate_var.get(), default=1.0)
                    except ValueError:
                        rate = 1.0
                    if rate <= 0:
                        rate = 1.0
                    price0 = avg_cost / rate
                else:
                    price0 = avg_cost
        if price0 <= 0:
            try:
                price0 = _parse_float(price_var.get(), default=0.0)
            except ValueError:
                price0 = 0.0
        product_name = f"{product_row['name']} ({product_row['sku']})"
        line_data.append(
            {
                "product_id": product_row["id"],
                "product_name": product_name,
                "quantity": qty_delta,
                "price": price0,
                "amount": qty_delta * price0,
            }
        )
        refresh_lines()
        idx = len(line_data) - 1
        tree.selection_set(str(idx))
        tree.focus(str(idx))
        tree.see(str(idx))

    def _open_paste_preview() -> None:
        if not editable:
            return

        preview_dlg = tk.Toplevel(dlg)
        preview_dlg.title("Вставка списку — попередній перегляд")
        preview_dlg.grab_set()
        preview_dlg.columnconfigure(0, weight=1)
        preview_dlg.rowconfigure(2, weight=1)

        ttk.Label(preview_dlg, text="Вставити список рядків").grid(
            row=0, column=0, padx=8, pady=(8, 2), sticky="w"
        )
        input_text = tk.Text(preview_dlg, height=9, width=60)
        input_text.grid(row=1, column=0, padx=8, pady=4, sticky="ew")
        try:
            clipboard_text = dlg.clipboard_get()
        except tk.TclError:
            clipboard_text = ""
        if clipboard_text:
            input_text.insert("1.0", clipboard_text)

        options_frame = ttk.Frame(preview_dlg)
        options_frame.grid(row=2, column=0, padx=8, pady=(0, 6), sticky="ew")
        options_frame.columnconfigure(0, weight=1)
        merge_var = tk.BooleanVar(value=True)
        update_price_var = tk.BooleanVar(value=False)
        default_qty_var = tk.BooleanVar(value=True)
        use_avg_cost_var = tk.BooleanVar(value=scan_use_avg_cost_var.get())
        comma_mode_var = tk.BooleanVar(value=False)

        ttk.Checkbutton(
            options_frame,
            text="Об’єднувати дублікати у вставці",
            variable=merge_var,
        ).grid(row=0, column=0, padx=4, pady=2, sticky="w")
        ttk.Checkbutton(
            options_frame,
            text="Оновлювати ціну в існуючих рядках",
            variable=update_price_var,
        ).grid(row=0, column=1, padx=4, pady=2, sticky="w")
        ttk.Checkbutton(
            options_frame,
            text="Якщо qty не вказано → 1",
            variable=default_qty_var,
        ).grid(row=1, column=0, padx=4, pady=2, sticky="w")
        ttk.Checkbutton(
            options_frame,
            text='Для відсутньої ціни брати "Ціна зі середньої собівартості"',
            variable=use_avg_cost_var,
        ).grid(row=1, column=1, padx=4, pady=2, sticky="w")
        ttk.Checkbutton(
            options_frame,
            text="CSV режим (кома як розділювач)",
            variable=comma_mode_var,
        ).grid(row=2, column=0, padx=4, pady=2, sticky="w")

        preview_columns = ["status", "action", "code", "sku", "name", "qty", "price", "note"]
        preview_tree = ttk.Treeview(
            preview_dlg,
            columns=preview_columns,
            show="headings",
            height=8,
        )
        preview_headings = {
            "status": ("Статус", 90),
            "action": ("Дія", 110),
            "code": ("Код", 120),
            "sku": ("SKU", 90),
            "name": ("Назва", 200),
            "qty": ("К-сть", 80),
            "price": ("Ціна", 90),
            "note": ("Примітка", 180),
        }
        for col, (title, width) in preview_headings.items():
            preview_tree.heading(col, text=title)
            preview_tree.column(col, width=width, anchor="w")
        preview_tree.grid(row=3, column=0, padx=8, pady=6, sticky="nsew")
        preview_dlg.rowconfigure(3, weight=1)

        preview_state: list[dict] = []

        def _resolve_missing_price(product_row: sqlite3.Row) -> float:
            price0 = 0.0
            if use_avg_cost_var.get():
                wh_id = _current_warehouse_id()
                if wh_id:
                    _, avg_cost = db.get_stock_balance(int(product_row["id"]), int(wh_id))
                    if doc_type == "sale":
                        try:
                            rate = _parse_float(rate_var.get(), default=1.0)
                        except ValueError:
                            rate = 1.0
                        if rate <= 0:
                            rate = 1.0
                        price0 = avg_cost / rate
                    else:
                        price0 = avg_cost
            if price0 <= 0:
                try:
                    price0 = _parse_float(price_var.get(), default=0.0)
                except ValueError:
                    price0 = 0.0
            return price0

        def _append_note(existing: str, addition: str) -> str:
            if not existing:
                return addition
            if addition in existing:
                return existing
            return f"{existing}; {addition}"

        def _render_preview(rows: list[dict]) -> None:
            preview_tree.delete(*preview_tree.get_children())
            for idx, row in enumerate(rows):
                preview_tree.insert(
                    "",
                    "end",
                    iid=str(idx),
                    values=(
                        row["status"],
                        row.get("action", ""),
                        row["code"],
                        row.get("sku", ""),
                        row.get("name", ""),
                        f"{row['qty']:.2f}" if row.get("qty") is not None else "",
                        f"{row['price']:.2f}" if row.get("price") is not None else "",
                        row.get("note", ""),
                    ),
                )

        def _run_preview() -> None:
            nonlocal preview_state
            preview_state = []
            raw_text = input_text.get("1.0", "end")
            parsed = parse_paste_lines(raw_text, comma_as_delimiter=comma_mode_var.get())
            merged_by_code: dict[str, dict] = {}
            entries: list[dict] = []
            for entry in parsed:
                code = (entry.get("code") or "").strip()
                if not code:
                    continue
                qty = entry.get("qty")
                if qty is None:
                    if default_qty_var.get():
                        qty_val = 1.0
                    else:
                        preview_state.append(
                            {
                                "status": "NOT FOUND",
                                "action": "-",
                                "code": code,
                                "note": "qty invalid",
                            }
                        )
                        continue
                else:
                    qty_val = float(qty)
                if qty_val <= 0:
                    preview_state.append(
                        {
                            "status": "NOT FOUND",
                            "action": "-",
                            "code": code,
                            "note": "qty invalid",
                        }
                    )
                    continue
                if merge_var.get():
                    existing = merged_by_code.get(code)
                    price_val = entry.get("price")
                    if price_val is not None:
                        price_val = float(price_val)
                    if existing:
                        existing["qty"] += qty_val
                        if (
                            existing.get("price") is not None
                            and price_val is not None
                            and abs(existing["price"] - price_val) > 1e-9
                        ):
                            existing["note"] = _append_note(
                                existing.get("note", ""),
                                "ціни різні, взято першу",
                            )
                    else:
                        merged_by_code[code] = {
                            "code": code,
                            "qty": qty_val,
                            "price": price_val,
                            "note": "",
                        }
                else:
                    entries.append(
                        {
                            "code": code,
                            "qty": qty_val,
                            "price": float(entry["price"]) if entry.get("price") is not None else None,
                            "note": "",
                        }
                    )
            if merge_var.get():
                entries.extend(merged_by_code.values())
            cache: dict[str, sqlite3.Row | None] = {}
            for entry in entries:
                code = entry["code"]
                if code not in cache:
                    cache[code] = _scan_resolve_product(code)
            for entry in entries:
                code = entry["code"]
                product = cache.get(code)
                if not product:
                    preview_state.append(
                        {
                            "status": "NOT FOUND",
                            "action": "-",
                            "code": code,
                            "note": "не знайдено код",
                        }
                    )
                    continue
                price_val = entry.get("price")
                if price_val is None:
                    price_val = _resolve_missing_price(product)
                else:
                    price_val = float(price_val)
                existing = next((ln for ln in line_data if ln["product_id"] == product["id"]), None)
                if existing:
                    action = "UPDATE+PRICE" if update_price_var.get() else "UPDATE"
                else:
                    action = "ADD"
                preview_state.append(
                    {
                        "status": "OK",
                        "action": action,
                        "code": code,
                        "sku": product["sku"],
                        "name": product["name"],
                        "qty": float(entry["qty"]),
                        "price": price_val,
                        "product_id": int(product["id"]),
                        "product_row": product,
                        "note": entry.get("note", ""),
                    }
                )
            ok_count = sum(1 for row in preview_state if row.get("status") == "OK")
            add_btn.config(state="normal" if ok_count > 0 else "disabled")
            not_found_count = sum(1 for row in preview_state if row.get("status") == "NOT FOUND")
            copy_nf_btn.config(state="normal" if not_found_count > 0 else "disabled")
            _render_preview(preview_state)

        def _confirm_add() -> None:
            ok_rows = [row for row in preview_state if row.get("status") == "OK"]
            if not ok_rows:
                return
            added_count = 0
            updated_count = 0
            for row in ok_rows:
                product = row["product_row"]
                qty_val = float(row["qty"])
                price_val = float(row["price"] or 0.0)
                existing = next((ln for ln in line_data if ln["product_id"] == product["id"]), None)
                if existing:
                    existing["quantity"] += qty_val
                    if update_price_var.get():
                        existing["price"] = price_val
                existing["amount"] = existing["quantity"] * existing["price"]
                    updated_count += 1
                else:
                    product_name = f"{product['name']} ({product['sku']})"
                    line_data.append(
                        {
                            "product_id": product["id"],
                            "product_name": product_name,
                            "quantity": qty_val,
                            "price": price_val,
                            "amount": qty_val * price_val,
                        }
                    )
                    added_count += 1
            refresh_lines()
            not_found = [row["code"] for row in preview_state if row.get("status") != "OK"]
            preview_list = ", ".join(not_found[:20])
            summary = (
                f"Added new: {added_count}\n"
                f"Updated: {updated_count}\n"
                f"Not found: {len(not_found)}"
            )
            if preview_list:
                summary += f"\nКоди: {preview_list}"
            messagebox.showinfo("Вставка списку", summary)
            preview_dlg.destroy()

        btns_frame = ttk.Frame(preview_dlg)
        btns_frame.grid(row=4, column=0, padx=8, pady=(0, 8), sticky="e")
        def _copy_not_found() -> None:
            codes = [row["code"] for row in preview_state if row.get("status") == "NOT FOUND"]
            if not codes:
                return
            preview_dlg.clipboard_clear()
            preview_dlg.clipboard_append("\n".join(codes))

        ttk.Button(btns_frame, text="Preview", command=_run_preview).pack(side=tk.LEFT, padx=4)
        copy_nf_btn = ttk.Button(
            btns_frame,
            text="Скопіювати NOT FOUND",
            command=_copy_not_found,
            state="disabled",
        )
        copy_nf_btn.pack(side=tk.LEFT, padx=4)
        add_btn = ttk.Button(btns_frame, text="Додати", command=_confirm_add, state="disabled")
        add_btn.pack(side=tk.LEFT, padx=4)
        ttk.Button(btns_frame, text="Закрити", command=preview_dlg.destroy).pack(side=tk.LEFT, padx=4)

    paste_btn.config(command=_open_paste_preview)

    def _on_scan_commit(event=None):
        if not editable:
            return "break"
        code = scan_var.get().strip()
        if not code:
            return "break"
        try:
            qty = 1 if scan_plus_one_var.get() else int(scan_qty_var.get() or 1)
        except (TypeError, ValueError):
            qty = 1
        product = _scan_resolve_product(code)
        if not product:
            scan_status.config(text=f"Не знайдено: {code}", foreground="#b91c1c")
            dlg.bell()
            scan_entry.focus_set()
            scan_var.set("")
            return "break"
        _scan_add_line(product, qty)
        scan_var.set("")
        scan_status.config(text=f"OK: {product['sku']} — {product['name']} (+{qty})", foreground="#15803d")
        scan_entry.focus_set()
        return "break"

    scan_entry.bind("<Return>", _on_scan_commit)
    scan_entry.bind("<KP_Enter>", _on_scan_commit)

    def on_select(event=None):
        selected_idx.clear()
        sel = tree.selection()
        if sel:
            idx = int(sel[0])
            selected_idx.append(idx)

    tree.bind("<<TreeviewSelect>>", on_select)

    last_col_id: str | None = None

    def _remember_col(ev):
        nonlocal last_col_id
        col = tree.identify_column(ev.x)
        if col:
            last_col_id = col

    def _on_tree_dbl(ev):
        row = tree.identify_row(ev.y)
        col = tree.identify_column(ev.x)
        if row:
            tree.selection_set(row)
            _begin_edit(row, col)

    def _on_tree_f2(ev):
        sel = tree.selection()
        if not sel:
            return
        row = sel[0]
        col = last_col_id or tree.identify_column(ev.x)
        if not col:
            return
        _begin_edit(row, col)

    def _on_tree_click_empty(ev):
        row = tree.identify_row(ev.y)
        if not row:
            tree.selection_remove(tree.selection())
            selected_idx.clear()

    def _on_tree_escape(ev):
        tree.selection_remove(tree.selection())
        selected_idx.clear()
        return "break"

    tree.bind("<Double-1>", _on_tree_dbl, add="+")
    tree.bind("<F2>", _on_tree_f2, add="+")
    tree.bind("<Motion>", _remember_col, add="+")
    tree.bind("<Button-1>", _remember_col, add="+")
    tree.bind("<Button-1>", _on_tree_click_empty, add="+")
    tree.bind("<Escape>", _on_tree_escape, add="+")

    def _parse_float(s: str, default: float | None = None) -> float:
        t = (s or "").strip().replace(" ", "").replace(",", ".")
        if t == "":
            if default is None:
                raise ValueError("empty")
            return float(default)
        return float(t)

    def add_line():
        if not editable:
            return
        try:
            qty = _parse_float(qty_var.get())
            price = _parse_float(price_var.get())
        except ValueError:
            messagebox.showerror("Валідація", "Невірні числові значення")
            return
        if qty <= 0:
            messagebox.showerror("Валідація", "Кількість повинна бути більшою за 0")
            return
        product_name = product_var.get().strip()
        product_id = product_lookup.get(product_name)
        if not product_id:
            if not editable:
                return
            if not product_name:
                messagebox.showerror("Валідація", "Введіть назву товару")
                return
            created = add_new_product(product_name)
            if not created:
                return
            product_id, product_name = created
        data = {
            "product_id": product_id,
            "product_name": product_name,
            "quantity": qty,
            "price": price,
            "amount": qty * price,
        }
        line_data.append(data)
        refresh_lines()
        tree.selection_remove(tree.selection())
        selected_idx.clear()

    def delete_line():
        if not editable:
            return
        if not selected_idx:
            return
        line_data.pop(selected_idx[0])
        selected_idx.clear()
        refresh_lines()

    if editable:
        qty_entry.bind("<Return>", lambda ev: (add_line(), "break"))
        price_entry.bind("<Return>", lambda ev: (add_line(), "break"))

    def add_new_product(default_name: str = ""):
        if not editable:
            return None
        brands = db.list_brands()
        categories = [
            {
                **c,
                "label": c.get("label") or ("    " * c.get("depth", 0) + c.get("name", "")),
            }
            for c in db.list_categories_tree(include_hidden=False)
        ]
        if not brands or not categories:
            messagebox.showerror(
                "Товари",
                "Додайте принаймні один бренд і категорію у вкладці \"Товари\", щоб створювати нові позиції.",
            )
            return None

        dlg_product = tk.Toplevel(dlg)
        dlg_product.title("Новий товар")
        dlg_product.grab_set()

        ttk.Label(dlg_product, text="Артикул (SKU)").grid(row=0, column=0, padx=6, pady=4, sticky="e")
        sku_var = tk.StringVar(value=default_name)
        sku_frame = ttk.Frame(dlg_product)
        sku_frame.grid(row=0, column=1, padx=6, pady=4, sticky="w")
        sku_frame.columnconfigure(0, weight=1)
        ttk.Entry(sku_frame, textvariable=sku_var, width=30).grid(row=0, column=0, padx=(0, 4), sticky="ew")
        sku_generate_btn = ttk.Button(sku_frame, text="Згенерувати")
        sku_generate_btn.grid(row=0, column=1, padx=0)

        ttk.Label(dlg_product, text="Назва").grid(row=1, column=0, padx=6, pady=4, sticky="e")
        name_var = tk.StringVar(value=default_name)
        ttk.Entry(dlg_product, textvariable=name_var, width=30).grid(row=1, column=1, padx=6, pady=4, sticky="w")

        ttk.Label(dlg_product, text="Бренд").grid(row=2, column=0, padx=6, pady=4, sticky="e")
        brand_var = tk.StringVar()
        brand_combo = ttk.Combobox(
            dlg_product,
            textvariable=brand_var,
            values=[b["name"] for b in brands],
            state="readonly",
            width=28,
        )
        brand_combo.grid(row=2, column=1, padx=6, pady=4, sticky="w")

        brand_default = _get_default_product_setting("brand", "")
        preferred_brand = _find_index_by_name([b["name"] for b in brands], brand_default)
        if preferred_brand is not None:
            brand_combo.current(preferred_brand)
        else:
            brand_combo.current(0)

        ttk.Label(dlg_product, text="Категорія").grid(row=3, column=0, padx=6, pady=4, sticky="e")
        category_var = tk.StringVar()
        category_combo = ttk.Combobox(
            dlg_product,
            textvariable=category_var,
            values=[c["label"] for c in categories],
            state="readonly",
            width=28,
        )
        category_combo.grid(row=3, column=1, padx=6, pady=4, sticky="w")

        generator_enabled = bool(settings.get("defaults", "product", "sku_generator", "enabled") if settings else False)

        def _selected_brand():
            try:
                idx = brand_combo.current()
                if idx is None or idx < 0:
                    return None
                return brands[idx]
            except Exception:
                return None

        def _selected_category():
            label = category_var.get()
            return next((c for c in categories if c.get("label") == label), None)

        def _generate_sku() -> None:
            if not generator_enabled or settings is None:
                return
            brand_row = _selected_brand()
            category_row = _selected_category()
            try:
                sku_value = sku_gen.generate_next_sku(settings, brand_row, category_row, name_var.get())
            except Exception as exc:
                messagebox.showerror("SKU", f"Не вдалося згенерувати SKU: {exc}")
                return
            sku_var.set(sku_value)

        sku_generate_btn.configure(command=_generate_sku, state="normal" if generator_enabled else "disabled")
        default_category = _get_default_product_setting("category", "")
        preferred_category = _find_index_by_name([c["label"] for c in categories], default_category)
        if preferred_category is None:
            preferred_category = _find_index_by_name([c.get("name", "") for c in categories], default_category)
        if preferred_category is not None:
            category_combo.current(preferred_category)
        else:
            category_combo.current(0)

        default_unit = _get_default_product_setting("unit", "pcs")
        ttk.Label(dlg_product, text="Одиниця").grid(row=4, column=0, padx=6, pady=4, sticky="e")
        unit_var = tk.StringVar(value=default_unit)
        ttk.Entry(dlg_product, textvariable=unit_var, width=30).grid(row=4, column=1, padx=6, pady=4, sticky="w")

        result_new: tuple[int, str] | None = None

        def on_save():
            nonlocal result_new
            sku = sku_var.get().strip()
            name = name_var.get().strip()
            unit = unit_var.get().strip() or "pcs"
            if not sku and generator_enabled and settings:
                _generate_sku()
                sku = sku_var.get().strip()
            if not sku or not name:
                messagebox.showerror("Товари", "Введіть артикул і назву товару")
                return
            brand_idx = brand_combo.current()
            cat_idx = category_combo.current()
            try:
                brand_id = brands[brand_idx]["id"]
                category_id = categories[cat_idx]["id"]
            except Exception:
                messagebox.showerror("Товари", "Оберіть бренд та категорію")
                return
            try:
                new_id = db.add_product(sku, name, brand_id, category_id, unit, True)
            except Exception as exc:
                messagebox.showerror("Товари", f"Не вдалося створити товар: {exc}")
                return
            product_full_name = f"{name} ({sku})"
            product_lookup[product_full_name] = new_id
            products_by_id[new_id] = product_full_name
            product_names.append(product_full_name)
            product_names.sort(key=str.lower)
            product_combo["values"] = product_names
            product_var.set(product_full_name)
            result_new = (new_id, product_full_name)
            dlg_product.destroy()

        def on_cancel():
            dlg_product.destroy()

        btns_new = ttk.Frame(dlg_product)
        btns_new.grid(row=5, column=0, columnspan=2, pady=8)
        ttk.Button(btns_new, text="Зберегти", command=on_save).pack(side=tk.LEFT, padx=4)
        ttk.Button(btns_new, text="Скасувати", command=on_cancel).pack(side=tk.LEFT, padx=4)
        dlg_product.bind("<Return>", lambda e: on_save())
        dlg_product.bind("<Escape>", lambda e: on_cancel())
        dlg_product.wait_window()
        return result_new

    btn_line = ttk.Frame(entry_frame)
    btn_line.grid(row=0, column=6, padx=6)
    ttk.Button(btn_line, text="Новий товар", command=lambda: add_new_product(product_var.get()), state="normal" if editable else "disabled").pack(side=tk.LEFT, padx=4)
    ttk.Button(btn_line, text="Додати", command=add_line, style="Success.TButton", state="normal" if editable else "disabled").pack(side=tk.LEFT)
    ttk.Button(btn_line, text="Видалити", command=delete_line, style="Danger.TButton", state="normal" if editable else "disabled").pack(side=tk.LEFT, padx=4)

    refresh_lines()

    row_idx += 1

    result = None

    def on_ok():
        nonlocal result
        try:
            doc_date = dates.normalize_date_to_iso(date_picker.get(), field_label="Дата")
        except ValueError as exc:
            messagebox.showerror("Валідація", str(exc))
            return
        if editable and not line_data:
            messagebox.showerror("Валідація", "Додайте хоча б один рядок")
            return
        try:
            rate = _parse_float(rate_var.get())
        except ValueError:
            messagebox.showerror("Валідація", "Невірний курс")
            return
        if rate <= 0:
            messagebox.showerror("Валідація", "Курс має бути більшим за 0")
            return
        currency_code = curr_var.get().strip().upper()
        order_expense = 0.0
        if doc_type == "sale":
            try:
                order_expense = _parse_float(order_expense_var.get(), default=0.0)
            except ValueError:
                messagebox.showerror("Валідація", "Невірна сума витрат замовлення")
                return
            if order_expense < 0:
                messagebox.showerror("Валідація", "Витрати замовлення не можуть бути від'ємними")
                return
        cp_name = cp_var.get()
        cp_id = None
        if cp_name and cp_name != "-":
            cp_id = next((c["id"] for c in filtered_counterparties if c["name"] == cp_name), None)
        if currency_code != get_base_currency_code() and not db.rate_on_date(currency_code, doc_date):
            db.add_currency_rate(currency_code, doc_date, rate)
        try:
            warehouse_id = warehouses[wh_combo.current()]["id"]
        except Exception:
            messagebox.showerror("Валідація", "Оберіть склад")
            return
        channel_name = ""
        if doc_type == "sale":
            channel_name = ch_var.get() if ch_var.get() else (channels[0]["name"] if channels else "")
        info = {
            "doc_type": doc_type,
            "doc_date": doc_date,
            "counterparty_id": cp_id,
            "warehouse_id": warehouse_id,
            "channel": channel_name,
            "comment": comment_var.get().strip(),
            "currency": curr_var.get(),
            "rate": rate,
            "order_expense_doc": order_expense if doc_type == "sale" else 0.0,
        }
        lines_to_save = [(ln["product_id"], ln["quantity"], ln["price"]) for ln in line_data]
        result = (info, lines_to_save)
        dlg.destroy()

    def on_cancel():
        dlg.destroy()

    def _focus_scan(event=None):
        if editable:
            scan_entry.focus_set()
            scan_entry.selection_range(0, tk.END)
        return "break"

    def _toggle_plus_one(event=None):
        if editable:
            scan_plus_one_var.set(not scan_plus_one_var.get())
            _apply_scan_mode()
            scan_entry.focus_set()
        return "break"

    btns = ttk.Frame(content)
    btns.grid(row=row_idx, column=0, columnspan=2, pady=8, sticky="e")
    ttk.Button(btns, text="OK", command=on_ok).pack(side=tk.LEFT, padx=4)
    ttk.Button(btns, text="Скасувати", command=on_cancel).pack(side=tk.LEFT, padx=4)
    dlg.bind("<Return>", lambda e: on_ok())
    dlg.bind("<Control-Return>", lambda e: on_ok())
    dlg.bind("<Control-KP_Enter>", lambda e: on_ok())
    dlg.bind("<F8>", _focus_scan)
    dlg.bind("<F9>", _toggle_plus_one)
    dlg.bind("<Escape>", lambda e: on_cancel())
    if editable:
        dlg.after_idle(
            lambda: (
                scan_entry.focus_set(),
                scan_entry.selection_range(0, tk.END),
                scan_entry.icursor(tk.END),
            )
        )
    dlg.wait_window()
    return result


def cash_prompt(counterparties, channels, *, defaults: dict | None = None):
    defaults = defaults or {}
    dlg = tk.Toplevel()
    dlg.title("Рух коштів")
    dlg.grab_set()

    ttk.Label(dlg, text="Дата (ДД.ММ.РРРР)").grid(row=0, column=0, padx=6, pady=4, sticky="w")
    date_picker = DatePicker(dlg, initial=defaults.get("date") or datetime.now().strftime("%Y-%m-%d"))
    date_picker.grid(row=0, column=1, padx=6, pady=4, sticky="w")

    ttk.Label(dlg, text="Тип").grid(row=1, column=0, padx=6, pady=4, sticky="w")
    type_var = tk.StringVar()
    types = [
        ("Оплата від клієнта", "sale_payment"),
        ("Оплата постачальнику", "purchase_payment"),
        ("Інший дохід", "other_income"),
        ("Змінна витрата", "other_variable_expense"),
        ("Постійна витрата", "fixed_expense"),
    ]
    type_combo = ttk.Combobox(dlg, textvariable=type_var, values=[t[0] for t in types], state="readonly")
    type_combo.grid(row=1, column=1, padx=6, pady=4, sticky="w")
    default_type = defaults.get("type")
    default_type_idx = next((i for i, t in enumerate(types) if t[1] == default_type), 0)
    type_combo.current(default_type_idx)

    ttk.Label(dlg, text="Валюта").grid(row=2, column=0, padx=6, pady=4, sticky="w")
    currencies = db.list_currencies(active_only=True)
    currency_codes = [c["code"] for c in currencies] or [get_base_currency_code()]
    currency_var = tk.StringVar(value=defaults.get("currency_code") or currency_codes[0])
    currency_combo = ttk.Combobox(dlg, textvariable=currency_var, values=currency_codes, state="readonly", width=8)
    currency_combo.grid(row=2, column=1, padx=6, pady=4, sticky="w")

    ttk.Label(dlg, text="Курс").grid(row=3, column=0, padx=6, pady=4, sticky="w")
    rate_var = tk.StringVar(value=str(defaults.get("exchange_rate", 1.0)))
    ttk.Entry(dlg, textvariable=rate_var, width=12).grid(row=3, column=1, padx=6, pady=4, sticky="w")

    ttk.Label(dlg, text="Сума (валюта)").grid(row=4, column=0, padx=6, pady=4, sticky="w")
    amount_doc_var = tk.StringVar(value=str(defaults.get("amount_doc", 0)))
    ttk.Entry(dlg, textvariable=amount_doc_var, width=15).grid(row=4, column=1, padx=6, pady=4, sticky="w")

    ttk.Label(dlg, text="Сума (база)").grid(row=5, column=0, padx=6, pady=4, sticky="w")
    amount_base_var = tk.StringVar(value=str(defaults.get("amount_base", 0)))
    ttk.Entry(dlg, textvariable=amount_base_var, width=15, state="readonly").grid(
        row=5, column=1, padx=6, pady=4, sticky="w"
    )

    ttk.Label(dlg, text="Контрагент").grid(row=6, column=0, padx=6, pady=4, sticky="w")
    cp_var = tk.StringVar()
    cp_names = ["-"] + [c["name"] for c in counterparties]
    cp_combo = ttk.Combobox(dlg, textvariable=cp_var, values=cp_names, state="readonly", width=30)
    cp_combo.grid(row=6, column=1, padx=6, pady=4, sticky="w")
    default_cp = defaults.get("counterparty_id")
    if default_cp:
        idx = next((i + 1 for i, cp in enumerate(counterparties) if cp["id"] == default_cp), 0)
        cp_combo.current(idx)
    else:
        cp_combo.current(0)

    ttk.Label(dlg, text="Канал").grid(row=7, column=0, padx=6, pady=4, sticky="w")
    ch_var = tk.StringVar()
    ch_names = [c["name"] for c in channels]
    ch_combo = ttk.Combobox(dlg, textvariable=ch_var, values=ch_names, state="readonly", width=20)
    ch_combo.grid(row=7, column=1, padx=6, pady=4, sticky="w")
    if defaults.get("channel"):
        ch_var.set(defaults.get("channel"))
    elif channels:
        ch_combo.current(0)

    ttk.Label(dlg, text="Коментар").grid(row=8, column=0, padx=6, pady=4, sticky="w")
    comment_var = tk.StringVar(value=defaults.get("comment", ""))
    ttk.Entry(dlg, textvariable=comment_var, width=40).grid(row=8, column=1, padx=6, pady=4, sticky="w")

    result: list[dict] | None = None

    def recalc_base(*_args) -> None:
        try:
            rate = float(rate_var.get())
            amount_doc = float(amount_doc_var.get())
        except ValueError:
            amount_base_var.set("")
            return
        current_type = next((t[1] for t in types if t[0] == type_var.get()), types[0][1])
        sign = -1 if current_type in ("purchase_payment", "other_variable_expense", "fixed_expense") else 1
        amount_base_var.set(f"{amount_doc * rate * sign:.2f}")

    def on_ok():
        nonlocal result
        try:
            normalized_date = dates.normalize_date_to_iso(date_picker.get(), field_label="Дата")
            rate = float(rate_var.get())
            amount_doc = float(amount_doc_var.get())
        except ValueError:
            messagebox.showerror("Валідація", "Невірні значення дати або суми")
            return
        ctype = next((t[1] for t in types if t[0] == type_var.get()), types[0][1])
        cp_name = cp_var.get()
        cp_id = None
        if cp_name and cp_name != "-":
            cp_id = next((c["id"] for c in counterparties if c["name"] == cp_name), None)
        channel = ch_var.get() if ch_var.get() else ""
        sign = -1 if ctype in ("purchase_payment", "other_variable_expense", "fixed_expense") else 1
        amount_base = amount_doc * rate * sign
        result = [
            {
                "date": normalized_date,
                "amount": amount_base,
                "amount_doc": amount_doc * sign,
                "exchange_rate": rate,
                "currency_code": currency_var.get().strip().upper() or get_base_currency_code(),
                "ctype": ctype,
                "counterparty_id": cp_id,
                "related_doc_type": defaults.get("related_doc_type"),
                "related_doc_id": defaults.get("related_doc_id"),
                "channel": channel,
                "comment": comment_var.get().strip(),
            }
        ]
        dlg.destroy()

    def on_cancel():
        dlg.destroy()

    btns = ttk.Frame(dlg)
    btns.grid(row=9, column=0, columnspan=2, pady=8)
    ttk.Button(btns, text="OK", command=on_ok).pack(side=tk.LEFT, padx=4)
    ttk.Button(btns, text="Скасувати", command=on_cancel).pack(side=tk.LEFT, padx=4)
    dlg.bind("<Return>", lambda e: on_ok())
    dlg.bind("<Escape>", lambda e: on_cancel())
    rate_var.trace_add("write", recalc_base)
    amount_doc_var.trace_add("write", recalc_base)
    type_var.trace_add("write", recalc_base)
    recalc_base()
    dlg.wait_window()
    return result
