# Copyright (c) 2015, Frappe Technologies Pvt. Ltd. and Contributors
# License: MIT. See LICENSE
import frappe
from frappe.cache_manager import clear_controller_cache
from frappe.desk.doctype.todo.todo import ToDo
from frappe.tests import IntegrationTestCase
from frappe.tests.test_api import FrappeAPITestCase


class TestHooks(IntegrationTestCase):
	def test_hooks(self):
		hooks = frappe.get_hooks()
		self.assertTrue(isinstance(hooks.get("app_name"), list))
		self.assertTrue(isinstance(hooks.get("doc_events"), dict))
		self.assertTrue(isinstance(hooks.get("doc_events").get("*"), dict))
		self.assertTrue(isinstance(hooks.get("doc_events").get("*"), dict))
		self.assertTrue(
			"frappe.desk.notifications.clear_doctype_notifications"
			in hooks.get("doc_events").get("*").get("on_update")
		)

	def test_override_doctype_class(self):
		from frappe import hooks

		# Set hook
		hooks.override_doctype_class = {"ToDo": ["frappe.tests.test_hooks.CustomToDo"]}

		# Clear cache
		frappe.client_cache.delete_value("app_hooks")
		clear_controller_cache("ToDo")

		todo = frappe.get_doc(doctype="ToDo", description="asdf")
		self.assertTrue(isinstance(todo, CustomToDo))

	def test_has_permission(self):
		from frappe import hooks

		# Set hook
		address_has_permission_hook = hooks.has_permission.get("Address", [])
		if isinstance(address_has_permission_hook, str):
			address_has_permission_hook = [address_has_permission_hook]

		address_has_permission_hook.append("frappe.tests.test_hooks.custom_has_permission")

		hooks.has_permission["Address"] = address_has_permission_hook

		wildcard_has_permission_hook = hooks.has_permission.get("*", [])
		if isinstance(wildcard_has_permission_hook, str):
			wildcard_has_permission_hook = [wildcard_has_permission_hook]

		wildcard_has_permission_hook.append("frappe.tests.test_hooks.custom_has_permission")

		hooks.has_permission["*"] = wildcard_has_permission_hook

		# Clear cache
		frappe.client_cache.delete_value("app_hooks")

		# Init User and Address
		username = "test@example.com"
		user = frappe.get_doc("User", username)
		user.add_roles("System Manager")
		address = frappe.new_doc("Address")

		# Create Note
		note = frappe.new_doc("Note")
		note.public = 1

		# Test!
		self.assertTrue(frappe.has_permission("Address", doc=address, user=username))
		self.assertTrue(frappe.has_permission("Note", doc=note, user=username))

		address.flags.dont_touch_me = True
		self.assertFalse(frappe.has_permission("Address", doc=address, user=username))

		note.flags.dont_touch_me = True
		self.assertFalse(frappe.has_permission("Note", doc=note, user=username))

	def test_ignore_links_on_delete(self):
		email_unsubscribe = frappe.get_doc(
			{"doctype": "Email Unsubscribe", "email": "test@example.com", "global_unsubscribe": 1}
		).insert()

		event = frappe.get_doc(
			{
				"doctype": "Event",
				"subject": "Test Event",
				"starts_on": "2022-12-21",
				"event_type": "Public",
				"event_participants": [
					{
						"reference_doctype": "Email Unsubscribe",
						"reference_docname": email_unsubscribe.name,
					}
				],
			}
		).insert()
		self.assertRaises(frappe.LinkExistsError, email_unsubscribe.delete)

		event.event_participants = []
		event.save()

		todo = frappe.get_doc(
			{
				"doctype": "ToDo",
				"description": "Test ToDo",
				"reference_type": "Event",
				"reference_name": event.name,
			}
		)
		todo.insert()

		event.delete()

	def test_fixture_prefix(self):
		import os
		import shutil

		from frappe import hooks
		from frappe.utils.fixtures import export_fixtures

		app = "frappe"
		if os.path.isdir(frappe.get_app_path(app, "fixtures")):
			shutil.rmtree(frappe.get_app_path(app, "fixtures"))

		# use any set of core doctypes for test purposes
		hooks.fixtures = [
			{"dt": "User"},
			{"dt": "Contact"},
			{"dt": "Role"},
		]
		hooks.fixture_auto_order = False
		# every call to frappe.get_hooks loads the hooks module into cache
		# therefor the cache has to be invalidated after every manual overwriting of hooks
		# TODO replace with a more elegant solution if there is one or build a util function for this purpose
		if frappe._load_app_hooks in frappe.local.request_cache.keys():
			del frappe.local.request_cache[frappe._load_app_hooks]
		self.assertEqual([False], frappe.get_hooks("fixture_auto_order", app_name=app))
		self.assertEqual(
			[
				{"dt": "User"},
				{"dt": "Contact"},
				{"dt": "Role"},
			],
			frappe.get_hooks("fixtures", app_name=app),
		)

		export_fixtures(app)
		# use assertCountEqual (replaced assertItemsEqual), beacuse os.listdir might return the list in a different order, depending on OS
		self.assertCountEqual(
			["user.json", "contact.json", "role.json"], os.listdir(frappe.get_app_path(app, "fixtures"))
		)

		hooks.fixture_auto_order = True
		del frappe.local.request_cache[frappe._load_app_hooks]
		self.assertEqual([True], frappe.get_hooks("fixture_auto_order", app_name=app))

		shutil.rmtree(frappe.get_app_path(app, "fixtures"))
		export_fixtures(app)
		self.assertCountEqual(
			["1_user.json", "2_contact.json", "3_role.json"],
			os.listdir(frappe.get_app_path(app, "fixtures")),
		)

		hooks.fixtures = [
			{"dt": "User", "prefix": "my_prefix"},
			{"dt": "Contact"},
			{"dt": "Role"},
		]
		hooks.fixture_auto_order = False

		del frappe.local.request_cache[frappe._load_app_hooks]
		shutil.rmtree(frappe.get_app_path(app, "fixtures"))
		export_fixtures(app)
		self.assertCountEqual(
			["my_prefix_user.json", "contact.json", "role.json"],
			os.listdir(frappe.get_app_path(app, "fixtures")),
		)

		hooks.fixture_auto_order = True
		del frappe.local.request_cache[frappe._load_app_hooks]
		shutil.rmtree(frappe.get_app_path(app, "fixtures"))
		export_fixtures(app)
		self.assertCountEqual(
			["1_my_prefix_user.json", "2_contact.json", "3_role.json"],
			os.listdir(frappe.get_app_path(app, "fixtures")),
		)

	def test_fixture_split_by_dt(self):
		"""When fixture_split_by_dt is enabled, Custom Field (which has a dt field)
		should be exported into a directory with one JSON file per parent DocType."""
		import os
		import shutil

		from frappe import hooks
		from frappe.utils.fixtures import export_fixtures, import_fixtures

		app = "frappe"
		fixtures_path = frappe.get_app_path(app, "fixtures")
		if os.path.isdir(fixtures_path):
			shutil.rmtree(fixtures_path)

		hooks.fixtures = [{"dt": "Custom Field"}]
		hooks.fixture_auto_order = False
		hooks.fixture_split_by_dt = True

		if frappe._load_app_hooks in frappe.local.request_cache.keys():
			del frappe.local.request_cache[frappe._load_app_hooks]

		export_fixtures(app)

		split_dir = os.path.join(fixtures_path, "custom_field")
		flat_file = os.path.join(fixtures_path, "custom_field.json")

		# A directory should have been created, not a flat file
		self.assertTrue(os.path.isdir(split_dir), "Expected custom_field/ directory to exist")
		self.assertFalse(os.path.isfile(flat_file), "Flat custom_field.json should not exist")

		# The directory should contain JSON files (unless no Custom Fields exist,
		# in which case the directory may be empty — that's acceptable)
		json_files = [f for f in os.listdir(split_dir) if f.endswith(".json")]
		if frappe.get_all("Custom Field", limit=1):
			self.assertGreater(len(json_files), 0, "Expected at least one per-dt JSON file")

		# Verify import_fixtures can read the split directory without errors
		import_fixtures(app)

		# Cleanup
		shutil.rmtree(fixtures_path)

		# Reset hooks
		hooks.fixture_split_by_dt = False
		if frappe._load_app_hooks in frappe.local.request_cache.keys():
			del frappe.local.request_cache[frappe._load_app_hooks]

	def test_fixture_split_fallback_no_dt_field(self):
		"""When fixture_split_by_dt is enabled but the DocType has no dt field,
		it should fall back to a flat JSON file instead of creating a directory."""
		import os
		import shutil

		from frappe import hooks
		from frappe.utils.fixtures import export_fixtures

		app = "frappe"
		fixtures_path = frappe.get_app_path(app, "fixtures")
		if os.path.isdir(fixtures_path):
			shutil.rmtree(fixtures_path)

		hooks.fixtures = [{"dt": "Role"}]
		hooks.fixture_auto_order = False
		hooks.fixture_split_by_dt = True

		if frappe._load_app_hooks in frappe.local.request_cache.keys():
			del frappe.local.request_cache[frappe._load_app_hooks]

		export_fixtures(app)

		flat_file = os.path.join(fixtures_path, "role.json")
		split_dir = os.path.join(fixtures_path, "role")

		# Should produce a flat file since Role has no "dt" field
		self.assertTrue(os.path.isfile(flat_file), "Expected role.json flat file for fallback")
		self.assertFalse(os.path.isdir(split_dir), "role/ directory should not exist for fallback")

		# Cleanup
		shutil.rmtree(fixtures_path)

		# Reset hooks
		hooks.fixture_split_by_dt = False
		if frappe._load_app_hooks in frappe.local.request_cache.keys():
			del frappe.local.request_cache[frappe._load_app_hooks]


class TestAPIHooks(FrappeAPITestCase):
	def test_auth_hook(self):
		with self.patch_hooks({"auth_hooks": ["frappe.tests.test_hooks.custom_auth"]}):
			site_url = frappe.utils.get_site_url(frappe.local.site)
			response = self.get(
				site_url + "/api/method/frappe.auth.get_logged_user",
				headers={"Authorization": "Bearer set_test_example_user"},
			)
			# Test!
			self.assertTrue(response.json.get("message") == "test@example.com")


def custom_has_permission(doc, ptype, user):
	if doc.flags.dont_touch_me:
		return False
	return True


def custom_auth():
	_auth_type, token = frappe.get_request_header("Authorization", "Bearer ").split(" ")
	if token == "set_test_example_user":
		frappe.set_user("test@example.com")


class CustomToDo(ToDo):
	pass
