from __future__ import annotations

import logging
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional
import tkinter as tk
from tkinter import ttk, messagebox, filedialog

from inventorylite import db, dates
from inventorylite.helpers import (
    SALES_FIELDS,
    _normalize_sales_records,
    _suggest_sales_mapping,
    parse_sales_file,
)
from inventorylite.dialogs_documents import document_prompt
from inventorylite.ui_components import TableFrame, simple_prompt
from inventorylite.utils import Settings, show_error


class SalesTab:
    def __init__(
        self,
        parent: ttk.Notebook,
        settings: Settings,
        default_workdir_provider: Callable[[], Path],
        generate_unique_sku: Callable[[str, set[str]], str],
        on_refresh_stock: Callable[[], None],
        on_refresh_cash: Callable[[], None],
    ) -> None:
        self.frame = ttk.Frame(parent)
        self.settings = settings
        self.default_workdir_provider = default_workdir_provider
        self.generate_unique_sku = generate_unique_sku
        self.on_refresh_stock = on_refresh_stock
        self.on_refresh_cash = on_refresh_cash

        self.sales_status_var = tk.StringVar(value="Усі")
        self.sales_date_from_var = tk.StringVar()
        self.sales_date_to_var = tk.StringVar()
        self.sales_table: TableFrame | None = None

        self._build()

    def _build(self) -> None:
        filters = ttk.Frame(self.frame)
        filters.pack(fill=tk.X, padx=8, pady=4)
        ttk.Label(filters, text="Статус:").pack(side=tk.LEFT)
        status_combo = ttk.Combobox(
            filters,
            textvariable=self.sales_status_var,
            values=["Усі", "Чернетка", "Проведений"],
            state="readonly",
            width=14,
        )
        status_combo.pack(side=tk.LEFT, padx=4)
        ttk.Label(filters, text="Дата з:").pack(side=tk.LEFT)
        ttk.Entry(filters, textvariable=self.sales_date_from_var, width=10).pack(side=tk.LEFT, padx=2)
        ttk.Label(filters, text="по:").pack(side=tk.LEFT)
        ttk.Entry(filters, textvariable=self.sales_date_to_var, width=10).pack(side=tk.LEFT, padx=2)
        ttk.Button(filters, text="Фільтр", command=self.refresh_sales).pack(side=tk.LEFT, padx=6)

        columns = [
            ("doc_date", "Дата", 90),
            ("customer", "Клієнт", 200),
            ("warehouse", "Склад", 160),
            ("channel", "Канал", 130),
            ("status", "Статус", 90),
            ("currency", "Валюта", 80),
            ("rate", "Курс", 80),
            ("total_doc", "Сума (вал)", 110),
            ("total", "Сума (база)", 110),
            ("comment", "Коментар", 240),
        ]
        self.sales_table = TableFrame(
            self.frame,
            columns,
            settings=self.settings,
            persist_key="sales_table",
        )
        self.sales_table.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)
        self.sales_table.on_double_click(self.edit_sale)
        self.sales_table.register_context_menu_actions(
            [
                ("Редагувати", self.edit_sale),
                ("Видалити", self.delete_sale),
            ]
        )

        btns = ttk.Frame(self.frame)
        btns.pack(pady=4)
        ttk.Button(btns, text="Нова продажа", command=self.new_sale).pack(side=tk.LEFT, padx=4)
        ttk.Button(btns, text="Змінити", command=self.edit_sale).pack(side=tk.LEFT, padx=4)
        ttk.Button(btns, text="Видалити", command=self.delete_sale).pack(side=tk.LEFT, padx=4)
        ttk.Button(btns, text="Провести", command=self.post_sale_action).pack(side=tk.LEFT, padx=4)
        ttk.Button(btns, text="Відмінити проведення", command=self.unpost_sale_action).pack(side=tk.LEFT, padx=4)
        ttk.Button(btns, text="Комплектація", command=self.show_assembly_plan).pack(side=tk.LEFT, padx=4)
        ttk.Button(btns, text="Імпорт із файлу", command=self.import_sales_from_file).pack(side=tk.LEFT, padx=4)

    def _selected_sale(self):
        if not self.sales_table:
            return None
        doc_id = self.sales_table.selected_id()
        if not doc_id:
            show_error("Продажі", "Оберіть документ")
            return None
        return doc_id

    def refresh_sales(self) -> None:
        if not self.sales_table:
            return
        status_filter = self.sales_status_var.get()
        status_value = "draft" if status_filter == "Чернетка" else "posted" if status_filter == "Проведений" else None
        try:
            rows = db.list_sales(
                status_value,
                self.sales_date_from_var.get().strip() or None,
                self.sales_date_to_var.get().strip() or None,
            )
        except ValueError as exc:
            show_error("Продажі", str(exc))
            return
        self.sales_table.set_rows(
            [
                {
                    "id": r["id"],
                    "doc_date": dates.format_iso_to_dmy(r["doc_date"]),
                    "customer": r["customer"] or "-",
                    "warehouse": r["warehouse"] or "-",
                    "channel": r["channel"] or "-",
                    "status": "Чернетка" if r["status"] == "draft" else "Проведений",
                    "currency": r["currency_code"],
                    "rate": f"{r['exchange_rate']:.4f}",
                    "total_doc": f"{r['total_doc']:.2f}",
                    "total": f"{r['total']:.2f}",
                    "comment": r["comment"] or "",
                }
                for r in rows
            ]
        )

    def new_sale(self) -> None:
        products = db.list_products()
        warehouses = db.list_warehouses(active_only=True)
        channels = db.list_channels(active_only=True)
        counterparties = db.list_counterparties()
        currencies = db.list_currencies()
        result = document_prompt("sale", products, counterparties, warehouses, channels, currencies, settings=self.settings)
        if not result:
            return
        info, lines = result
        try:
            doc_id = db.create_sale(
                info["doc_date"],
                info["counterparty_id"],
                info["warehouse_id"],
                info["channel"],
                info["comment"],
                info["currency"],
                info["rate"],
                info.get("order_expense_doc", 0.0),
            )
            db.replace_sale_lines(doc_id, lines, info["rate"], info.get("order_expense_doc", 0.0))
            self.refresh_sales()
        except Exception:
            logging.exception("Create sale error")
            show_error("Продажі", "Не вдалося створити документ")

    def edit_sale(self) -> None:
        doc_id = self._selected_sale()
        if not doc_id:
            return
        doc = db.get_sale(doc_id)
        if not doc:
            return
        lines = db.list_sale_lines(doc_id)
        products = db.list_products()
        warehouses = db.list_warehouses(active_only=False)
        channels = db.list_channels(active_only=False)
        counterparties = db.list_counterparties()
        currencies = db.list_currencies()
        result = document_prompt(
            "sale",
            products,
            counterparties,
            warehouses,
            channels,
            currencies,
            doc=doc,
            lines=lines,
            settings=self.settings,
        )
        if not result:
            return
        info, new_lines = result
        try:
            if doc["status"] == "draft":
                db.update_sale(
                    doc_id,
                    info["doc_date"],
                    info["counterparty_id"],
                    info["warehouse_id"],
                    info["channel"],
                    info["comment"],
                    info["currency"],
                    info["rate"],
                    info.get("order_expense_doc", 0.0),
                )
                db.replace_sale_lines(doc_id, new_lines, info["rate"], info.get("order_expense_doc", 0.0))
            else:
                db.update_sale(
                    doc_id,
                    doc["doc_date"],
                    doc["customer_id"],
                    doc["warehouse_id"],
                    doc["channel"] or "",
                    info["comment"],
                    doc["currency_code"],
                    doc["exchange_rate"],
                    doc.get("order_expense_doc", 0.0),
                )
            self.refresh_sales()
        except Exception:
            logging.exception("Edit sale error")
            show_error("Продажі", "Не вдалося змінити документ")

    def delete_sale(self) -> None:
        doc_id = self._selected_sale()
        if not doc_id:
            return
        if not messagebox.askyesno("Підтвердження", "Видалити документ?"):
            return
        try:
            with db.get_connection() as conn:
                status_row = conn.execute("SELECT status FROM SalesDocuments WHERE id=?", (doc_id,)).fetchone()
            if not status_row:
                raise ValueError("Документ не знайдено")

            was_posted = status_row[0] == "posted"
            if was_posted:
                if not messagebox.askyesno(
                    "Підтвердження", "Документ проведено. Скасувати проведення та видалити?"
                ):
                    return
                db.unpost_sale(doc_id)

            with db.get_connection() as conn:
                with db.safe_transaction(conn):
                    conn.execute("DELETE FROM SalesDocuments WHERE id=?", (doc_id,))

            self.refresh_sales()
            if was_posted:
                self.on_refresh_stock()
                self.on_refresh_cash()
        except Exception as exc:
            logging.exception("Delete sale error")
            show_error("Продажі", str(exc))

    def post_sale_action(self) -> None:
        doc_id = self._selected_sale()
        if not doc_id:
            return
        try:
            db.post_sale(doc_id)
            self.refresh_sales()
            self.on_refresh_stock()
            self.on_refresh_cash()
        except Exception as exc:
            logging.exception("Post sale error")
            show_error("Продажі", str(exc))

    def unpost_sale_action(self) -> None:
        doc_id = self._selected_sale()
        if not doc_id:
            return
        try:
            db.unpost_sale(doc_id)
            self.refresh_sales()
            self.on_refresh_stock()
            self.on_refresh_cash()
        except Exception as exc:
            logging.exception("Unpost sale error")
            show_error("Продажі", str(exc))

    def show_assembly_plan(self) -> None:
        doc_id = self._selected_sale()
        if not doc_id:
            return
        try:
            doc = db.get_sale(doc_id)
            if not doc:
                raise ValueError("Документ не знайдено")
            lines = db.list_sale_lines(doc_id)
            plans = db.list_sale_assembly_plans(doc_id)
            products = {p["id"]: p for p in db.list_products()}
        except Exception as exc:
            logging.exception("Load assembly plan error")
            show_error("Продажі", str(exc))
            return

        plans_by_line = {plan["sale_line_id"]: plan for plan in plans}
        dlg = tk.Toplevel(self.frame)
        dlg.title("Комплектація продажу")
        dlg.transient(self.frame.winfo_toplevel())
        dlg.resizable(True, True)

        tree = ttk.Treeview(dlg, columns=("qty", "amount"), show="tree headings")
        tree.heading("#0", text="Рядок")
        tree.heading("qty", text="К-сть")
        tree.heading("amount", text="Сума собівар.")
        tree.column("qty", width=100, anchor="center")
        tree.column("amount", width=140, anchor="center")

        vsb = ttk.Scrollbar(dlg, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=vsb.set)
        tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        dlg.grid_columnconfigure(0, weight=1)
        dlg.grid_rowconfigure(0, weight=1)

        draft_hint_shown = False
        for line in lines:
            line_text = f"{line['sku']} — {line['product_name']} (x{line['quantity']})"
            parent_item = tree.insert("", "end", text=line_text, values=("", ""))
            plan = plans_by_line.get(line["id"])
            if plan and plan.get("lines"):
                for comp in plan["lines"]:
                    comp_product = products.get(comp["component_product_id"]) or {}
                    comp_label = f"{comp_product.get('sku', comp['component_product_id'])} — {comp_product.get('name', '')}"
                    qty_val = float(comp.get("qty") or 0.0)
                    amount_val = float(comp.get("amount") or 0.0)
                    tree.insert(
                        parent_item,
                        "end",
                        text=f"• {comp_label}",
                        values=(f"{qty_val:.4g}", f"{amount_val:.2f}"),
                    )
            else:
                hint = "План створюється при проведенні продажу" if doc["status"] == "draft" else "План відсутній"
                tree.insert(parent_item, "end", text=hint, values=("", ""))
                if doc["status"] == "draft":
                    draft_hint_shown = True

        if draft_hint_shown:
            ttk.Label(dlg, text="План буде згенерований під час проведення продажу.").grid(
                row=1, column=0, columnspan=2, sticky="w", padx=8, pady=6
            )
        ttk.Button(dlg, text="Закрити", command=dlg.destroy).grid(row=2, column=0, columnspan=2, pady=6)
        dlg.grab_set()

    def import_sales_from_file(self) -> None:
        file_path = filedialog.askopenfilename(
            title="Файл замовлень",
            filetypes=[("CSV", "*.csv"), ("Excel", "*.xlsx *.xls"), ("Усі файли", "*.*")],
            initialdir=str(self.default_workdir_provider()),
        )
        if not file_path:
            return

        try:
            raw_rows, headers = parse_sales_file(
                Path(file_path),
                encoding=self.settings.get("files", "encoding") or "utf-8",
            )
        except Exception as exc:
            logging.exception("Не вдалося прочитати файл імпорту")
            show_error(
                "Імпорт продажів",
                "Не вдалося прочитати файл. Перевірте формат, кодування та структуру даних.\n" + str(exc),
            )
            return

        if not raw_rows:
            messagebox.showinfo("Імпорт продажів", "У файлі не знайдено рядків із товарами.")
            return

        warehouses = db.list_warehouses(active_only=True)
        if not warehouses:
            show_error("Імпорт продажів", "Спочатку створіть хоча б один склад.")
            return
        channels = db.list_channels(active_only=False)

        dialog = SalesImportDialog(self.frame.winfo_toplevel(), raw_rows, headers, warehouses, channels, self.settings)
        result = dialog.result
        if not result:
            return

        try:
            summary = self._process_sales_import(result["orders"], result["options"])
        except Exception:
            logging.exception("Помилка під час імпорту продажів")
            show_error("Імпорт продажів", "Імпорт перервано помилкою. Деталі у логах.")
            return

        messagebox.showinfo("Імпорт продажів", summary)
        self.refresh_sales()
        self.on_refresh_cash()
        self.on_refresh_stock()

    def _process_sales_import(self, orders: list[dict], options: dict) -> str:
        warehouse_id = options["warehouse_id"]
        channel_override = options.get("channel", "")
        mode = options.get("mode", "draft")
        allow_negative = bool(options.get("allow_negative"))
        create_products = bool(options.get("create_products", True))
        create_customers = bool(options.get("create_customers"))
        use_file_channel = bool(options.get("use_file_channel"))

        product_rows = db.list_products()
        products_by_sku = {p["sku"].lower(): dict(p) for p in product_rows if p["sku"]}
        products_by_name = {p["name"].lower(): dict(p) for p in product_rows if p["name"]}
        products_by_supplier_sku = {p["supplier_sku"].lower(): dict(p) for p in product_rows if p.get("supplier_sku")}
        counterparties = db.list_counterparties()
        allowed_customer_types = {"customer", "both", "other"}
        customers_by_name = {
            c["name"].lower(): c for c in counterparties if c["type"] in allowed_customer_types and c["name"]
        }

        default_brand = self.settings.get("defaults", "product", "brand") or "Імпорт"
        default_category = self.settings.get("defaults", "product", "category") or "Імпорт"
        default_unit = (self.settings.get("defaults", "product", "unit") or "pcs").strip() or "pcs"
        brand_id, category_id = db.ensure_import_defaults(default_brand, default_category)
        stock_map = db.stock_on_hand(warehouse_id)

        created_products = 0
        created_customers = 0
        skipped_lines = 0
        posted_docs = 0
        draft_docs = 0
        total_docs = 0

        grouped: dict[str, list[dict]] = defaultdict(list)
        for idx, row in enumerate(orders):
            key = row.get("order_no") or f"#{idx+1}"
            grouped[key].append(row)

        for order_no, lines in grouped.items():
            doc_date = lines[0].get("doc_date") or datetime.now().strftime("%Y-%m-%d")
            customer_name = lines[0].get("customer", "").strip()
            phone = lines[0].get("phone", "").strip()
            email = lines[0].get("email", "").strip()
            customer_id = None

            if customer_name:
                existing = customers_by_name.get(customer_name.lower()) or db.find_counterparty_by_name(
                    customer_name, allowed_customer_types
                )
                if existing:
                    customer_id = existing["id"]
                    customers_by_name[customer_name.lower()] = dict(existing)
                elif create_customers:
                    customer_id = db.add_counterparty(customer_name, "customer", phone, email, "", "Імпортований клієнт")
                    new_cp = {
                        "id": customer_id,
                        "name": customer_name,
                        "type": "customer",
                        "phone": phone,
                        "email": email,
                        "address": "",
                        "note": "Імпортований клієнт",
                    }
                    counterparties.append(new_cp)
                    customers_by_name[customer_name.lower()] = new_cp
                    created_customers += 1

            sale_lines: list[tuple[int, float, float, float]] = []
            comment = lines[0].get("comment", "").strip()
            line_channel = lines[0].get("channel", "").strip()
            channel_value = line_channel if (use_file_channel and line_channel) else channel_override

            for row in lines:
                sku = (row.get("sku") or "").strip()
                supplier_sku = (row.get("supplier_sku") or "").strip()
                name = (row.get("product_name") or sku or "Без назви").strip()
                qty = float(row.get("quantity") or 0)
                price = float(row.get("price") or 0)
                amount = float(row.get("amount") or 0)
                if not price and qty and amount:
                    price = amount / qty

                product_row = products_by_supplier_sku.get(supplier_sku.lower()) if supplier_sku else None
                if not product_row:
                    product_row = products_by_sku.get(sku.lower()) if sku else None
                if not product_row and name:
                    product_row = products_by_name.get(name.lower())
                if not product_row and create_products:
                    final_sku = sku or self.generate_unique_sku(name, set(products_by_sku.keys()))
                    product_id = db.add_product(
                        final_sku,
                        name,
                        brand_id,
                        category_id,
                        unit=default_unit,
                        supplier_sku=supplier_sku,
                    )
                    product_row = {
                        "id": product_id,
                        "sku": final_sku,
                        "name": name,
                        "supplier_sku": supplier_sku,
                    }
                    products_by_sku[final_sku.lower()] = product_row
                    if supplier_sku:
                        products_by_supplier_sku[supplier_sku.lower()] = product_row
                    products_by_name[name.lower()] = product_row
                    created_products += 1

                if not product_row or qty <= 0:
                    skipped_lines += 1
                    continue

                sale_lines.append((int(product_row["id"]), qty, price, 0.0))

            if not sale_lines:
                skipped_lines += len(lines)
                continue

            total_docs += 1
            try:
                sale_id = db.create_sale(doc_date, customer_id, warehouse_id, channel_value, comment, "UAH", 1.0)
                db.replace_sale_lines(sale_id, sale_lines, 1.0, 0.0)
            except Exception as exc:
                logging.warning("Не вдалося створити продаж %s: %s", order_no, exc)
                skipped_lines += len(sale_lines)
                continue

            should_post = mode == "post"
            if mode == "in_stock":
                enough = True
                for pid, qty, _, _ in sale_lines:
                    current_qty = stock_map.get(pid, db.get_stock_quantity(pid, warehouse_id))
                    if qty > current_qty:
                        enough = False
                        break
                should_post = enough

            if should_post:
                try:
                    db.post_sale(sale_id, allow_negative=allow_negative)
                    posted_docs += 1
                    for pid, qty, _, _ in sale_lines:
                        stock_map[pid] = stock_map.get(pid, db.get_stock_quantity(pid, warehouse_id)) - qty
                except Exception as exc:
                    logging.warning("Проведення продажу #%s завершилось помилкою: %s", sale_id, exc)
                    try:
                        db.unpost_sale(sale_id)
                    except Exception:
                        logging.exception("Не вдалося скасувати проведення після помилки імпорту")
                    draft_docs += 1
            else:
                draft_docs += 1

        lines_msg = f"Пропущено рядків: {skipped_lines}" if skipped_lines else "Без пропусків"
        created_parts = []
        if created_products:
            created_parts.append(f"створено товарів: {created_products}")
        if created_customers:
            created_parts.append(f"створено клієнтів: {created_customers}")
        created_msg = ", ".join(created_parts) if created_parts else "без нових довідників"
        return (
            f"Опрацьовано документів: {total_docs}. Проведено: {posted_docs}, чернеток: {draft_docs}. "
            f"{lines_msg}; {created_msg}."
        )


class SalesImportDialog(tk.Toplevel):
    def __init__(
        self,
        app: tk.Tk,
        raw_rows: list[dict[str, object]],
        headers: list[str],
        warehouses,
        channels,
        settings,
    ) -> None:
        super().__init__(app)
        self.title("Імпорт продажів")
        self.resizable(True, True)
        self.grab_set()
        self.result: Optional[dict] = None
        self.raw_rows = raw_rows
        self.headers = headers
        self.warehouses = warehouses
        self.channels = channels
        self.settings = settings
        self.templates: dict[str, dict[str, str]] = settings.get("sales_import", "templates") or {}
        self.current_mapping = _suggest_sales_mapping(headers)

        main = ttk.Frame(self, padding=10)
        main.pack(fill=tk.BOTH, expand=True)

        info = ttk.Label(main, text=f"Рядків у файлі: {len(raw_rows)}")
        info.grid(row=0, column=0, columnspan=3, sticky="w")

        self._build_template_controls(main)
        self._build_mapping_controls(main)
        self._build_options(main)
        self.preview = self._build_preview(main)
        self._refresh_preview()

        btns = ttk.Frame(main)
        btns.grid(row=12, column=0, columnspan=3, pady=8, sticky="e")
        ttk.Button(btns, text="Скасувати", command=self.destroy).pack(side=tk.RIGHT, padx=4)
        ttk.Button(btns, text="Імпортувати", command=self._on_ok).pack(side=tk.RIGHT, padx=4)

        self.bind("<Return>", lambda _e: self._on_ok())
        self.bind("<Escape>", lambda _e: self.destroy())
        self.wait_window(self)

    def _on_ok(self) -> None:
        warehouse = next((w for w in self.warehouses if w["name"] == self.wh_var.get()), None)
        if not warehouse:
            show_error("Імпорт", "Оберіть склад")
            return

        normalized_orders = _normalize_sales_records(self.raw_rows, self.current_mapping)
        self.result = {
            "options": {
                "warehouse_id": warehouse["id"],
                "channel": self.channel_var.get().strip(),
                "mode": self.mode_var.get(),
                "allow_negative": bool(self.allow_negative_var.get()),
                "create_products": bool(self.create_products_var.get()),
                "create_customers": bool(self.create_customers_var.get()),
                "use_file_channel": bool(self.use_file_channel_var.get()),
            },
            "orders": normalized_orders,
        }
        self.settings.set(self.current_template_name.get(), "sales_import", "last_template")
        self.settings.save()
        self.destroy()

    def _build_template_controls(self, parent: ttk.Frame) -> None:
        ttk.Label(parent, text="Шаблон співставлення:").grid(row=1, column=0, sticky="w", pady=4)
        self.current_template_name = tk.StringVar(value=self.settings.get("sales_import", "last_template") or "")
        self.template_combo = ttk.Combobox(
            parent, textvariable=self.current_template_name, values=list(self.templates.keys()), state="readonly"
        )
        self.template_combo.grid(row=1, column=1, sticky="ew", pady=4)
        ttk.Button(parent, text="Застосувати", command=self._apply_template).grid(row=1, column=2, padx=4, sticky="w")
        ttk.Button(parent, text="Зберегти як…", command=self._save_template).grid(row=1, column=3, padx=4, sticky="w")

    def _build_mapping_controls(self, parent: ttk.Frame) -> None:
        ttk.Label(parent, text="Співставлення колонок:").grid(row=2, column=0, sticky="nw", pady=4)
        mapping_frame = ttk.Frame(parent)
        mapping_frame.grid(row=2, column=1, columnspan=3, sticky="ew", pady=4)
        mapping_frame.columnconfigure(1, weight=1)

        options = ["(не використовувати)"] + self.headers
        self.mapping_vars: dict[str, tk.StringVar] = {}
        for idx, (field_key, field_label, _aliases) in enumerate(SALES_FIELDS):
            ttk.Label(mapping_frame, text=field_label).grid(row=idx, column=0, sticky="w", pady=2)
            var = tk.StringVar(value=self.current_mapping.get(field_key, ""))
            combo = ttk.Combobox(mapping_frame, textvariable=var, values=options, state="readonly")
            combo.grid(row=idx, column=1, sticky="ew", pady=2)
            combo.bind("<<ComboboxSelected>>", lambda _e, key=field_key, v=var: self._update_mapping(key, v.get()))
            self.mapping_vars[field_key] = var

    def _build_options(self, parent: ttk.Frame) -> None:
        ttk.Label(parent, text="Склад для імпорту:").grid(row=3, column=0, sticky="w", pady=4)
        self.wh_var = tk.StringVar(value=self.warehouses[0]["name"] if self.warehouses else "")
        wh_combo = ttk.Combobox(
            parent,
            textvariable=self.wh_var,
            values=[w["name"] for w in self.warehouses],
            state="readonly",
        )
        wh_combo.grid(row=3, column=1, sticky="ew", pady=4)

        ttk.Label(parent, text="Канал (якщо не вказано у файлі):").grid(row=4, column=0, sticky="w", pady=4)
        self.channel_var = tk.StringVar()
        channel_values = [c["name"] for c in self.channels]
        ttk.Combobox(parent, textvariable=self.channel_var, values=channel_values).grid(row=4, column=1, sticky="ew", pady=4)

        self.use_file_channel_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(parent, text="Брати канал із файлу, якщо він є", variable=self.use_file_channel_var).grid(
            row=5, column=1, sticky="w"
        )

        ttk.Label(parent, text="Режим проведення:").grid(row=6, column=0, sticky="nw", pady=4)
        mode_frame = ttk.Frame(parent)
        mode_frame.grid(row=6, column=1, sticky="w", pady=4)
        self.mode_var = tk.StringVar(value="post")
        ttk.Radiobutton(mode_frame, text="Провести всі", variable=self.mode_var, value="post").pack(anchor="w")
        ttk.Radiobutton(mode_frame, text="Тільки чернетки", variable=self.mode_var, value="draft").pack(anchor="w")
        ttk.Radiobutton(
            mode_frame, text="Проводити, лише якщо є залишок", variable=self.mode_var, value="in_stock"
        ).pack(anchor="w")

        self.allow_negative_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            parent,
            text="Дозволити від'ємний залишок під час проведення",
            variable=self.allow_negative_var,
        ).grid(row=7, column=1, sticky="w")

        self.create_products_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(parent, text="Створювати відсутні товари", variable=self.create_products_var).grid(
            row=8, column=1, sticky="w", pady=(4, 0)
        )
        self.create_customers_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(parent, text="Створювати відсутніх клієнтів", variable=self.create_customers_var).grid(
            row=9, column=1, sticky="w"
        )

    def _build_preview(self, parent: ttk.Frame) -> ttk.Treeview:
        ttk.Label(parent, text="Попередній перегляд (перші 30 рядків):").grid(
            row=10, column=0, columnspan=3, sticky="w", pady=6
        )
        preview = ttk.Treeview(
            parent,
            columns=("order", "date", "customer", "sku", "name", "qty", "price"),
            show="headings",
            height=10,
        )
        headings = {
            "order": ("Замовлення", 120),
            "date": ("Дата", 90),
            "customer": ("Клієнт", 160),
            "sku": ("SKU", 90),
            "name": ("Товар", 200),
            "qty": ("К-сть", 70),
            "price": ("Ціна", 90),
        }
        for col, (title, width) in headings.items():
            preview.heading(col, text=title)
            preview.column(col, width=width, anchor="w")
        preview.grid(row=11, column=0, columnspan=3, sticky="nsew")
        parent.grid_rowconfigure(11, weight=1)
        parent.grid_columnconfigure(1, weight=1)
        scroll = ttk.Scrollbar(parent, orient="vertical", command=preview.yview)
        preview.configure(yscrollcommand=scroll.set)
        scroll.grid(row=11, column=3, sticky="ns")
        return preview

    def _refresh_preview(self) -> None:
        self.preview.delete(*self.preview.get_children())
        normalized = _normalize_sales_records(self.raw_rows, self.current_mapping)
        for row in normalized[:30]:
            self.preview.insert(
                "",
                "end",
                values=(
                    row.get("order_no") or "-",
                    row.get("doc_date"),
                    row.get("customer"),
                    row.get("sku"),
                    row.get("product_name"),
                    f"{float(row.get('quantity') or 0):.2f}",
                    f"{float(row.get('price') or 0):.2f}",
                ),
            )

    def _update_mapping(self, key: str, value: str) -> None:
        clean_value = "" if value == "(не використовувати)" else value
        self.current_mapping[key] = clean_value
        self._refresh_preview()

    def _apply_template(self) -> None:
        name = self.current_template_name.get().strip()
        if not name or name not in self.templates:
            return
        template = self.templates[name]
        for key, var in self.mapping_vars.items():
            var.set(template.get(key, ""))
            self.current_mapping[key] = template.get(key, "")
        self._refresh_preview()

    def _save_template(self) -> None:
        values = simple_prompt(
            "Назва шаблону",
            ["Вкажіть назву шаблону"],
            [self.current_template_name.get().strip()],
        )
        if not values:
            return

        name = values[0].strip()
        if not name:
            return

        self.templates[name] = dict(self.current_mapping)
        self.settings.set(self.templates, "sales_import", "templates")
        self.settings.set(name, "sales_import", "last_template")
        self.settings.save()
        self.current_template_name.set(name)
        self.template_combo.configure(values=list(self.templates.keys()))
