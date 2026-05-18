import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields as _create_custom_fields


def create_custom_fields():
	"""Crea los campos personalizados del SGF Escazú en los doctypes existentes de Frappe Education."""
	fields = get_custom_fields()
	_create_custom_fields(fields, update=True)


def get_custom_fields():
	"""Devuelve el diccionario de custom fields agrupados por doctype."""
	return {
		"Course": [
			# --- Información básica del curso ---
			{
				"fieldname": "course_code",
				"label": "Código del curso",
				"fieldtype": "Data",
				"insert_after": "course_status",
			},
			# --- Sección: Configuración académica ---
			{
				"fieldname": "academic_config_section",
				"label": "Configuración académica",
				"fieldtype": "Section Break",
				"insert_after": "course_code",
			},
			{
				"fieldname": "credits",
				"label": "Créditos",
				"fieldtype": "Float",
				"precision": "2",
				"insert_after": "academic_config_section",
			},
			{
				"fieldname": "theory_hours",
				"label": "Horas teóricas",
				"fieldtype": "Float",
				"precision": "2",
				"insert_after": "credits",
			},
			{
				"fieldname": "practical_hours",
				"label": "Horas prácticas",
				"fieldtype": "Float",
				"precision": "2",
				"insert_after": "theory_hours",
			},
			{
				"fieldname": "total_hours",
				"label": "Total de horas",
				"fieldtype": "Float",
				"precision": "2",
				"read_only": 1,
				"description": "Calculado automáticamente",
				"insert_after": "practical_hours",
			},
			{
				"fieldname": "modality",
				"label": "Modalidad",
				"fieldtype": "Select",
				"options": "\nPresencial\nVirtual\nHíbrida",
				"insert_after": "total_hours",
			},
			{
				"fieldname": "course_objective",
				"label": "Objetivo general del curso",
				"fieldtype": "Text Editor",
				"insert_after": "modality",
			},
			{
				"fieldname": "min_grade",
				"label": "Calificación mínima de aprobación",
				"fieldtype": "Float",
				"precision": "2",
				"default": "70",
				"insert_after": "course_objective",
			},
			{
				"fieldname": "min_attendance",
				"label": "Porcentaje mínimo de asistencia",
				"fieldtype": "Float",
				"precision": "2",
				"default": "80",
				"insert_after": "min_grade",
			},
			# --- Sección: Plan de estudios (solo Modular / Técnico) ---
			{
				"fieldname": "study_plan_section",
				"label": "Plan de estudios",
				"fieldtype": "Section Break",
				"depends_on": "eval:doc.course_type=='Modular' || doc.course_type=='Técnico'",
				"insert_after": "min_attendance",
			},
			{
				"fieldname": "study_cycle",
				"label": "Ciclo de estudios",
				"fieldtype": "Data",
				"description": "Ejemplo: Semestral, Cuatrimestral, Anual",
				"insert_after": "study_plan_section",
			},
			{
				"fieldname": "approval_criteria",
				"label": "Criterios generales de aprobación",
				"fieldtype": "Text Editor",
				"insert_after": "study_cycle",
			},
		],
		"Topic": [
			{
				"fieldname": "unit_number",
				"label": "Número de unidad",
				"fieldtype": "Int",
				"insert_after": "topic_name",
			},
			{
				"fieldname": "estimated_hours",
				"label": "Horas estimadas",
				"fieldtype": "Float",
				"insert_after": "unit_number",
			},
			{
				"fieldname": "unit_objective",
				"label": "Objetivo de la unidad",
				"fieldtype": "Small Text",
				"insert_after": "estimated_hours",
			},
			{
				"fieldname": "competencies",
				"label": "Competencias que desarrolla",
				"fieldtype": "Text Editor",
				"insert_after": "unit_objective",
			},
		],
	}
