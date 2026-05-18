# Copyright (c) 2015, Frappe Technologies and contributors
# For license information, please see license.txt


import json

import frappe
from frappe import _
from frappe.model.document import Document


class Course(Document):
	def validate(self):
		self._calcular_horas_totales()
		self.validate_assessment_criteria()
		self.validate_course_documents()
		self.validate_status_change()
		self._validar_no_en_matricula_activa()
		self._actualizar_estado_matricula()

	def onload(self):
		self._actualizar_estado_matricula()

	def _actualizar_estado_matricula(self):
		if not self.is_new():
			activo = 1 if _get_active_enrollment_term_for_course(self.name) else 0
			self.has_active_enrollment = activo
			self.db_set("has_active_enrollment", activo, update_modified=False)

	def on_update(self):
		"""RF-12: notifica cuando un curso existente pasa a Activo."""
		if self.is_new():
			return
		before = self.get_doc_before_save()
		if not before:
			return
		if before.get("course_status") != "Activo" and self.course_status == "Activo":
			self._enviar_notificacion_curso_activo()
		if self.moodle_course_id:
			from education.moodle_integration.events import on_course_updated
			on_course_updated(self, "on_update")

	def _enviar_notificacion_curso_activo(self):
		"""Dispara las notificaciones 'Nuevo Curso Disponible' para cursos activados post-creación."""
		for nombre in ("Nuevo Curso Disponible - Sistema", "Nuevo Curso Disponible - Email"):
			notif = frappe.db.get_value("Notification", nombre, "name")
			if notif:
				try:
					frappe.get_doc("Notification", nombre).send(self)
				except Exception:
					frappe.log_error(
						frappe.get_traceback(),
						f"Error al enviar notificación '{nombre}' para curso {self.name}",
					)

	def on_trash(self):
		self._validar_no_en_matricula_activa()

	def _calcular_horas_totales(self):
		self.total_hours = (self.theory_hours or 0) + (self.practical_hours or 0)

	def validate_course_documents(self):
			"""RF-17: eliminar filas vacías y validar campos requeridos."""
			docs_validos = []
			for row in self.course_documents:
				tiene_nombre = bool(row.document_name and row.document_name.strip())
				tiene_archivo = bool(row.document_file)
				
				if not tiene_nombre and not tiene_archivo:
					# Fila completamente vacía → ignorar silenciosamente
					continue
				
				if tiene_nombre and tiene_archivo:
					docs_validos.append(row)
				else:
					# Fila parcialmente llena → error claro
					frappe.throw(
						_("Fila {0} en Documentos: debe completar tanto <b>Nombre</b> como <b>Archivo</b>.").format(
							row.idx
						)
					)

			self.course_documents = docs_validos

	def validate_status_change(self):
		"""RF-26/RF-27: controla cambios de estado del curso."""
		if self.is_new():
			return

		before = self._doc_before_save
		if not before:
			return

		prev_status = before.get("course_status")
		new_status = self.course_status

		if prev_status == new_status:
			return

		# RF-26/RF-27: solo roles autorizados pueden cambiar el estado
		allowed_roles = {"Administrator", "Education Manager", "System Manager"}
		user_roles = set(frappe.get_roles(frappe.session.user))
		if not allowed_roles & user_roles:
			frappe.throw(
				_("Solo un Administrador o Education Manager puede cambiar el estado del curso."),
				title=_("Permiso denegado"),
			)

		# RF-27: bloquear cancelación si hay estudiantes matriculados
		if new_status == "Cancelado":
			# Usar UNION para contar estudiantes únicos entre ambas rutas sin duplicados
			result = frappe.db.sql(
				"""
				SELECT COUNT(DISTINCT student) as total FROM (
					SELECT student FROM `tabCourse Enrollment`
					WHERE course = %s
					UNION
					SELECT pe.student FROM `tabProgram Enrollment Course` pec
					INNER JOIN `tabProgram Enrollment` pe ON pe.name = pec.parent
					WHERE pec.course = %s
					  AND pe.docstatus = 1
				) AS matriculados
				""",
				(self.name, self.name),
				as_dict=True,
			)
			total_enrolled = result[0].total if result else 0

			if total_enrolled:
				frappe.throw(
					_("No se puede cancelar el curso <b>{0}</b>: tiene {1} estudiante(s) matriculado(s).").format(
						self.course_name, total_enrolled
					),
					title=_("Cancelación bloqueada"),
				)

	def _validar_no_en_matricula_activa(self):
		"""RT-3: bloquea edición y eliminación si el curso tiene matrícula activa abierta."""
		if self.is_new():
			return
		term = _get_active_enrollment_term_for_course(self.name)
		if term:
			frappe.throw(
				_("El curso <b>{0}</b> no puede modificarse ni eliminarse: "
				  "está dentro del período de matrícula activa del término <b>{1}</b> "
				  "({2} al {3}).").format(
					self.course_name,
					term.name,
					frappe.format(term.enrollment_start_date, "Date"),
					frappe.format(term.enrollment_end_date, "Date"),
				),
				title=_("Matrícula activa"),
			)

	def validate_assessment_criteria(self):
		if self.assessment_criteria:
			total_weightage = 0
			for criteria in self.assessment_criteria:
				total_weightage += criteria.weightage or 0
			if total_weightage != 100:
				frappe.throw(_("Total Weightage of all Assessment Criteria must be 100%"))

	def after_insert(self):
		"""Hook llamado después de insertar el documento."""
		from education.moodle_integration.events import on_course_created
		on_course_created(self, "after_insert")

	def on_rename(self, old_name, new_name, merge=False):
		"""Hook llamado después de renombrar el documento."""
		from education.moodle_integration.events import sync_course_to_moodle

		if self.moodle_course_id:
			frappe.enqueue(
				sync_course_to_moodle,
				course_name=new_name,
				queue="short",
				enqueue_after_commit=True,
			)

	def get_topics(self):
		topic_data = []
		for topic in self.topics:
			topic_doc = frappe.get_doc("Topic", topic.topic)
			if topic_doc.topic_content:
				topic_data.append(topic_doc)
		return topic_data


def _get_active_enrollment_term_for_course(course_name):
	"""
	Retorna el Academic Term activo cuya ventanilla de matrícula está abierta
	y que tiene al menos un Student Group que usa este curso.
	Retorna None si no hay ninguno.
	"""
	today = frappe.utils.today()

	# Buscar Student Groups que usen este curso y tengan academic_term definido
	groups = frappe.db.get_all(
		"Student Group",
		filters={"course": course_name, "disabled": 0, "academic_term": ["!=", ""]},
		fields=["academic_term"],
	)
	if not groups:
		return None

	term_names = list({g.academic_term for g in groups if g.academic_term})
	if not term_names:
		return None

	# De esos términos, buscar si alguno tiene ventanilla activa y hoy está en rango
	for term_name in term_names:
		term = frappe.db.get_value(
			"Academic Term",
			term_name,
			["name", "enrollment_open", "enrollment_start_date", "enrollment_end_date"],
			as_dict=True,
		)
		if not term or not term.enrollment_open:
			continue
		start = term.enrollment_start_date
		end = term.enrollment_end_date
		if start and end and str(start) <= today <= str(end):
			return term

	return None


@frappe.whitelist()
def add_course_to_programs(course, programs, mandatory=False):
	programs = json.loads(programs)
	for entry in programs:
		program = frappe.get_doc("Program", entry)
		program.append(
			"courses", {"course": course, "course_name": course, "mandatory": mandatory}
		)
		program.flags.ignore_mandatory = True
		program.save()
	frappe.msgprint(
		_("Course {0} has been added to all the selected programs successfully.").format(
			frappe.bold(course)
		),
		title=_("Programs updated"),
		indicator="green",
	)


@frappe.whitelist()
def get_programs_without_course(course):
	data = []
	for entry in frappe.db.get_all("Program"):
		program = frappe.get_doc("Program", entry.name)
		courses = [c.course for c in program.courses]
		if not courses or course not in courses:
			data.append(program.name)
	return data

	