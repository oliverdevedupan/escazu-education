# Copyright (c) 2015, Frappe Technologies and contributors
# For license information, please see license.txt

import re
import frappe
from frappe import _
from frappe.model.document import Document
from frappe.model.naming import set_name_by_naming_series


class Instructor(Document):
	def autoname(self):
		naming_method = frappe.db.get_value(
			"Education Settings", None, "instructor_created_by"
		)
		if not naming_method:
			frappe.throw(
				_("Please setup Instructor Naming System in Education > Education Settings")
			)
		else:
			if naming_method == "Naming Series":
				set_name_by_naming_series(self)
			elif naming_method == "Employee Number":
				if not self.employee:
					frappe.throw(_("Please select Employee"))
				self.name = self.employee
			elif naming_method == "Full Name":
				self.name = self.instructor_name

	def validate(self):
		self.validate_duplicate_employee()
		self.validate_email()
		self.validate_phone()
		self.validate_cedula()
		self.validate_required_fields()
		self.validate_deactivation()


	def validate_email(self):
		"""Valida que el correo electrónico tenga formato correcto."""
		if self.get("email_id"):
			pattern = r'^[\w\.-]+@[\w\.-]+\.\w{2,}$'
			if not re.match(pattern, self.email_id):
				frappe.throw(_("El formato del correo electrónico no es válido: {0}").format(self.email_id))

	def validate_phone(self):
		"""Valida que el teléfono solo contenga números y tenga longitud correcta."""
		if self.get("phone"):
			# Permite +, espacios y guiones para limpiar antes de validar
			clean_phone = re.sub(r'[\s\-\(\)]', '', self.phone)
			if not re.match(r'^\+?\d{7,15}$', clean_phone):
				frappe.throw(
					_("El formato del teléfono no es válido: {0}. Use solo números (7-15 dígitos).").format(self.phone)
				)

	def validate_cedula(self):
		"""Valida que la cédula solo contenga dígitos."""
		if self.get("cedula"):
			if not re.match(r'^\d{5,20}$', self.cedula.replace("-", "")):
				frappe.throw(_("El formato de la cédula no es válido: {0}").format(self.cedula))

	def validate_required_fields(self):
		"""Verifica que todos los campos obligatorios del RT-8 estén completos."""
		required = {
			"cedula": _("Cédula"),
			"last_name": _("Apellido"),
			"phone": _("Teléfono"),
			"email_id": _("Correo Electrónico"),
			"specialty": _("Especialidad"),
			"supplier_company": _("Empresa Proveedora"),
		}
		for fieldname, label in required.items():
			if not self.get(fieldname):
				frappe.throw(_("El campo {0} es obligatorio.").format(label))

	def validate_deactivation(self):
		"""Al desactivar un instructor verifica que no tenga grupos activos ni horarios futuros asignados."""
		if self.is_new():
			return

		previous_status = frappe.db.get_value("Instructor", self.name, "status")
		if previous_status != "Active" or self.status != "Inactive":
			return

		grupos = self._get_active_student_groups()
		if grupos:
			lineas = [f"  • {g.course} — {g.name}" for g in grupos]
			frappe.throw(
				_(
					"No se puede desactivar el instructor porque tiene {0} grupo(s) de estudiantes activo(s):\n\n"
					"{1}\n\n"
					"Por favor, reasigne o elimine esos grupos antes de desactivar este perfil."
				).format(len(grupos), "\n".join(lineas)),
				title=_("⚠️ Instructor con Grupos Activos"),
			)

		horarios = self._get_active_schedules()
		if not horarios:
			return

		lineas = [f"  • {c.course} — {frappe.format(c.schedule_date, 'Date')} ({c.name})" for c in horarios]
		frappe.throw(
			_(
				"No se puede desactivar el instructor porque tiene {0} horario(s) futuro(s) asignado(s):\n\n"
				"{1}\n\n"
				"Por favor, reasigne o elimine esos horarios antes de desactivar este perfil."
			).format(len(horarios), "\n".join(lineas)),
			title=_("⚠️ Instructor con Horarios Activos"),
		)

	def _get_active_schedules(self):
		"""Retorna los Course Schedules futuros asignados a este instructor."""
		return frappe.db.get_all(
			"Course Schedule",
			filters={
				"instructor": self.name,
				"schedule_date": [">=", frappe.utils.today()],
				"docstatus": ["!=", 2],
			},
			fields=["name", "course", "schedule_date"],
			order_by="schedule_date asc",
		)

	def _get_active_student_groups(self):
		"""Retorna Student Groups activos donde este instructor está asignado."""
		return frappe.db.sql(
			"""
			SELECT sg.name, sg.course
			FROM `tabStudent Group` sg
			INNER JOIN `tabStudent Group Instructor` sgi ON sgi.parent = sg.name
			WHERE sgi.instructor = %s AND (sg.disabled = 0 OR sg.disabled IS NULL)
			ORDER BY sg.name
			""",
			self.name,
			as_dict=True,
		)


	def validate_duplicate_employee(self):
		if self.employee and frappe.db.get_value(
			"Instructor", {"employee": self.employee, "name": ["!=", self.name]}, "name"
		):
			frappe.throw(_("Employee ID is linked with another instructor"))


	def after_insert(self):
		"""Crea usuario del sistema y envía credenciales al instructor."""
		self.create_instructor_user()

	def create_instructor_user(self):
		"""
		Crea un usuario Frappe para el instructor si no existe,
		asignando el rol 'Instructor'. Frappe enviará automáticamente
		el correo de bienvenida con las credenciales.
		"""
		email = self.get("email_id")
		if not email:
			return

		if frappe.db.exists("User", email):
			frappe.msgprint(
				_("El usuario {0} ya existe en el sistema.").format(email),
				indicator="orange"
			)
			return

		try:
			user = frappe.get_doc({
				"doctype": "User",
				"email": email,
				"first_name": self.instructor_name,
				"last_name": self.get("last_name") or "",
				"send_welcome_email": 1,
				"roles": [{"role": "Instructor"}],
			})
			user.insert(ignore_permissions=True)

			# Guardar referencia al usuario creado en el Instructor
			frappe.db.set_value("Instructor", self.name, "user", user.name)

			frappe.msgprint(
				_("Usuario creado exitosamente. Se han enviado las credenciales a {0}.").format(email),
				indicator="green"
			)
		except Exception as e:
			frappe.log_error(
				message=frappe.get_traceback(),
				title=f"Error al crear usuario para instructor {self.name}"
			)
			frappe.msgprint(
				_("El perfil fue creado, pero ocurrió un error al generar el usuario: {0}").format(str(e)),
				indicator="orange"
			)



@frappe.whitelist()
def get_active_assignments(instructor):
	"""Retorna horarios futuros del instructor para validación en cliente."""
	schedules = frappe.db.get_all(
		"Course Schedule",
		filters={
			"instructor": instructor,
			"schedule_date": [">=", frappe.utils.today()],
			"docstatus": ["!=", 2],
		},
		fields=["name", "course", "schedule_date"],
		order_by="schedule_date asc",
	)
	return {"schedules": schedules, "groups": []}


def get_timeline_data(doctype, name):
	"""Return timeline for course schedule"""
	return dict(
		frappe.db.sql(
			"""
			SELECT unix_timestamp(`schedule_date`), count(*)
			FROM `tabCourse Schedule`
			WHERE
				instructor=%s and
				`schedule_date` > date_sub(curdate(), interval 1 year)
			GROUP BY schedule_date
		""",
			name,
		)
	)