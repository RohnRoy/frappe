# Copyright (c) 2015, Frappe Technologies Pvt. Ltd. and Contributors
# License: MIT. See LICENSE

import collections
import os
import shutil

import click

import frappe
from frappe.core.doctype.data_import.data_import import export_json, import_doc


def sync_fixtures(app=None):
	"""Import, overwrite fixtures from `[app]/fixtures`"""
	if app:
		apps = [app]
	else:
		apps = frappe.get_installed_apps()

	frappe.flags.in_fixtures = True

	for app in apps:
		import_fixtures(app)
		import_custom_scripts(app)

	frappe.flags.in_fixtures = False


def import_fixtures(app):
	fixtures_path = frappe.get_app_path(app, "fixtures")
	if not os.path.exists(fixtures_path):
		return

	fixture_files = sorted(os.listdir(fixtures_path))

	for fname in fixture_files:
		file_path = frappe.get_app_path(app, "fixtures", fname)

		# If it's a directory (produced by fixture_split_by_dt), import each
		# JSON file inside it in sorted order. Skip `custom_scripts` which is
		# handled separately by import_custom_scripts().
		if os.path.isdir(file_path):
			if fname == "custom_scripts":
				continue
			sub_files = sorted(
				os.path.join(file_path, f)
				for f in os.listdir(file_path)
				if f.endswith(".json")
			)
			for sub_file in sub_files:
				try:
					import_doc(sub_file)
				except (ImportError, frappe.DoesNotExistError) as e:
					print(f"Skipping fixture syncing from {sub_file}. Reason: {e}")
			continue

		if not fname.endswith(".json"):
			continue

		try:
			import_doc(file_path, sort=True)
		except (ImportError, frappe.DoesNotExistError) as e:
			# fixture syncing for missing doctypes
			print(f"Skipping fixture syncing from the file {fname}. Reason: {e}")


def import_custom_scripts(app):
	"""Import custom scripts from `[app]/fixtures/custom_scripts`"""
	scripts_folder = frappe.get_app_path(app, "fixtures", "custom_scripts")
	if not os.path.exists(scripts_folder):
		return

	for fname in os.listdir(scripts_folder):
		if not fname.endswith(".js"):
			continue

		click.secho(
			f"Importing Client Script `{fname}` from `{scripts_folder}` is not supported. Convert the client script to fixture.",
			fg="red",
		)


def export_fixtures(app=None):
	"""Export fixtures as JSON to `[app]/fixtures`"""
	if app:
		apps = [app]
	else:
		apps = frappe.get_installed_apps()
	for app in apps:
		fixture_auto_order = bool(next(iter(frappe.get_hooks("fixture_auto_order", app_name=app)), False))
		# Check if app opts into per-dt split
		fixture_split_by_dt = bool(next(iter(frappe.get_hooks("fixture_split_by_dt", app_name=app)), False))

		fixtures = frappe.get_hooks("fixtures", app_name=app)
		prefix = None
		for index, fixture in enumerate(fixtures, start=1):
			filters = None
			or_filters = None
			if isinstance(fixture, dict):
				filters = fixture.get("filters")
				or_filters = fixture.get("or_filters")
				prefix = fixture.get("prefix")
				fixture = fixture.get("doctype") or fixture.get("dt")
			print(f"Exporting {fixture} app {app} filters {(filters if filters else or_filters)}")
			if not os.path.exists(frappe.get_app_path(app, "fixtures")):
				os.mkdir(frappe.get_app_path(app, "fixtures"))

			filename = frappe.scrub(fixture)
			if prefix:
				filename = f"{prefix}_{filename}"
			if fixture_auto_order:
				number_of_digits = len(str(len(fixtures)))
				# add zero padding so files can be sorted lexicographically with filename.
				file_number = str(index).zfill(number_of_digits)
				filename = f"{file_number}_{filename}"

			if fixture_split_by_dt:
				folder_path = frappe.get_app_path(app, "fixtures", filename)
				flat_file = folder_path + ".json"

				# Remove stale flat file left over from before split was enabled
				if os.path.isfile(flat_file):
					os.remove(flat_file)

				export_json_split_by_dt(
					fixture,
					folder_path,
					filters=filters,
					or_filters=or_filters,
				)
			else:
				flat_file = frappe.get_app_path(app, "fixtures", filename + ".json")
				dir_path = frappe.get_app_path(app, "fixtures", filename)

				# Remove stale split directory left over from when split was enabled
				if os.path.isdir(dir_path):
					shutil.rmtree(dir_path)

				export_json(
					fixture,
					flat_file,
					filters=filters,
					or_filters=or_filters,
					order_by="name asc",
				)


def export_json_split_by_dt(doctype, folder_path, filters=None, or_filters=None):
	"""
	Export records into one JSON file per parent doctype (dt field).
	Used for Custom Field, Property Setter, Custom DocPerm etc.
	Falls back to a single file if the doctype has no `dt` field.

	Folder structure produced:
	    fixtures/
	        custom_field/
	            customer.json
	            purchase_order.json
	            sales_order.json
	"""
	# Check if this doctype has a `dt` field at all
	meta = frappe.get_meta(doctype)
	has_dt_field = any(f.fieldname == "dt" for f in meta.fields)

	if not has_dt_field:
		# Fall back to single file — no point splitting
		export_json(
			doctype,
			folder_path + ".json",
			filters=filters,
			or_filters=or_filters,
			order_by="name asc",
		)
		return

	# Fetch all records, ordered so same-dt records arrive together
	all_names = frappe.get_all(
		doctype,
		fields=["name", "dt"],
		filters=filters,
		or_filters=or_filters,
		limit_page_length=0,
		order_by="dt asc, idx asc, name asc",
	)

	if not all_names:
		return

	# Group by dt
	grouped = collections.defaultdict(list)
	for row in all_names:
		grouped[row.dt].append(row.name)

	# Ensure the folder exists (e.g. fixtures/custom_field/)
	os.makedirs(folder_path, exist_ok=True)

	written = set()
	for dt, names in sorted(grouped.items()):
		out = []
		for name in names:
			out.append(frappe.get_doc(doctype, name).as_dict())

		post_process_fixture_docs(out)

		# File name: frappe.scrub converts "Sales Order" → "sales_order"
		safe_dt = frappe.scrub(dt)
		fname = safe_dt + ".json"
		file_path = os.path.join(folder_path, fname)

		with open(file_path, "w") as f:
			f.write(frappe.as_json(out, ensure_ascii=False) + "\n")

		written.add(fname)
		print(f"  └─ {dt}: {len(out)} records → {os.path.basename(file_path)}")

	# Remove stale per-DocType files only after all new files are written
	# (avoids leaving an empty folder if an exception occurs mid-export)
	for existing_file in os.listdir(folder_path):
		if existing_file.endswith(".json") and existing_file not in written:
			os.remove(os.path.join(folder_path, existing_file))


def post_process_fixture_docs(out):
	"""Strip volatile/non-portable keys from exported fixture docs.

	Note on Tree DocTypes:
	    The tree structure is maintained in the database via the fields "lft"
	    and "rgt". They are automatically set and kept up-to-date. Importing
	    them would destroy any existing tree structure, so they are stripped.

	Child-table keys (parent, parentfield, parenttype) are also stripped
	because they are re-derived from the nested JSON structure by
	frappe.get_doc() on import.
	"""
	del_keys = ("modified_by", "modified", "creation", "owner", "idx", "lft", "rgt")
	for doc in out:
		for key in del_keys:
			if key in doc:
				del doc[key]
		for v in doc.values():
			if isinstance(v, list):
				for child in v:
					for key in (
						*del_keys,
						"docstatus",
						"doctype",
						"modified",
						"name",
						"parent",
						"parentfield",
						"parenttype",
					):
						if key in child:
							del child[key]
