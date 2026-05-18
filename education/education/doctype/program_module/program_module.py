import frappe
from frappe.model.document import Document


class ProgramModule(Document):

	def validate(self):
		self._calcular_horas_totales()
		self._validar_tipo_programa()
		self._validar_tipo_asignaturas()
		self._validar_asignaturas_duplicadas()
		self._validar_prerrequisito_circular()

	def on_update(self):
		self._recalcular_duracion_programa()
		self._sincronizar_program_courses()

	def on_trash(self):
		self._recalcular_duracion_programa()
		self._sincronizar_program_courses(excluir_modulo=self.name)

	def _recalcular_duracion_programa(self):
		"""Actualiza program_duration en el Program padre al guardar o eliminar un módulo."""
		if not self.program:
			return
		result = frappe.db.sql(
			"SELECT COALESCE(SUM(total_hours), 0) FROM `tabProgram Module` WHERE program = %s",
			self.program,
		)
		total = result[0][0] if result else 0
		frappe.db.set_value("Program", self.program, "program_duration", total)

	def _calcular_horas_totales(self):
		"""Suma horas de las asignaturas; si no hay filas o ninguna tiene horas, usa los campos manuales."""
		if self.courses_in_module:
			theory_sum = sum(r.theory_hours or 0 for r in self.courses_in_module)
			practical_sum = sum(r.practical_hours or 0 for r in self.courses_in_module)
			if theory_sum or practical_sum:
				self.theory_hours = theory_sum
				self.practical_hours = practical_sum
		self.total_hours = (self.theory_hours or 0) + (self.practical_hours or 0)

	def _validar_tipo_programa(self):
		"""El programa asociado debe ser de tipo Modular o Técnico, no Libre."""
		if not self.program:
			return
		program_type = frappe.db.get_value("Program", self.program, "program_type")
		if program_type not in ("Modular", "Técnico"):
			frappe.throw(
				f"El programa '{self.program}' es de tipo '{program_type or 'sin definir'}'. "
				"Solo los programas de tipo Modular o Técnico admiten módulos."
			)

	def _validar_tipo_asignaturas(self):
		"""Una asignatura de tipo Libre no puede agregarse a un módulo."""
		for row in self.courses_in_module:
			if not row.course:
				continue
			course_type = frappe.db.get_value("Course", row.course, "course_type")
			if course_type not in ("Modular", "Técnico"):
				frappe.throw(
					f"La asignatura '{row.course}' es de tipo '{course_type or 'sin definir'}' y no puede "
					f"agregarse a un módulo. Solo asignaturas de tipo Modular o Técnico "
					f"pueden pertenecer a un módulo."
				)

	def _validar_asignaturas_duplicadas(self):
		"""No permite agregar la misma asignatura dos veces en el módulo."""
		cursos_vistos = set()
		for row in self.courses_in_module:
			if not row.course:
				continue
			if row.course in cursos_vistos:
				frappe.throw(
					f"La asignatura '{row.course}' está duplicada en la tabla "
					f"de asignaturas del módulo. Cada asignatura debe aparecer "
					f"una sola vez."
				)
			cursos_vistos.add(row.course)

	def _sincronizar_program_courses(self, excluir_modulo=None):
		"""Reconstruye tabProgram Course del Program padre con todos los cursos de sus módulos.

		tabProgram Course es la fuente que usa todo el framework (get_program_courses,
		api.py, utils.py, student_group_creation_tool, etc.). Para programas Modulares
		y Técnicos los cursos viven en Program Module Course, por lo que hay que
		mantener este espejo sincronizado para que el resto del sistema funcione.
		"""
		if not self.program:
			return

		program_type = frappe.db.get_value("Program", self.program, "program_type")
		if program_type not in ("Modular", "Técnico"):
			return

		# Recolecta todos los cursos de todos los módulos del programa,
		# excepto el módulo que se está eliminando (on_trash).
		filters = {"program": self.program}
		if excluir_modulo:
			filters["name"] = ("!=", excluir_modulo)

		modulos = frappe.get_all(
			"Program Module",
			filters=filters,
			fields=["name"],
		)

		cursos_vistos = set()
		filas_nuevas = []
		for mod in modulos:
			asignaturas = frappe.get_all(
				"Program Module Course",
				filters={"parent": mod.name},
				fields=["course", "is_mandatory"],
				order_by="order_no asc, idx asc",
			)
			for a in asignaturas:
				if not a.course or a.course in cursos_vistos:
					continue
				cursos_vistos.add(a.course)
				course_name = frappe.db.get_value("Course", a.course, "course_name") or ""
				filas_nuevas.append({
					"course": a.course,
					"course_name": course_name,
					"required": 1 if a.is_mandatory else 0,
				})

		# Reemplaza las filas existentes en tabProgram Course para este programa.
		frappe.db.delete("Program Course", {"parent": self.program})
		for i, fila in enumerate(filas_nuevas, start=1):
			frappe.db.sql(
				"""INSERT INTO `tabProgram Course`
					(name, parent, parenttype, parentfield, idx, course, course_name, required)
				VALUES (%s, %s, 'Program', 'courses', %s, %s, %s, %s)""",
				(frappe.generate_hash("", 10), self.program, i, fila["course"], fila["course_name"], fila["required"]),
			)

	def _validar_prerrequisito_circular(self):
		"""Un módulo no puede ser prerrequisito de sí mismo."""
		for row in self.prerequisites:
			if row.prerequisite_module == self.name:
				frappe.throw(
					"Un módulo no puede ser prerrequisito de sí mismo."
				)
